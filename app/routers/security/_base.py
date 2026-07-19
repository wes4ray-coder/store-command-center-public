"""Shared router + cross-engine helpers for the security package.

Split out of the former monolithic ``routers/security.py``. The shared
``APIRouter`` and the helpers used by two or more engines live here so there are
no import cycles between the engine modules. There are no import-time side
effects beyond constructing the router (the original module had none either).
"""
import hashlib
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from deps import *

router = APIRouter()


def _fkey(issue: str) -> str:
    return hashlib.sha256(issue.strip().lower().encode()).hexdigest()[:16]


def _score():
    """0-100 security score from open (pending/approved) findings, weighted by priority."""
    conn = get_conn()
    rows = conn.execute("SELECT priority FROM security_findings WHERE status IN ('pending','approved')").fetchall()
    conn.close()
    penalty = 0
    for r in rows:
        p = (r["priority"] or "").lower()
        penalty += 20 if "high" in p else 10 if "med" in p else 5
    return max(0, 100 - penalty)
