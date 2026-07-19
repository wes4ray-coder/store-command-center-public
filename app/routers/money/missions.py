"""money — the missions queue (list/create/approve/reject/done, with best-effort
Company-world integration on approve) and the pipeline stats."""
import json as _json
import hmac as _hmac
import random as _random
import requests
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

from deps import *
from services import *
from ._base import router, MISSION_KINDS


def _mission_row(r) -> dict:
    return dict(r)


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
