"""AI Assistant — the real agentic loop and its chat / events / approve / stop
endpoints. Runs execute inside the orchestrator LLM queue (one job per loop
segment); the frontend polls /api/agent/events for live updates.
"""
import json
import time

import httpx
from fastapi import HTTPException

from deps import *
from services import *
import assistant_tools
from llm_client import _llm_headers

from ._base import (router, _ensure, _add_msg, _new_conversation,
                    _RUNS, _RUNS_LOCK, _set_run, _run_state)


# ─── LM Studio call with full message history ────────────────────────────────
def _chat_raw(messages: list, max_tokens: int = 1400) -> str:
    """Multi-message LM Studio call (runs inside the orchestrator worker, which
    picked/loaded the model — same borrow semantics as _call_lmstudio)."""
    from deps import ENHANCE_MODEL, LMSTUDIO_URL
    model = getattr(orch, "_current_llm_model", None) or ENHANCE_MODEL
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": 0.4, "reasoning_effort": "none"}
    r = httpx.post(f"{LMSTUDIO_URL}/chat/completions", json=body,
                   headers=_llm_headers(), timeout=600)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    return ((msg.get("content") or "").strip()
            or (msg.get("reasoning_content") or "").strip())


def _submit_run(conv_id: int):
    model = get_setting("assistant_model", "") or None
    _set_run(conv_id, status="running", stop=False)
    tid = orch.submit_llm(lambda: _run_loop(conv_id), desc="Assistant agent loop",
                          priority=0, task="assistant", model=model)
    _set_run(conv_id, tid=tid)


# ─── The agentic loop ────────────────────────────────────────────────────────
def _build_llm_messages(conv_id: int) -> list:
    system = (get_prompt("assistant")
              + "\n\nAVAILABLE TOOLS:\n" + assistant_tools.prompt_tool_docs())
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM (SELECT * FROM assistant_messages WHERE conv_id=? ORDER BY id DESC LIMIT 60) "
        "ORDER BY id ASC", (conv_id,)).fetchall()
    conn.close()
    msgs = [{"role": "system", "content": system}]
    for r in rows:
        kind, content = r["kind"], r["content"]
        if kind == "user":
            msgs.append({"role": "user", "content": content})
        elif kind == "assistant":
            msgs.append({"role": "assistant", "content": content})
        elif kind in ("tool_call", "approval_request"):
            msgs.append({"role": "assistant", "content": content if kind == "tool_call"
                         else f'(proposed action awaiting user approval: {content})'})
        elif kind == "tool_result":
            msgs.append({"role": "user", "content": "TOOL_RESULT: " + content[:3800]})
        elif kind == "tool_error":
            msgs.append({"role": "user", "content": "TOOL_ERROR: " + content[:1000]})
        elif kind == "approval_result":
            msgs.append({"role": "user", "content": content})
        elif kind == "error":
            msgs.append({"role": "user", "content": "SYSTEM: " + content[:500]})
    return msgs


def _exec_and_record(conv_id: int, call: dict, res: dict) -> dict:
    _add_msg(conv_id, "tool", "tool_call",
             json.dumps({"tool": call["tool"], "args": call["args"]}, ensure_ascii=False),
             meta={"tool": call["tool"], "method": res.get("method"), "path": res.get("path"),
                   "category": res.get("category")})
    try:
        out = assistant_tools.execute_resolved(res)
    except Exception as e:  # noqa: BLE001 — surfaced to the model + UI
        out = {"status": 0, "result": f"tool execution failed: {e}"}
    _add_msg(conv_id, "tool", "tool_result", assistant_tools.truncate_for_llm(out, 20000),
             meta={"tool": call["tool"], "status": out.get("status")})
    return out


def _run_loop(conv_id: int):
    """One loop segment: think → tool → observe → ... until final answer, approval
    pause, stop, or the max-step cap. Runs inside an orchestrator LLM worker."""
    _ensure()
    _set_run(conv_id, status="running")
    try:
        max_iters = int(get_setting("assistant_max_iters", 8) or 8)
        for _step in range(max_iters):
            if _run_state(conv_id).get("stop"):
                _add_msg(conv_id, "system", "status", "Stopped by user.")
                break
            out = _chat_raw(_build_llm_messages(conv_id))
            call = assistant_tools.parse_tool_call(out)
            if not call:
                _add_msg(conv_id, "assistant", "assistant", out or "(the model returned an empty reply)")
                break
            try:
                res = assistant_tools.resolve_call(call["tool"], call["args"])
            except ValueError as e:
                _add_msg(conv_id, "tool", "tool_error", str(e),
                         meta={"tool": call.get("tool"), "args": call.get("args")})
                continue
            if not assistant_tools.auto_approved(res["category"]):
                conn = get_conn()
                cur = conn.execute(
                    "INSERT INTO assistant_approvals (conv_id, tool, args, category, status, created) "
                    "VALUES (?,?,?,?, 'pending', ?)",
                    (conv_id, call["tool"], json.dumps(call["args"]), res["category"], time.time()))
                conn.commit()
                ap_id = cur.lastrowid
                conn.close()
                _add_msg(conv_id, "tool", "approval_request",
                         f"{call['tool']} → {res.get('method', '')} {res.get('path', '')}",
                         meta={"tool": call["tool"], "args": call["args"], "category": res["category"],
                               "approval_id": ap_id, "method": res.get("method"), "path": res.get("path")})
                _set_run(conv_id, status="awaiting_approval")
                return
            _exec_and_record(conv_id, call, res)
        else:
            _add_msg(conv_id, "assistant", "assistant",
                     "(paused: hit the max tool-step limit — say 'continue' to keep going)")
    except Exception as e:  # noqa: BLE001 — never leave the run stuck
        _add_msg(conv_id, "system", "error", f"Assistant error: {e}")
    _set_run(conv_id, status="idle")


