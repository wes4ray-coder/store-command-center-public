"""Shared base for the resell_browser package: the single router + the cross-domain
automation helpers used by two or more submodules.

Split out of the former monolithic ``routers/resell_browser.py``. The shared
``APIRouter`` and the helpers used across domains (``_alog`` event logging,
``_login_guard`` login-wall detection, the ``_PLATFORM_CREATE`` map) live here so
there are no import cycles between the submodules. There are no import-time side
effects beyond constructing the router (the original module had none either)."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from deps import *
from services import *

router = APIRouter()


def _alog(action: str, target, status: str, detail: str = ""):
    """Record an automation event (persisted) so the UI is never a black box.
    Keeps only the most recent 100 rows."""
    try:
        conn = get_conn()
        conn.execute("INSERT INTO automation_log (action, target, status, detail) VALUES (?,?,?,?)",
                     (action, str(target), status, (detail or "")[:500]))
        conn.execute("DELETE FROM automation_log WHERE id NOT IN "
                     "(SELECT id FROM automation_log ORDER BY id DESC LIMIT 100)")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _login_guard(tab, platform: str, action: str):
    """If the current page is a login wall, log it and return a clear 'needs_login'
    response dict; otherwise return None so the caller proceeds."""
    try:
        sig = tab.page_signal()
    except Exception:
        sig = {}
    if sig.get("needs_login"):
        _alog(action, platform, "needs_login", f"Login wall at {sig.get('url','')}")
        return {
            "ok": False, "needs_login": True, "platform": platform,
            "current_url": sig.get("url", ""),
            "note": (f"⚠️ Not logged into {platform.title()} in the Store browser. "
                     "Click “Launch Browser”, sign in once (the login is remembered), then retry."),
        }
    return None


_PLATFORM_CREATE = {
    "facebook":   "https://www.facebook.com/marketplace/create/item",
    "offerup":    "https://offerup.com/post/",
    "craigslist": "https://post.craigslist.org/",
    "mercari":    "https://www.mercari.com/sell/",
}
