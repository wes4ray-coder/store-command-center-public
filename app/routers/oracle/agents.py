"""Analyst roster + leaderboard + read views: per-analyst stats, add/rename/retire
analysts, toggle them in/out of the tournament, and browse predictions + memory."""
import json as _json
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

from deps import *          # get_conn
from services import *      # (kept consistent with sibling routers)

from ._base import router, _assets


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
    # per-rung accuracy on RESOLVED calls (the ladder view: 1d/3d/5d/1w/2w/…)
    rungs = [{"h": rr["h"], "resolved": rr["n"], "correct": rr["c"] or 0,
              "accuracy": round(100 * (rr["c"] or 0) / rr["n"], 1) if rr["n"] else None}
             for rr in conn.execute(
                 "SELECT horizon_days AS h, COUNT(*) AS n,"
                 " SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS c "
                 "FROM oracle_predictions WHERE agent_id=? AND status='resolved' "
                 "GROUP BY horizon_days ORDER BY horizon_days", (agent_id,)).fetchall()]
    conn.close()
    r = dict(row)
    resolved = r["resolved"] or 0
    return {"score": round(r["score"] or 0, 1), "resolved": resolved, "open": r["open"] or 0,
            "correct": r["correct"] or 0,
            "accuracy": round(100 * (r["correct"] or 0) / resolved, 1) if resolved else None,
            "avg_horizon": round(r["avg_h"] or 0, 1), "rungs": rungs}


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


class AgentIn(BaseModel):
    name: str = ""
    model: str = ""


@router.post("/api/oracle/agents")
def add_agent(body: AgentIn):
    """Add an analyst: any LM Studio model id can compete. Starts active."""
    name, model = body.name.strip(), body.model.strip()
    if not name or not model:
        raise HTTPException(400, "name and model are both required")
    conn = get_conn()
    if conn.execute("SELECT 1 FROM oracle_agents WHERE name=?", (name,)).fetchone():
        conn.close(); raise HTTPException(400, f"An analyst named '{name}' already exists")
    aid = conn.execute("INSERT INTO oracle_agents (name,model,active) VALUES (?,?,1)",
                       (name, model)).lastrowid
    conn.commit(); conn.close()
    return {"ok": True, "id": aid}


@router.post("/api/oracle/agents/{aid}")
def update_agent(aid: int, body: AgentIn):
    """Rename an analyst and/or point it at a different model (empty field = keep)."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM oracle_agents WHERE id=?", (aid,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "No such analyst")
    name = body.name.strip() or row["name"]
    model = body.model.strip() or row["model"]
    conn.execute("UPDATE oracle_agents SET name=?, model=? WHERE id=?", (name, model, aid))
    conn.commit(); conn.close()
    return {"ok": True}


@router.delete("/api/oracle/agents/{aid}")
def delete_agent(aid: int):
    """Retire an analyst from the tournament. Its past predictions/lessons stay in
    the DB (history is honest) but it stops appearing anywhere and never runs again."""
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM oracle_agents WHERE id=?", (aid,)).fetchone():
        conn.close(); raise HTTPException(404, "No such analyst")
    conn.execute("DELETE FROM oracle_agents WHERE id=?", (aid,))
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
