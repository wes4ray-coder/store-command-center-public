"""God Console — The Republic (survival strategy engine: state/convene/override)
and The Bible (BOOK.md is the Word; agents grow the teachings)."""
import json, logging, threading, os
from fastapi import HTTPException, Body

from deps import get_conn
import world_strategy
import world_bible
from ._base import router


# ── The Republic (survival strategy engine) ──────────────────────────────────
@router.get("/api/world/republic/state")
def republic_state():
    return world_strategy.state()


@router.post("/api/world/republic/convene")
def republic_convene():
    """Convene the assembly: assess → propose → vote → adopt → act → measure."""
    conn = get_conn()
    try:
        return world_strategy.run_cycle(conn)
    finally:
        conn.close()


# ── The Bible (BOOK.md is the Word; agents grow the teachings) ───────────────
@router.get("/api/world/bible/word")
def bible_word():
    return world_bible.word()


@router.get("/api/world/bible/teachings")
def bible_teachings(limit: int = 100):
    return {"teachings": world_bible.teachings(limit)}


@router.post("/api/world/republic/strategy/{sid}/override")
def republic_override(sid: int, body: dict = Body(...)):
    """God overrides the vote: 'adopt' (force + act) or 'reject' a strategy."""
    decision = body.get("decision")
    if decision not in ("adopt", "reject"):
        raise HTTPException(400, "decision must be 'adopt' or 'reject'")
    conn = get_conn()
    try:
        res = world_strategy.override(conn, sid, decision)
        if res is None:
            raise HTTPException(404, "strategy not found")
        return res
    finally:
        conn.close()
