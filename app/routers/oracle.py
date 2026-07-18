"""Oracle — a forecasting TOURNAMENT between local LLM models.

Several models compete as "analysts": each researches real-world catalysts
(economic / news / government / social) via searxng, then predicts where a crypto
or stock price is heading, how far out, and why. When the horizon arrives, the
prediction is auto-scored on: got the direction right, how CLOSE the target was,
and how FAR OUT the call was (longer correct calls score much higher). Each analyst
keeps a memory of its past hits/misses and feeds those lessons into future calls, so
they sharpen over time. A leaderboard ranks them. No money moves — this is pure
prediction sport whose winners can later inform the trading side.
"""
import json as _json
import re as _re
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import *          # get_conn, get_setting, orch, logger, _call_lmstudio
from services import *      # (kept consistent with sibling routers)

router = APIRouter()

SEARX_URL = "http://127.0.0.1:8899"

# The competitors. name → LM Studio model id (seeded on first use; toggle in the UI).
# Chosen for SPEED + reliable JSON on this single-GPU box. Gemma and Ministral were
# dropped — they took up to ~17 min/call and never returned clean JSON. Coder models
# are the most JSON-compliant; GLM-flash adds non-Qwen diversity.
DEFAULT_ANALYSTS = [
    ("GLM-4.7",        "zai-org/glm-4.7-flash"),
    ("GLM-4.6v",       "zai-org/glm-4.6v-flash"),
    ("Qwen3.5-9B",     "qwen/qwen3.5-9b"),
    ("Qwen-Coder-32B", "qwen2.5-coder-32b-instruct"),
    ("Qwen3-Coder-30B", "qwen3-coder-30b-a3b-instruct"),
]

# Auto-resolvable assets. Crypto → CoinGecko id; stocks come from stocks_watchlist.
CRYPTO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
              "DOGE": "dogecoin", "ADA": "cardano", "LTC": "litecoin"}


# ── schema ────────────────────────────────────────────────────────────────────
def _ensure_schema():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS oracle_agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, model TEXT,
        active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE IF NOT EXISTS oracle_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, agent_name TEXT,
        market TEXT, asset TEXT, current_value REAL, direction TEXT,
        target_value REAL, horizon_days INTEGER, resolve_at TEXT, confidence REAL,
        thesis TEXT, sources TEXT, status TEXT DEFAULT 'open',
        actual_value REAL, rel_error REAL, correct INTEGER, score REAL,
        created_at TEXT DEFAULT (datetime('now')), resolved_at TEXT);
    CREATE TABLE IF NOT EXISTS oracle_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, text TEXT,
        created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE IF NOT EXISTS oracle_meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    conn.commit()
    conn.close()

_ensure_schema()


def _seed_agents():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM oracle_agents").fetchone()["n"]
    if n == 0:
        for name, model in DEFAULT_ANALYSTS:
            conn.execute("INSERT INTO oracle_agents (name,model,active) VALUES (?,?,1)", (name, model))
        conn.commit()
    conn.close()

_seed_agents()


# ── small helpers ─────────────────────────────────────────────────────────────
def _meta_get(k, d=""):
    conn = get_conn(); r = conn.execute("SELECT v FROM oracle_meta WHERE k=?", (k,)).fetchone(); conn.close()
    return r["v"] if r else d


def _meta_set(k, v):
    conn = get_conn(); conn.execute("INSERT OR REPLACE INTO oracle_meta (k,v) VALUES (?,?)", (k, str(v)))
    conn.commit(); conn.close()


def _assets() -> list:
    """Tracked assets: the crypto majors + any non-crypto stock tickers on the watchlist."""
    out = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    wl = (get_setting("stocks_watchlist", "") or "").upper()
    for s in [x.strip() for x in wl.split(",") if x.strip()]:
        if "-" in s or s in CRYPTO_IDS:      # skip BTC-USD style + crypto dupes
            continue
        out.append(s)
    return out


def _price(asset: str) -> Optional[float]:
    """Current USD price. Crypto via CoinGecko, stocks via yfinance. None on failure."""
    try:
        if asset in CRYPTO_IDS:
            r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                             params={"ids": CRYPTO_IDS[asset], "vs_currencies": "usd"}, timeout=15)
            return float(r.json()[CRYPTO_IDS[asset]]["usd"])
        import yfinance as yf
        fi = yf.Ticker(asset).fast_info
        p = None
        for k in ("last_price", "lastPrice"):
            p = getattr(fi, k, None) if hasattr(fi, k) else (fi.get(k) if hasattr(fi, "get") else None)
            if p:
                break
        return float(p) if p else None
    except Exception as e:
        logger.warning("oracle price(%s) failed: %s", asset, e)
        return None


def _searx(query: str, n: int = 5) -> list:
    try:
        r = requests.get(f"{SEARX_URL}/search",
                         params={"q": query, "format": "json", "language": "en"}, timeout=20)
        r.raise_for_status()
        return [{"title": (x.get("title") or "")[:160], "url": x.get("url") or "",
                 "snippet": (x.get("content") or "")[:280]}
                for x in (r.json().get("results") or [])[:n]]
    except Exception as e:
        logger.warning("oracle searx failed: %s", e)
        return []


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


# ── resolution + scoring ──────────────────────────────────────────────────────
def _score(pred: dict, actual: float):
    cur, tgt = pred["current_value"], pred["target_value"]
    actual_dir = "up" if actual >= cur else "down"
    correct = pred["direction"] == actual_dir
    rel = abs(actual - tgt) / actual if actual else 1.0
    closeness = 20.0 * max(0.0, 1.0 - rel)          # perfect target = +20
    base = (10.0 if correct else -5.0) + closeness
    horizon_mult = 1.0 + pred["horizon_days"] / 30.0  # longer correct calls worth more
    return round(base * horizon_mult, 2), correct, round(rel, 4)