# ─── Chat endpoints ──────────────────────────────────────────────────────────
class AgentChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None
    session_key: Optional[str] = "store-dashboard"   # legacy compat


@router.post("/api/agent/chat")
def agent_chat(req: AgentChatRequest):
    """Start (or continue) an agentic run. Returns immediately; poll /api/agent/events."""
    _ensure()
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(400, "message required")
    conv_id = req.conversation_id
    if conv_id:
        conn = get_conn()
        row = conn.execute("SELECT id FROM assistant_conversations WHERE id=?", (conv_id,)).fetchone()
        conn.close()
        if not row:
            conv_id = None
    if not conv_id:
        conv_id = _new_conversation(msg)
    if _run_state(conv_id)["status"] in ("running", "awaiting_approval"):
        raise HTTPException(409, "a run is already active in this conversation — stop it first")
    _add_msg(conv_id, "user", "user", msg)
    _submit_run(conv_id)
    return {"ok": True, "conversation_id": conv_id, "status": "running"}


@router.get("/api/agent/events")
def agent_events(conversation_id: int, after: int = 0):
    """Poll for new messages/events + the run status (running / awaiting_approval / idle)."""
    _ensure()
    st = _run_state(conversation_id)
    status = st["status"]
    # Reconcile: if the queued orchestrator task died/cancelled, don't stay 'running' forever.
    if status == "running" and st.get("tid"):
        t = orch.poll(st["tid"])
        if t["status"] in ("error", "cancelled", "not_found"):
            if t["status"] == "error":
                _add_msg(conversation_id, "system", "error", f"Run failed: {t.get('error')}")
            _set_run(conversation_id, status="idle")
            status = "idle"
    conn = get_conn()
    rows = conn.execute("SELECT * FROM assistant_messages WHERE conv_id=? AND id>? ORDER BY id ASC",
                        (conversation_id, after)).fetchall()
    conn.close()
    msgs = [{"id": r["id"], "ts": r["ts"], "role": r["role"], "kind": r["kind"],
             "content": r["content"], "meta": json.loads(r["meta"] or "{}")} for r in rows]
    return {"ok": True, "status": status, "messages": msgs}


class ApproveRequest(BaseModel):
    approval_id: int
    approve: bool
    remember: bool = False    # flip the category's auto-approve toggle on approve


@router.post("/api/agent/approve")
def agent_approve(req: ApproveRequest):
    """Answer a pending approval; executes (or records denial) and resumes the loop."""
    _ensure()
    conn = get_conn()
    row = conn.execute("SELECT * FROM assistant_approvals WHERE id=?", (req.approval_id,)).fetchone()
    if not row or row["status"] != "pending":
        conn.close()
        raise HTTPException(404, "no such pending approval")
    conn.execute("UPDATE assistant_approvals SET status=? WHERE id=?",
                 ("approved" if req.approve else "denied", req.approval_id))
    conn.commit()
    conn.close()
    conv_id = row["conv_id"]
    call = {"tool": row["tool"], "args": json.loads(row["args"] or "{}")}
    if req.approve:
        if req.remember:
            c = get_conn()
            c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                      (f"assistant_auto_{row['category']}", "1"))
            c.commit()
            c.close()
        _add_msg(conv_id, "user", "approval_result",
                 f"APPROVAL_RESULT: user APPROVED {row['tool']} ({row['category']}).",
                 meta={"approval_id": req.approval_id, "approved": True})
        try:
            res = assistant_tools.resolve_call(call["tool"], call["args"])
            _exec_and_record(conv_id, call, res)
        except ValueError as e:
            _add_msg(conv_id, "tool", "tool_error", str(e), meta={"tool": call["tool"]})
    else:
        _add_msg(conv_id, "user", "approval_result",
                 f"APPROVAL_RESULT: user DENIED {row['tool']} ({row['category']}). "
                 "Do not retry it; adapt or finish.",
                 meta={"approval_id": req.approval_id, "approved": False})
    _submit_run(conv_id)
    return {"ok": True, "resumed": True}


class StopRequest(BaseModel):
    conversation_id: int


@router.post("/api/agent/stop")
def agent_stop(req: StopRequest):
    """Stop the active run (takes effect between loop steps; cancels a queued task)."""
    _ensure()
    st = _run_state(req.conversation_id)
    _set_run(req.conversation_id, stop=True)
    if st.get("tid"):
        try:
            orch.cancel(st["tid"])
        except Exception:
            pass
    if st["status"] == "awaiting_approval":
        conn = get_conn()
        conn.execute("UPDATE assistant_approvals SET status='cancelled' "
                     "WHERE conv_id=? AND status='pending'", (req.conversation_id,))
        conn.commit()
        conn.close()
        _add_msg(req.conversation_id, "system", "status", "Stopped by user.")
        _set_run(req.conversation_id, status="idle")
    return {"ok": True}
