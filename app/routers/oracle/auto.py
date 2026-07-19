"""Autonomous cadence: a background loop that resolves due predictions and kicks off
one fresh tournament round a day (disabled by the oracle_auto=off setting)."""
import threading
import time

from deps import *          # get_setting, logger

from ._base import _meta_get, _meta_set
from .scoring import _resolve_due
from .forecast import _run_round, _round


# ── autonomous cadence: resolve due predictions + optionally run a daily round ──
_auto = {"thread": None}


def _auto_loop():
    time.sleep(90)
    while True:
        try:
            if (get_setting("oracle_auto", "on") or "on").lower() != "off":
                n = _resolve_due()
                if n:
                    logger.info("oracle auto: resolved %d prediction(s)", n)
                # a fresh round once a day if the last one is old and none is running
                last = _meta_get("last_round_day", "")
                today = time.strftime("%Y-%m-%d")
                if today != last and not _round["running"]:
                    _meta_set("last_round_day", today)
                    threading.Thread(target=_run_round, args=(3,), daemon=True,
                                     name="oracle-round-auto").start()
        except Exception as e:
            logger.warning("oracle auto loop: %s", e)
        time.sleep(3600)


def start_auto():
    if _auto["thread"]:
        return
    t = threading.Thread(target=_auto_loop, daemon=True, name="oracle-auto")
    _auto["thread"] = t
    t.start()
    logger.info("oracle_auto started")
