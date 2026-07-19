"""Agent Watcher routes — the background agent-health watcher's incidents,
manual tick, and toggles. Everything here is also an MCP tool (via the /api/mcp
mount), so OpenClaw agents can ask "what's broken and how do I fix it" directly.
"""
from fastapi import APIRouter, HTTPException

from deps import get_conn, get_setting

import watcher

router = APIRouter()

# Only these keys are writable through the settings endpoint.
_KEYS = {
    "agent_watcher_enabled":    "1",   # master switch
    "agent_watcher_interval":   "5",   # minutes between ticks
    "agent_watcher_stall_min":  "20",  # no-progress minutes → stalled
    "agent_watcher_media_min":  "90",  # media job stuck threshold
    "agent_watcher_llm":        "1",   # LLM doctor enrichment
    "agent_watcher_notify":     "1",   # God-Console notes
    "agent_watcher_autoresume": "0",   # auto re-run resumable paused jobs
}


@router.get("/api/watcher")
def watcher_status():
    """Watcher state: settings, open-incident count, and the recent incidents.
    An incident = a failed/paused/stalled agent job plus its diagnosis
    (what happened, likely cause, how to fix, whether a re-run should work)."""
    conn = get_conn()
    open_n = conn.execute("SELECT COUNT(*) FROM watcher_incidents WHERE status='open'").fetchone()[0]
    conn.close()
    return {
        "settings": {k: get_setting(k, d) for k, d in _KEYS.items()},
        "open": open_n,
        "incidents": watcher.incidents(limit=30),
    }


@router.get("/api/watcher/incidents")
def watcher_incidents(status: str = None, limit: int = 50):
    """List incidents; status=open|resolved filters. Newest first."""
    return {"incidents": watcher.incidents(status=status, limit=min(200, max(1, limit)))}


@router.post("/api/watcher/tick")
def watcher_tick():
    """Run one watcher pass now (the scheduler also runs one every
    agent_watcher_interval minutes while enabled)."""
    return watcher.watch_tick()


@router.post("/api/watcher/incidents/{iid}/resolve")
def watcher_resolve(iid: int):
    """Mark an incident handled."""
    if not watcher.resolve_incident(iid):
        raise HTTPException(404, "no such open incident")
    return {"ok": True}


@router.post("/api/watcher/incidents/{iid}/rerun")
def watcher_rerun(iid: int):
    """Re-run the swarm job behind an incident. The watcher's diagnosis is already
    on the job's timeline, so the agents restart knowing what broke and how to fix it."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM watcher_incidents WHERE id=?", (iid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "no such incident")
    if row["source"] != "swarm":
        raise HTTPException(400, f"incident source '{row['source']}' is not re-runnable here")
    import swarm
    if not swarm.start_job(row["ref_id"]):
        raise HTTPException(409, "job is already running")
    watcher.resolve_incident(iid, action="rerun")
    return {"ok": True, "job_id": row["ref_id"]}


@router.post("/api/watcher/settings")
def watcher_settings(body: dict):
    """Update watcher toggles/intervals. Body: {key: value} pairs limited to the
    agent_watcher_* keys (everything the watcher does can be switched off)."""
    body = body or {}
    bad = [k for k in body if k not in _KEYS]
    if bad:
        raise HTTPException(400, f"unknown keys: {', '.join(bad)}")
    conn = get_conn()
    for k, v in body.items():
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit(); conn.close()
    return {"ok": True, "settings": {k: get_setting(k, d) for k, d in _KEYS.items()}}
