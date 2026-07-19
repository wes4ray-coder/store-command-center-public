"""Shared base for the money package: the single router, the idempotent schema
(run ONCE at import), the mission enums, and the defensive LLM-JSON parser used by
both proposal generators.

Split out of the former monolithic ``routers/money.py``. The shared ``APIRouter``,
the one-time ``_ensure_schema()`` side effect, and the helpers used by two or more
submodules live here so there are no import cycles between the submodules."""
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
