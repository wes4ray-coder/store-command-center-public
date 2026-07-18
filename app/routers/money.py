"""Money — real-dollar mission control.

The agent swarm's purpose here is to make the owner REAL dollars (not in-game gold).
Shop search queries (demand signals) flow in from the storefront; "the company"
reviews them against the current catalog with the LLM and proposes money missions:
product gaps we should carry, affiliate/deal opportunities, online income ideas,
and local carpentry work leads (your local area) for the Acme Carpentry front.
Missions follow the same approve/reject queue pattern as world_ops prayers, and an
approved mission is announced into The Company world (world_events + a named agent).

Signals ingest (/api/money/signals POST) is designed to be allowlisted through the
auth middleware — it self-guards with the X-Money-Token header, which must equal
the `money_signal_token` setting.
"""
import json as _json
import hmac as _hmac
import random as _random
import requests
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

from deps import *          # get_conn, get_setting, orch, _call_lmstudio, get_prompt, logger
from services import *      # (kept consistent with sibling routers)

router = APIRouter()


# ── schema (kept here to stay decoupled from the concurrently-edited db.py) ──
def _ensure_schema():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS money_signals (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        source        TEXT,
        query         TEXT,
        results_count INTEGER DEFAULT 0,
        meta          TEXT DEFAULT '',
        status        TEXT DEFAULT 'new',
        created_at    TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS money_missions (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        kind             TEXT,
        title            TEXT,
        detail           TEXT,
        source_signal_id INTEGER,
        est_value_cents  INTEGER DEFAULT 0,
        status           TEXT DEFAULT 'proposed',
        agent            TEXT DEFAULT '',
        result           TEXT DEFAULT '',
        created_at       TEXT DEFAULT (datetime('now')),
        updated_at       TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()

_ensure_schema()


MISSION_KINDS = ("product_gap", "online_income", "carpentry_lead", "other")
MISSION_STATUSES = ("proposed", "approved", "rejected", "done")

# GOAL framing for the company review. Editable copy may live in the prompt
# registry under `money_gap_review`; this local constant is the fallback.
MONEY_GAP_REVIEW_PROMPT = (
    "You are the revenue strategist for Acme — a small indie operation that runs an "
    "online shop (geeky tees, 3D-printable models, software, curated gadget deals) and a "
    "local carpentry business (Acme Carpentry, serving your local area). "
    "Your ONLY goal is to make the owner REAL dollars — not in-game gold: find product "
    "gaps we should carry, affiliate/deal opportunities, online income ideas, and local "
    "carpentry work leads.\n\n"
    "You are given (1) recent shop SEARCH QUERIES from visitors (with how many results "
    "each found) and (2) the CURRENT CATALOG of product titles. Identify products or "
    "niches we DON'T carry but should (demand gaps — especially queries with zero/few "
    "results), plus any other money-making leads the queries imply.\n\n"
    "Return a STRICT JSON array and nothing else — no markdown, no commentary:\n"
    '[{"kind": "product_gap" | "online_income" | "other", "title": "short actionable '
    'title", "detail": "1-3 sentences: what to do and why it will earn", '
    '"est_value_usd": <number, realistic monthly USD estimate>}]\n'
    "3 to 8 items. Be concrete and realistic; skip anything that can't plausibly earn."
)


def _review_system_prompt() -> str:
    try:
        return get_prompt("money_gap_review")
    except Exception:
        return MONEY_GAP_REVIEW_PROMPT


def _mission_row(r) -> dict:
    return dict(r)


# ── demand signals ────────────────────────────────────────────────────────────
class SignalIn(BaseModel):
    source: str
    query: str
    results_count: int = 0
    meta: Optional[str] = ""


@router.post("/api/money/signals")
def add_signal(sig: SignalIn, x_money_token: Optional[str] = Header(None)):
    """Ingest one demand signal (e.g. a storefront search). This endpoint is meant to
    be reachable WITHOUT a session (allowlisted in the auth middleware), so it guards
    itself: X-Money-Token must equal the `money_signal_token` setting."""
    token = get_setting("money_signal_token", "") or ""
    if not token or not x_money_token or not _hmac.compare_digest(str(x_money_token), str(token)):
        raise HTTPException(403, "bad or missing X-Money-Token")
    if not (sig.query or "").strip():
        raise HTTPException(400, "query required")
    conn = get_conn()
    try:
        # crude rate limit: at most 200 signals per rolling hour
        n = conn.execute("SELECT COUNT(*) AS n FROM money_signals "
                         "WHERE created_at >= datetime('now','-1 hour')").fetchone()["n"]
        if n >= 200:
            raise HTTPException(429, "signal rate limit exceeded (200/hour)")
        cur = conn.execute(
            "INSERT INTO money_signals (source, query, results_count, meta) VALUES (?,?,?,?)",
            ((sig.source or "shop").strip(), sig.query.strip(),
             int(sig.results_count or 0), sig.meta or ""))
        conn.commit()
        row = conn.execute("SELECT * FROM money_signals WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.get("/api/money/signals")
def list_signals(status: Optional[str] = None, limit: int = 100):
    conn = get_conn()
    try:
        if status:
            rows = conn.execute("SELECT * FROM money_signals WHERE status=? ORDER BY id DESC LIMIT ?",
                                (status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM money_signals ORDER BY "
                                "CASE status WHEN 'new' THEN 0 ELSE 1 END, id DESC LIMIT ?",
                                (limit,)).fetchall()
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM money_signals GROUP BY status")}
        return {"signals": [dict(r) for r in rows], "counts": counts}
    finally:
        conn.close()


# ── the company review: signals + catalog → proposed missions ────────────────
def _catalog_titles(limit: int = 150) -> list:
    """Current product titles: everything pushed to WordPress plus the local
    affiliate/software catalog (portal tables). Best-effort — an empty catalog
    just means the LLM treats every queried niche as a gap."""
    titles = []
    conn = get_conn()
    try:
        try:
            for r in conn.execute(
                    "SELECT title FROM portal_pushes WHERE kind='product' AND title IS NOT NULL "
                    "AND title!='' ORDER BY pushed_at DESC LIMIT ?", (limit,)).fetchall():
                titles.append(r["title"])
        except Exception:
            pass
        try:
            for r in conn.execute(
                    "SELECT title FROM portal_affiliate ORDER BY updated_at DESC LIMIT ?",
                    (limit,)).fetchall():
                titles.append(r["title"])
        except Exception:
            pass
    finally:
        conn.close()
    seen, out = set(), []
    for t in titles:
        k = (t or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(t.strip())
    return out[:limit]


def _parse_missions_json(raw: str) -> list:
    """Defensive parse of the LLM reply into a list of mission dicts."""
    import re as _re
    raw = _re.sub(r"<think>.*?</think>", "", raw or "", flags=_re.DOTALL).strip()
    raw = _re.sub(r"^```(?:json)?\s*", "", raw)
    raw = _re.sub(r"\s*```$", "", raw).strip()
    data = None
    try:
        data = _json.loads(raw)
    except Exception:
        i, j = raw.find("["), raw.rfind("]")
        if i != -1 and j > i:
            try:
                data = _json.loads(raw[i:j + 1])
            except Exception:
                data = None
    if isinstance(data, dict):   # model wrapped the array in an object
        for key in ("missions", "items", "results", "leads"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return []
    out = []
    for m in data:
        if not isinstance(m, dict):
            continue
        title = str(m.get("title", "")).strip()
        if not title:
            continue
        kind = str(m.get("kind", "other")).strip()
        if kind not in MISSION_KINDS:
            kind = "other"
        try:
            usd = float(m.get("est_value_usd") or 0)
        except Exception:
            usd = 0.0
        out.append({"kind": kind, "title": title[:200],
                    "detail": str(m.get("detail", "")).strip()[:1000],
                    "est_value_cents": max(0, int(round(usd * 100)))})
    return out


@router.post("/api/money/review")
def run_review():
    """The company reviews the searches: take all 'new' signals + the current catalog,
    ask the LLM ONCE for demand gaps / money leads, insert them as proposed missions,
    and mark the signals reviewed. Returns a task_id (poll /api/task/{id})."""
    conn = get_conn()
    signals = [dict(r) for r in conn.execute(
        "SELECT * FROM money_signals WHERE status='new' ORDER BY id ASC LIMIT 200").fetchall()]
    conn.close()
    if not signals:
        raise HTTPException(400, "No new signals to review.")
    titles = _catalog_titles()
    sig_lines = "\n".join(
        f"- \"{s['query']}\" (source: {s['source'] or 'shop'}, results found: {s['results_count']})"
        for s in signals)
    cat_lines = "\n".join(f"- {t}" for t in titles) if titles else "(catalog is empty)"
    user = (f"SHOP SEARCH QUERIES ({len(signals)} recent):\n{sig_lines}\n\n"
            f"CURRENT CATALOG ({len(titles)} product titles):\n{cat_lines}")
    sig_ids = [s["id"] for s in signals]
    first_id = sig_ids[0]

    def _work():
        raw = _call_lmstudio(_review_system_prompt(), user, max_tokens=2000, json_mode=True)
        missions = _parse_missions_json(raw)
        c = get_conn()
        try:
            for m in missions:
                c.execute(
                    """INSERT INTO money_missions (kind,title,detail,source_signal_id,est_value_cents)
                       VALUES (?,?,?,?,?)""",
                    (m["kind"], m["title"], m["detail"], first_id, m["est_value_cents"]))
            qmarks = ",".join("?" * len(sig_ids))
            c.execute(f"UPDATE money_signals SET status='reviewed' WHERE id IN ({qmarks})", sig_ids)
            c.commit()
        finally:
            c.close()
        return {"proposed": len(missions), "signals_reviewed": len(sig_ids),
                "missions": missions}

    tid = orch.submit_llm(_work, desc=f"Money review: {len(signals)} signals", priority=2)  # autonomous
    return {"task_id": tid, "signals": len(signals)}


# ── carpentry lead hunting (searxng → LLM → missions) ────────────────────────
SEARX_URL = "http://127.0.0.1:8899"

DEFAULT_LEAD_QUERIES = [
    "carpenter needed your town",
    "handyman wanted Wood County Texas",
    "finish carpentry work DFW",
    "deck repair contractor wanted East Texas",
    "home repair help wanted Tyler TX",
]

LEAD_HUNT_PROMPT = (
    "You screen web search results to find REAL local work leads for Acme Carpentry — "
    "a one-man precision repair / finish-carpentry / remodel operation based in your town, "
    "serving the local area and DFW. From the search results given, pick ONLY entries that "
    "plausibly lead to paid carpentry/handyman work (job posts, 'looking for a carpenter' "
    "asks, gig boards, bid requests). Skip ads, directories, and how-to articles. "
    "Respond with STRICT JSON: an array of objects "
    '[{"title": str, "detail": str (1-2 sentences INCLUDING the url), "est_value_usd": number}]. '
    "Empty array if nothing qualifies."
)


def _searx(query: str, n: int = 5) -> list:
    try:
        r = requests.get(f"{SEARX_URL}/search",
                         params={"q": query, "format": "json", "language": "en"},
                         timeout=20)
        r.raise_for_status()
        out = []
        for res in (r.json().get("results") or [])[:n]:
            out.append({"title": (res.get("title") or "")[:200],
                        "url": res.get("url") or "",
                        "snippet": (res.get("content") or "")[:300]})
        return out
    except Exception as e:
        logger.warning("searx query failed (%s): %s", query, e)
        return []


@router.post("/api/money/leads/hunt")
def hunt_leads():
    """Hunt local carpentry work leads: searxng sweep → LLM screen → proposed
    carpentry_lead missions. Queries overridable via setting `money_lead_queries`
    (one per line). Returns a task_id (poll /api/task/{id})."""
    qraw = get_setting("money_lead_queries", "") or ""
    queries = [q.strip() for q in qraw.splitlines() if q.strip()] or DEFAULT_LEAD_QUERIES

    results, seen_urls = [], set()
    for q in queries:
        for res in _searx(q):
            if res["url"] and res["url"] not in seen_urls:
                seen_urls.add(res["url"])
                results.append(res)
    if not results:
        raise HTTPException(502, "searxng returned no results (is it running on :8899?)")

    # skip urls already captured in existing carpentry_lead missions
    conn = get_conn()
    known = " ".join(r["detail"] or "" for r in conn.execute(
        "SELECT detail FROM money_missions WHERE kind='carpentry_lead'").fetchall())
    conn.close()
    fresh = [r for r in results if r["url"] not in known]
    if not fresh:
        return {"task_id": None, "results": len(results), "fresh": 0,
                "note": "all results already known"}

    lines = "\n".join(f"- {r['title']} | {r['url']} | {r['snippet']}" for r in fresh[:40])
    user = f"SEARCH RESULTS ({len(fresh)} fresh):\n{lines}"

    def _work():
        raw = _call_lmstudio(
            get_prompt("money_lead_hunt") if _has_prompt("money_lead_hunt") else LEAD_HUNT_PROMPT,
            user, max_tokens=1800, json_mode=True)
        missions = _parse_missions_json(raw)
        c = get_conn()
        try:
            for m in missions:
                c.execute(
                    """INSERT INTO money_missions (kind,title,detail,est_value_cents)
                       VALUES ('carpentry_lead',?,?,?)""",
                    (m["title"], m["detail"], m["est_value_cents"]))
            c.commit()
        finally:
            c.close()
        return {"proposed": len(missions), "screened": len(fresh)}

    tid = orch.submit_llm(_work, desc=f"Lead hunt: {len(fresh)} results", priority=2)  # autonomous
    return {"task_id": tid, "results": len(results), "fresh": len(fresh)}


def _has_prompt(key: str) -> bool:
    try:
        return bool(get_prompt(key))
    except Exception:
        return False


# ── missions queue ────────────────────────────────────────────────────────────
class MissionIn(BaseModel):
    kind: str = "other"
    title: str
    detail: Optional[str] = ""
    est_value_cents: int = 0


@router.get("/api/money/missions")
def list_missions(status: Optional[str] = None, limit: int = 100):
    conn = get_conn()
    try:
        if status:
            rows = conn.execute("SELECT * FROM money_missions WHERE status=? ORDER BY id DESC LIMIT ?",
                                (status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM money_missions ORDER BY "
                                "CASE status WHEN 'proposed' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, "
                                "id DESC LIMIT ?", (limit,)).fetchall()
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM money_missions GROUP BY status")}
        return {"missions": [_mission_row(r) for r in rows], "counts": counts}
    finally:
        conn.close()


@router.post("/api/money/missions")
def create_mission(m: MissionIn):
    """Manual mission entry (e.g. a carpentry lead idea you spotted yourself)."""
    if not (m.title or "").strip():
        raise HTTPException(400, "title required")
    kind = m.kind if m.kind in MISSION_KINDS else "other"
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO money_missions (kind,title,detail,est_value_cents) VALUES (?,?,?,?)",
            (kind, m.title.strip(), m.detail or "", max(0, int(m.est_value_cents or 0))))
        conn.commit()
        row = conn.execute("SELECT * FROM money_missions WHERE id=?", (cur.lastrowid,)).fetchone()
        return _mission_row(row)
    finally:
        conn.close()


def _get_mission(conn, mid: int):
    row = conn.execute("SELECT * FROM money_missions WHERE id=?", (mid,)).fetchone()
    if not row:
        raise HTTPException(404, "mission not found")
    return row


def _set_status(mid: int, status: str, result: Optional[str] = None, expect: Optional[str] = None):
    conn = get_conn()
    try:
        row = _get_mission(conn, mid)
        if expect and row["status"] != expect:
            raise HTTPException(400, f"mission is '{row['status']}', expected '{expect}'")
        if result is not None:
            conn.execute("UPDATE money_missions SET status=?, result=?, updated_at=datetime('now') WHERE id=?",
                         (status, result, mid))
        else:
            conn.execute("UPDATE money_missions SET status=?, updated_at=datetime('now') WHERE id=?",
                         (status, mid))
        conn.commit()
        return dict(_get_mission(conn, mid))
    finally:
        conn.close()


@router.post("/api/money/missions/{mid}/approve")
def approve_mission(mid: int):
    """Approve a mission. Best-effort world integration: assign a random Company
    agent to it and announce it on the town's world_events feed — a failure there
    must never break the approval itself."""
    mission = _set_status(mid, "approved", expect="proposed")
    try:
        conn = get_conn()
        try:
            agent = conn.execute(
                "SELECT key, name FROM world_agents ORDER BY RANDOM() LIMIT 1").fetchone()
            agent_key = agent["key"] if agent else None
            agent_name = (agent["name"] if agent else "") or ""
            if agent_name:
                conn.execute("UPDATE money_missions SET agent=?, updated_at=datetime('now') WHERE id=?",
                             (agent_name, mid))
                mission["agent"] = agent_name
            usd = (mission.get("est_value_cents") or 0) / 100
            who = agent_name or "The Company"
            conn.execute(
                "INSERT INTO world_events (agent_key, kind, text) VALUES (?,?,?)",
                (agent_key, "system",
                 f"💰 Money mission approved: {mission['title']}"
                 + (f" (~${usd:,.0f})" if usd else "")
                 + f" — assigned to {who}."))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("money: world integration failed for mission %s: %s", mid, e)
    return {"mission": mission}


@router.post("/api/money/missions/{mid}/reject")
def reject_mission(mid: int):
    return {"mission": _set_status(mid, "rejected")}


@router.post("/api/money/missions/{mid}/done")
def complete_mission(mid: int, body: dict = Body(default={})):
    return {"mission": _set_status(mid, "done", result=str(body.get("result") or ""))}


# ── stats ─────────────────────────────────────────────────────────────────────
@router.get("/api/money/stats")
def money_stats():
    conn = get_conn()
    try:
        missions = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM money_missions GROUP BY status")}
        signals = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM money_signals GROUP BY status")}
        val = {r["status"]: r["s"] for r in conn.execute(
            "SELECT status, COALESCE(SUM(est_value_cents),0) AS s FROM money_missions "
            "WHERE status IN ('proposed','approved') GROUP BY status")}
        proposed_cents = val.get("proposed", 0)
        approved_cents = val.get("approved", 0)
        return {"missions": missions, "signals": signals,
                "proposed_value_cents": proposed_cents,
                "approved_value_cents": approved_cents,
                "pipeline_value_cents": proposed_cents + approved_cents}
    finally:
        conn.close()


# ── autonomous cadence (the app's own cron; mirrors world_auto's thread) ─────
# Review new demand signals at most every 6h; hunt carpentry leads once a day
# after 09:00 local. Disable with setting money_auto=off.
_auto = {"thread": None, "last_review": 0.0, "last_hunt_day": ""}


def _auto_loop():
    time.sleep(60)   # let the app settle
    while True:
        try:
            if (get_setting("money_auto", "on") or "on").lower() != "off":
                now = time.time()
                if now - _auto["last_review"] >= 6 * 3600:
                    conn = get_conn()
                    n = conn.execute(
                        "SELECT COUNT(*) AS n FROM money_signals WHERE status='new'"
                    ).fetchone()["n"]
                    conn.close()
                    if n:
                        try:
                            run_review()
                            _auto["last_review"] = now
                            logger.info("money auto: reviewed %d signals", n)
                        except HTTPException:
                            pass
                lt = time.localtime()
                day = time.strftime("%Y-%m-%d", lt)
                if lt.tm_hour >= 9 and day != _auto["last_hunt_day"]:
                    _auto["last_hunt_day"] = day
                    try:
                        r = hunt_leads()
                        logger.info("money auto: lead hunt dispatched (%s)", r)
                    except HTTPException as e:
                        logger.info("money auto: lead hunt skipped (%s)", e.detail)
        except Exception as e:
            logger.warning("money auto loop: %s", e)
        time.sleep(3600)


def start_auto():
    if _auto["thread"]:
        return
    t = threading.Thread(target=_auto_loop, daemon=True, name="money-auto")
    _auto["thread"] = t
    t.start()
    logger.info("money_auto started")
