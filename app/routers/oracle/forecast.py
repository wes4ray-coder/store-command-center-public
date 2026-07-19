"""The forecasting tournament round: each active analyst researches an asset and
commits to a bold-but-calibrated price call. Runs in a background thread; exposes
the start + live-status endpoints."""
import json as _json
import re as _re
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

from deps import *          # get_conn, orch, logger, _call_lmstudio
from services import *      # (kept consistent with sibling routers)

from ._base import router, CRYPTO_IDS, _meta_get, _meta_set, _assets, _price, _searx


def _parse_json(raw: str) -> Optional[dict]:
    raw = _re.sub(r"<think>.*?</think>", "", raw or "", flags=_re.DOTALL)
    m = _re.search(r"```(?:json)?\s*(.*?)```", raw, flags=_re.DOTALL)
    if m:
        raw = m.group(1)
    m = _re.search(r"\{.*\}", raw, flags=_re.DOTALL)
    if not m:
        return None
    frag = m.group(0)
    for candidate in (frag,
                      frag.replace("'", '"'),                       # single→double quotes
                      _re.sub(r",\s*([}\]])", r"\1", frag)):         # strip trailing commas
        try:
            return _json.loads(candidate)
        except Exception:
            continue
    return None


def _wait_task(tid: int, timeout: float = 600) -> Optional[str]:
    end = time.time() + timeout
    while time.time() < end:
        p = orch.poll(tid)
        if p["status"] == "done":
            return p.get("result")
        if p["status"] in ("failed", "error", "cancelled", "not_found"):
            return None
        time.sleep(2)
    return None


ORACLE_SYS = (
    "You are {name}, an elite market forecaster competing in a live tournament against "
    "other AI analysts. You are scored on THREE things: (1) getting the DIRECTION right, "
    "(2) how CLOSE your target price is, and (3) how FAR OUT you called it — a correct "
    "long-horizon call is worth far more than a safe short one, so be bold but calibrated. "
    "First reason about real-world CATALYSTS — macroeconomics (rates, inflation, jobs), "
    "government/regulation, world news, corporate/on-chain events, and social/media "
    "sentiment — using the research provided. Then commit to a number.\n"
    "Respond with STRICT JSON and NOTHING else:\n"
    '{"direction":"up"|"down","target_price":<number>,"horizon_days":<int 7-90>,'
    '"confidence":<0..1>,"thesis":"2-3 sentences naming the specific real-world catalysts '
    'driving your call"}'
)


def _agent_lessons(agent_id: int, limit: int = 5) -> str:
    conn = get_conn()
    rows = conn.execute("SELECT text FROM oracle_memory WHERE agent_id=? ORDER BY id DESC LIMIT ?",
                        (agent_id, limit)).fetchall()
    conn.close()
    if not rows:
        return "(no past results yet — this is your first tournament round)"
    return "\n".join(f"- {r['text']}" for r in reversed(rows))


def _forecast(agent: dict, asset: str, price: float, research: list) -> Optional[dict]:
    """Run ONE model's forecast for one asset (blocking on the orch task)."""
    snips = "\n".join(f"- {r['title']}: {r['snippet']}" for r in research) or "(no research returned)"
    lessons = _agent_lessons(agent["id"])
    user = (f"ASSET: {asset}\nCURRENT PRICE: ${price:,.4f}\n\n"
            f"RESEARCH — real-world signals right now:\n{snips}\n\n"
            f"YOUR PAST TOURNAMENT RESULTS (learn from them):\n{lessons}\n\n"
            f"Make your call for {asset}.")
    sysmsg = ORACLE_SYS.replace("{name}", agent["name"])   # NOT .format — prompt has literal { } JSON braces
    d = None
    for attempt in range(2):
        extra = "" if attempt == 0 else (
            "\n\nYour previous reply was NOT valid JSON. Reply with ONLY the JSON object "
            "on a single line — no prose, no <think>, no markdown fences.")
        um = user + extra
        # priority=2 (background): the tournament is autonomous batch work — it must
        # yield the GPU to user-facing (priority 0) LLM calls, per the queue convention.
        tid = orch.submit_llm(lambda u=um: _call_lmstudio(sysmsg, u, max_tokens=1200),
                              desc=f"oracle {agent['name']} · {asset}", model=agent["model"], priority=2)
        raw = _wait_task(tid, 300)   # cap so one slow model can't stall the whole round
        if not raw:
            logger.warning("oracle %s · %s: empty response (try %d)", agent["name"], asset, attempt + 1)
            continue
        d = _parse_json(raw)
        if d and "direction" in d and "target_price" in d:
            break
        logger.warning("oracle %s · %s: unparseable (try %d): %s", agent["name"], asset,
                       attempt + 1, (raw or "")[:180].replace("\n", " "))
        d = None
    if not d:
        return None
    try:
        d["direction"] = "up" if str(d["direction"]).lower().startswith("u") else "down"
        d["target_price"] = float(d["target_price"])
        d["horizon_days"] = max(7, min(int(d.get("horizon_days", 30)), 90))
        d["confidence"] = max(0.0, min(float(d.get("confidence", 0.5)), 1.0))
        d["thesis"] = str(d.get("thesis", ""))[:600]
    except Exception:
        return None
    return d


