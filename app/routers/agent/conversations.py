"""AI Assistant — persistent conversation list / detail / delete endpoints."""
import json

from fastapi import HTTPException

from deps import *

from ._base import router, _ensure, _run_state, _RUNS, _RUNS_LOCK


# ─── Conversations ───────────────────────────────────────────────────────────
@router.get("/api/agent/conversations")
def agent_conversations():
    _ensure()
    conn = get_conn()
    rows = conn.execute(
        "SELECT c.id, c.title, c.created, c.updated, "
        "(SELECT COUNT(*) FROM assistant_messages m WHERE m.conv_id=c.id) AS messages "
        "FROM assistant_conversations c ORDER BY c.updated DESC LIMIT 50").fetchall()
    conn.close()
    return {"ok": True, "conversations": [dict(r) for r in rows]}


@router.get("/api/agent/conversations/{conv_id}")
def agent_conversation(conv_id: int):
    _ensure()
    conn = get_conn()
    conv = conn.execute("SELECT * FROM assistant_conversations WHERE id=?", (conv_id,)).fetchone()
    if not conv:
        conn.close()
        raise HTTPException(404, "no such conversation")
    rows = conn.execute("SELECT * FROM assistant_messages WHERE conv_id=? ORDER BY id ASC",
                        (conv_id,)).fetchall()
    conn.close()
    return {"ok": True, "conversation": dict(conv), "status": _run_state(conv_id)["status"],
            "messages": [{"id": r["id"], "ts": r["ts"], "role": r["role"], "kind": r["kind"],
                          "content": r["content"], "meta": json.loads(r["meta"] or "{}")}
                         for r in rows]}


@router.delete("/api/agent/conversations/{conv_id}")
def agent_conversation_delete(conv_id: int):
    _ensure()
    conn = get_conn()
    conn.execute("DELETE FROM assistant_messages WHERE conv_id=?", (conv_id,))
    conn.execute("DELETE FROM assistant_approvals WHERE conv_id=?", (conv_id,))
    conn.execute("DELETE FROM assistant_conversations WHERE id=?", (conv_id,))
    conn.commit()
    conn.close()
    with _RUNS_LOCK:
        _RUNS.pop(conv_id, None)
    return {"ok": True}