def _resolve_due() -> int:
    conn = get_conn()
    due = [dict(r) for r in conn.execute(
        "SELECT * FROM oracle_predictions WHERE status='open' AND resolve_at<=?",
        (datetime.now().isoformat(timespec="seconds"),)).fetchall()]
    conn.close()
    resolved = 0
    for p in due:
        actual = _price(p["asset"])
        if actual is None:
            continue
        score, correct, rel = _score(p, actual)
        conn = get_conn()
        conn.execute("UPDATE oracle_predictions SET status='resolved',actual_value=?,rel_error=?,"
                     "correct=?,score=?,resolved_at=? WHERE id=?",
                     (actual, rel, 1 if correct else 0, score,
                      datetime.now().isoformat(timespec="seconds"), p["id"]))
        move = "▲" if actual >= p["current_value"] else "▼"
        lesson = (f"{p['asset']}: called {p['direction']} → ${p['target_value']:,.2f} over "
                  f"{p['horizon_days']}d. Actual {move} ${actual:,.2f} "
                  f"({'RIGHT' if correct else 'WRONG'}, {rel:.1%} off, score {score:+}). "
                  f"Thesis was: {p['thesis'][:180]}")
        conn.execute("INSERT INTO oracle_memory (agent_id,text) VALUES (?,?)", (p["agent_id"], lesson))
        conn.commit(); conn.close()
        resolved += 1
    return resolved


@router.post("/api/oracle/resolve")
def resolve_now():
    return {"resolved": _resolve_due()}


# ── agents + leaderboard + views ──────────────────────────────────────────────
def _agent_stats(agent_id: int) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved,"
        " SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open,"
        " SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS correct,"
        " COALESCE(SUM(score),0) AS score,"
        " COALESCE(AVG(horizon_days),0) AS avg_h "
        "FROM oracle_predictions WHERE agent_id=?", (agent_id,)).fetchone()
    conn.close()
    r = dict(row)
    resolved = r["resolved"] or 0
    return {"score": round(r["score"] or 0, 1), "resolved": resolved, "open": r["open"] or 0,
            "correct": r["correct"] or 0,
            "accuracy": round(100 * (r["correct"] or 0) / resolved, 1) if resolved else None,
            "avg_horizon": round(r["avg_h"] or 0, 1)}


@router.get("/api/oracle/agents")
def list_agents():
    conn = get_conn()
    agents = [dict(r) for r in conn.execute("SELECT * FROM oracle_agents ORDER BY id").fetchall()]
    conn.close()
    for a in agents:
        a["stats"] = _agent_stats(a["id"])
    return {"agents": agents, "assets": _assets()}


@router.get("/api/oracle/leaderboard")
def leaderboard():
    d = list_agents()
    lb = sorted(d["agents"], key=lambda a: a["stats"]["score"], reverse=True)
    return {"leaderboard": lb, "assets": d["assets"]}


class AgentToggle(BaseModel):
    active: bool


@router.post("/api/oracle/agents/{aid}/toggle")
def toggle_agent(aid: int, body: AgentToggle):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM oracle_agents WHERE id=?", (aid,)).fetchone():
        conn.close(); raise HTTPException(404, "No such analyst")
    conn.execute("UPDATE oracle_agents SET active=? WHERE id=?", (1 if body.active else 0, aid))
    conn.commit(); conn.close()
    return {"ok": True}


@router.get("/api/oracle/predictions")
def list_predictions(status: Optional[str] = None, agent_id: Optional[int] = None, limit: int = 100):
    q = "SELECT * FROM oracle_predictions WHERE 1=1"
    args = []
    if status:
        q += " AND status=?"; args.append(status)
    if agent_id:
        q += " AND agent_id=?"; args.append(agent_id)
    q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(q, args).fetchall()]
    conn.close()
    for r in rows:
        try:
            r["sources"] = _json.loads(r["sources"]) if r.get("sources") else []
        except Exception:
            r["sources"] = []
    return {"predictions": rows}


@router.get("/api/oracle/memory/{aid}")
def agent_memory(aid: int, limit: int = 30):
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT text,created_at FROM oracle_memory WHERE agent_id=? ORDER BY id DESC LIMIT ?",
        (aid, limit)).fetchall()]
    conn.close()
    return {"lessons": rows}


# ── autonomous cadence: resolve due predictions + optionally run a daily round ──
_auto = {"thread": None}


def _auto_loop():
    time.sleep(90)
    while True:
        try:
            if (get_setting("oracle_auto", "on") or "on").lower() != "off":
                n = _resolve_due()
                if n:
                    logger.info("oracle auto: resolved %d prediction(s)", n)
                # a fresh round once a day if the last one is old and none is running
                last = _meta_get("last_round_day", "")
                today = time.strftime("%Y-%m-%d")
                if today != last and not _round["running"]:
                    _meta_set("last_round_day", today)
                    threading.Thread(target=_run_round, args=(3,), daemon=True,
                                     name="oracle-round-auto").start()
        except Exception as e:
            logger.warning("oracle auto loop: %s", e)
        time.sleep(3600)


def start_auto():
    if _auto["thread"]:
        return
    t = threading.Thread(target=_auto_loop, daemon=True, name="oracle-auto")
    _auto["thread"] = t
    t.start()
    logger.info("oracle_auto started")
