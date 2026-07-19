"""AI Assistant — "skills" (reusable prompt recipes): list / save / delete / run.
Running a skill submits its prompt as a normal user message through the agent loop.
"""
import time

from fastapi import HTTPException

from deps import *

from ._base import router, _ensure
from .chat import agent_chat, AgentChatRequest


# ─── Skills (reusable prompt recipes) ────────────────────────────────────────
class SkillRequest(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = ""
    prompt: str


@router.get("/api/agent/skills")
def agent_skills():
    _ensure()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM assistant_skills ORDER BY id ASC").fetchall()
    conn.close()
    return {"ok": True, "skills": [dict(r) for r in rows]}


@router.post("/api/agent/skills")
def agent_skill_save(req: SkillRequest):
    _ensure()
    if not (req.name or "").strip() or not (req.prompt or "").strip():
        raise HTTPException(400, "name and prompt required")
    conn = get_conn()
    if req.id:
        conn.execute("UPDATE assistant_skills SET name=?, description=?, prompt=? WHERE id=?",
                     (req.name.strip(), req.description or "", req.prompt, req.id))
        sid = req.id
    else:
        cur = conn.execute("INSERT INTO assistant_skills (name, description, prompt, builtin, created) "
                           "VALUES (?,?,?,0,?)", (req.name.strip(), req.description or "",
                                                  req.prompt, time.time()))
        sid = cur.lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "id": sid}


@router.delete("/api/agent/skills/{sid}")
def agent_skill_delete(sid: int):
    _ensure()
    conn = get_conn()
    conn.execute("DELETE FROM assistant_skills WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return {"ok": True}


class SkillRunRequest(BaseModel):
    conversation_id: Optional[int] = None
    extra: Optional[str] = ""     # appended to the skill prompt (topic, question, ...)


@router.post("/api/agent/skills/{sid}/run")
def agent_skill_run(sid: int, req: SkillRunRequest):
    """Run a saved skill as a user message through the normal agent loop."""
    _ensure()
    conn = get_conn()
    row = conn.execute("SELECT * FROM assistant_skills WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "no such skill")
    message = (row["prompt"] + " " + (req.extra or "")).strip()
    return agent_chat(AgentChatRequest(message=message, conversation_id=req.conversation_id))
