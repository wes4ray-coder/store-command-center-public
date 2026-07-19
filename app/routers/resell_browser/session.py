"""resell_browser — Domain A: browser session lifecycle (launch/quit/status/activity/
screenshot) and form-field inspection."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from deps import *
from services import *
from ._base import router, _alog, _login_guard, _PLATFORM_CREATE
import browser as _browser


_PLATFORM_LOGIN = {
    "facebook":   "https://www.facebook.com/marketplace/",
    "offerup":    "https://offerup.com/login/",
    "craigslist": "https://accounts.craigslist.org/login",
    "mercari":    "https://www.mercari.com/login/",
}


@router.get("/api/resell/browser/status")
def resell_browser_status():
    """Live browser state + login check on the current page, so the UI can show
    'ready / needs login / not running' instead of guessing."""
    st = _browser.browser.status()
    if st.get("running") and _browser.browser._tab:
        try:
            sig = _browser.browser._tab.page_signal()
            st["needs_login"] = bool(sig.get("needs_login"))
            st["page_title"] = sig.get("title", "")
        except Exception:
            pass
    return st


@router.get("/api/resell/browser/activity")
def resell_browser_activity(limit: int = 25):
    """Recent automation events (persisted) — the status report that keeps the
    agent from being a black box: what it did, whether it worked, and why not."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT action, target, status, detail, created_at FROM automation_log "
        "ORDER BY id DESC LIMIT ?", (max(1, min(100, limit)),)).fetchall()
    conn.close()
    events = [dict(r) for r in rows]
    last_fail = next((e for e in events if e["status"] in ("failed", "needs_login")), None)
    return {"events": events, "last_problem": last_fail}


@router.post("/api/resell/browser/launch")
def resell_browser_launch(body: dict = None):
    """Open the persistent Store browser (headed) — log into marketplaces here once."""
    platform = (body or {}).get("platform", "")
    url = _PLATFORM_LOGIN.get(platform, "https://www.google.com")
    try:
        _browser.browser.open(url, headless=False)
    except Exception as e:
        _alog("launch", platform or "browser", "failed", str(e))
        raise HTTPException(502, f"Could not launch browser: {e}")
    _alog("launch", platform or "browser", "done", f"Opened {url}")
    return {"ok": True, **_browser.browser.status()}


@router.post("/api/resell/browser/quit")
def resell_browser_quit():
    _browser.browser.quit()
    _alog("quit", "browser", "done", "Browser closed")
    return {"ok": True}


@router.get("/api/resell/browser/screenshot")
def resell_browser_screenshot():
    try:
        return {"png_b64": _browser.browser.screenshot_b64()}
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── Auto-fill: discover fields + fill per platform ──────────────────────────
@router.get("/api/resell/browser/inspect")
def resell_browser_inspect(platform: str = "facebook", goto: bool = False):
    """Dump the current tab's form fields (to find selectors). Pass goto=true to also
    LAUNCH the browser and navigate to the platform's create page first. goto defaults to
    FALSE so a bare GET never opens a real Chrome at a live marketplace (that side effect
    made a Facebook Marketplace tab pop up on every smoke-test run)."""
    url = _PLATFORM_CREATE.get(platform)
    if not url:
        raise HTTPException(400, "Unknown platform")
    try:
        tab = _browser.browser.open(url, headless=False) if goto else _browser.browser._tab
        if goto:
            time.sleep(5)
        return {"url": tab.url(), "fields": tab.dump_fields()}
    except Exception as e:
        raise HTTPException(502, f"Browser error: {e}")