# ── the tournament round (background) ─────────────────────────────────────────
_round = {"running": False, "target": 0, "done": 0, "made": 0, "started_at": None, "log": []}
_round_lock = threading.Lock()


def _rlog(msg):
    _round["log"].append(msg)
    _round["log"][:] = _round["log"][-40:]
    logger.info("oracle round: %s", msg)


def _run_round(n_assets: int):
    conn = get_conn()
    agents = [dict(r) for r in conn.execute("SELECT * FROM oracle_agents WHERE active=1 ORDER BY id").fetchall()]
    conn.close()
    all_assets = _assets()
    if not agents or not all_assets:
        _round.update(running=False)
        _rlog("no active agents or assets")
        return
    # rotate through the asset list so coverage spreads across rounds
    off = int(_meta_get("round_offset", "0") or 0)
    picks = [all_assets[(off + i) % len(all_assets)] for i in range(min(n_assets, len(all_assets)))]
    _meta_set("round_offset", (off + len(picks)) % len(all_assets))

    _round.update(running=True, target=len(agents) * len(picks), done=0, made=0,
                  started_at=datetime.now().isoformat(timespec="seconds"), log=[])
    _rlog(f"round start — {len(agents)} analysts × {len(picks)} assets: {', '.join(picks)}")
    try:
        # research each asset ONCE, share across all agents
        research, prices = {}, {}
        for a in picks:
            prices[a] = _price(a)
            month = datetime.now().strftime("%B %Y")
            research[a] = _searx(f"{a} price forecast {month} economic catalysts news")
            _rlog(f"researched {a} (${prices[a]}) — {len(research[a])} sources")
        # each analyst calls each asset (agent-by-agent to minimize model reloads)
        for ag in agents:
            for a in picks:
                if not prices.get(a):
                    _round["done"] += 1
                    _rlog(f"{ag['name']} · {a}: no price, skipped")
                    continue
                d = _forecast(ag, a, prices[a], research[a])
                if not d:
                    _round["done"] += 1
                    _rlog(f"{ag['name']} · {a}: no valid forecast")
                    continue
                resolve_at = (datetime.now() + timedelta(days=d["horizon_days"])).isoformat(timespec="seconds")
                market = "crypto" if a in CRYPTO_IDS else "stock"
                c = get_conn()
                c.execute(
                    "INSERT INTO oracle_predictions (agent_id,agent_name,market,asset,current_value,"
                    "direction,target_value,horizon_days,resolve_at,confidence,thesis,sources,status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'open')",
                    (ag["id"], ag["name"], market, a, prices[a], d["direction"], d["target_price"],
                     d["horizon_days"], resolve_at, d["confidence"], d["thesis"],
                     _json.dumps(research[a][:3])))
                c.commit(); c.close()
                _round["made"] += 1
                _round["done"] += 1
                arrow = "▲" if d["direction"] == "up" else "▼"
                _rlog(f"{ag['name']} · {a}: {arrow} ${d['target_price']:,.2f} in {d['horizon_days']}d "
                      f"(conf {d['confidence']:.0%})")
        _rlog(f"round complete — {_round['made']} predictions logged")
    except Exception as e:
        _rlog(f"round aborted: {str(e)[:120]}")
    finally:
        _round["running"] = False


class RoundIn(BaseModel):
    assets: int = 3


@router.post("/api/oracle/round")
def start_round(req: RoundIn):
    with _round_lock:
        if _round["running"]:
            raise HTTPException(409, "A round is already running.")
        n = max(1, min(int(req.assets or 3), 12))
        threading.Thread(target=_run_round, args=(n,), daemon=True, name="oracle-round").start()
    return {"ok": True}


@router.get("/api/oracle/round/status")
def round_status():
    return {k: _round[k] for k in ("running", "target", "done", "made", "started_at", "log")}
