"""Autonomous cadence + oracle settings.

The background loop ticks every 15 MINUTES (it used to be hourly — too slow now
that 1-day ladder rungs exist): each tick it resolves any due predictions, and
once a day it kicks off a fresh tournament round. Gates (each with a user
toggle, per the house rule): `oracle_auto` (master), `oracle_auto_rounds`
(the daily round). The /api/oracle/settings endpoints back BOTH settings
surfaces — the Oracle tab and the God panel."""
import threading
import time

from fastapi import HTTPException

from deps import *          # get_setting, get_conn, logger

from ._base import (router, _meta_get, _meta_set,
                    ORACLE_SETTINGS_DEFAULTS, oracle_setting, ladder_days)
from .scoring import _resolve_due
from .forecast import _run_round, _round

TICK_SECONDS = 900          # 15 min — resolves 1-day rungs promptly

# ── autonomous cadence: resolve due predictions + optionally run a daily round ──
_auto = {"thread": None}


def _auto_loop():
    time.sleep(90)
    while True:
        try:
            if (oracle_setting("oracle_auto") or "on").lower() != "off":
                n = _resolve_due()
                if n:
                    logger.info("oracle auto: resolved %d prediction(s)", n)
                # a fresh round once a day if the last one is old and none is running
                last = _meta_get("last_round_day", "")
                today = time.strftime("%Y-%m-%d")
                if (today != last and not _round["running"]
                        and oracle_setting("oracle_auto_rounds") in ("1", "true", "on")):
                    _meta_set("last_round_day", today)
                    threading.Thread(target=_run_round, args=(3,), daemon=True,
                                     name="oracle-round-auto").start()
        except Exception as e:
            logger.warning("oracle auto loop: %s", e)
        time.sleep(TICK_SECONDS)


def start_auto():
    if _auto["thread"]:
        return
    t = threading.Thread(target=_auto_loop, daemon=True, name="oracle-auto")
    _auto["thread"] = t
    t.start()
    logger.info("oracle_auto started")


# ── settings surface (Oracle tab + God panel both read/write these) ──────────
@router.get("/api/oracle/settings")
def get_oracle_settings():
    return {
        "settings": {k: oracle_setting(k) for k in ORACLE_SETTINGS_DEFAULTS},
        "defaults": dict(ORACLE_SETTINGS_DEFAULTS),
        "ladder_days": ladder_days(),      # the effective rungs after toggles
    }


@router.post("/api/oracle/settings")
def save_oracle_settings(body: dict):
    updates = (body or {}).get("settings", body or {})
    if not isinstance(updates, dict):
        raise HTTPException(400, "settings must be an object")
    clean = {}
    for k, v in updates.items():
        if k not in ORACLE_SETTINGS_DEFAULTS:
            continue
        v = str(v).strip()
        if k == "oracle_ladder":
            days = [t.strip() for t in v.split(",") if t.strip()]
            if not days or len(days) > 8 or not all(t.isdigit() and 1 <= int(t) <= 90 for t in days):
                raise HTTPException(400, "oracle_ladder must be 1–8 comma-separated day counts, each 1–90")
            v = ",".join(str(d) for d in sorted({int(t) for t in days}))
        elif k == "oracle_auto":
            v = "on" if v.lower() in ("1", "true", "on") else "off"
        else:
            v = "1" if v.lower() in ("1", "true", "on") else "0"
        clean[k] = v
    conn = get_conn()
    for k, v in clean.items():
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()
    return get_oracle_settings()
