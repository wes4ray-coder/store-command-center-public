"""money — autonomous cadence (the app's own cron; mirrors world_auto's thread).

Review new demand signals at most every 6h; hunt carpentry leads once a day after
09:00 local. Disable with setting money_auto=off."""
import json as _json
import hmac as _hmac
import random as _random
import requests
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

from deps import *
from services import *
from .intel import run_review, hunt_leads


_auto = {"thread": None, "last_review": 0.0, "last_hunt_day": ""}


def _auto_loop():
    time.sleep(60)   # let the app settle
    while True:
        try:
            if (get_setting("money_auto", "on") or "on").lower() != "off":
                now = time.time()
                if now - _auto["last_review"] >= 6 * 3600:
                    conn = get_conn()
                    n = conn.execute(
                        "SELECT COUNT(*) AS n FROM money_signals WHERE status='new'"
                    ).fetchone()["n"]
                    conn.close()
                    if n:
                        try:
                            run_review()
                            _auto["last_review"] = now
                            logger.info("money auto: reviewed %d signals", n)
                        except HTTPException:
                            pass
                lt = time.localtime()
                day = time.strftime("%Y-%m-%d", lt)
                if lt.tm_hour >= 9 and day != _auto["last_hunt_day"]:
                    _auto["last_hunt_day"] = day
                    try:
                        r = hunt_leads()
                        logger.info("money auto: lead hunt dispatched (%s)", r)
                    except HTTPException as e:
                        logger.info("money auto: lead hunt skipped (%s)", e.detail)
        except Exception as e:
            logger.warning("money auto loop: %s", e)
        time.sleep(3600)


def start_auto():
    if _auto["thread"]:
        return
    t = threading.Thread(target=_auto_loop, daemon=True, name="money-auto")
    _auto["thread"] = t
    t.start()
    logger.info("money_auto started")
