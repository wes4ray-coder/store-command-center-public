"""money — demand-signal ingest (self-guarded X-Money-Token) + listing."""
import json as _json
import hmac as _hmac
import random as _random
import requests
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

from deps import *
from services import *
from ._base import router


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
