"""resell_browser — Domain B: opening a platform's create page, attaching photos, and
auto-filling the listing form (per-platform label + plain-form CSS selectors)."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from deps import *
from services import *
from ._base import router, _alog, _login_guard, _PLATFORM_CREATE
import browser as _browser


def _listing_photo_paths(lid: int, row: dict) -> list:
    conn = get_conn()
    photos = conn.execute("SELECT image_path FROM resell_listing_images WHERE listing_id=? ORDER BY is_primary DESC, id", (lid,)).fetchall()
    conn.close()
    paths = []
    def _disk(ip):
        if not ip:
            return None
        d = (BASE / "static" / ip) if "resell_uploads" in str(ip) else Path(ip)
        return str(d.resolve()) if d.exists() else None
    for p in photos:
        dp = _disk(p["image_path"])
        if dp and dp not in paths:
            paths.append(dp)
    dp = _disk(row.get("image_path"))
    if dp and dp not in paths:
        paths.insert(0, dp)
    return paths


@router.post("/api/resell/listings/{lid}/browser-post")
def resell_browser_post(lid: int, body: dict):
    """Open the platform's create-listing page in the logged-in Store browser and
    attach the listing's photos. You paste the generated text and click submit
    (keeps login/CAPTCHA/2FA in your hands)."""
    platform = (body or {}).get("platform", "facebook").lower()
    url = _PLATFORM_CREATE.get(platform)
    if not url:
        raise HTTPException(400, f"Unknown platform: {platform}")
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Listing not found")
    row = dict(row)
    paths = _listing_photo_paths(lid, row)
    _alog("post", f"{platform}:{lid}", "running", f"Opening {url}")
    try:
        tab = _browser.browser.open(url, headless=False)
        time.sleep(5)   # let the create page (often React + login) settle
        guard = _login_guard(tab, platform, "post")
        if guard:
            guard["screenshot"] = _browser.browser.screenshot_b64()
            return guard
        uploaded = False
        if paths:
            try:
                uploaded = tab.upload_files('input[type="file"]', paths[:10])
            except Exception:
                uploaded = False
        filled = _autofill(tab, platform, row, (body or {}).get("overrides"))
        shot = _browser.browser.screenshot_b64()
    except Exception as e:
        _alog("post", f"{platform}:{lid}", "failed", str(e))
        raise HTTPException(502, f"Browser error: {e}")
    n_filled = sum(1 for v in filled.values() if v)
    if n_filled == 0 and not uploaded:
        _alog("post", f"{platform}:{lid}", "failed",
              "No fields filled and no photo field found (layout changed or page still loading)")
        return {
            "ok": False, "platform": platform, "create_url": url, "n_filled": 0,
            "fields_filled": filled, "photos_uploaded": False, "photo_count": len(paths),
            "screenshot": shot,
            "note": ("⚠️ Opened the create page but couldn't fill anything or find a photo box — "
                     "it may still be loading, or the layout changed. Check the browser window; "
                     "you can use “Fill Current Page” once the form is visible."),
        }
    _alog("post", f"{platform}:{lid}", "done",
          f"{n_filled} field(s) filled, {'photos attached' if uploaded else 'no photo box'}")
    return {
        "ok": True, "platform": platform, "create_url": url,
        "photos_uploaded": uploaded, "photo_count": len(paths),
        "fields_filled": filled, "n_filled": n_filled,
        "screenshot": shot,
        "note": (f"✅ Create page opened; {n_filled} field(s) auto-filled and "
                 f"{'photos attached' if uploaded else 'no photo field found'}. "
                 "Review in the browser window and submit."),
    }


def _listing_fill_values(row: dict) -> dict:
    price = row.get("asking_price") or row.get("ai_price_max") or ""
    return {
        "title": (row.get("title") or "")[:100],
        "price": str(int(price)) if price else "",
        "description": row.get("description") or "",
        "condition": row.get("condition") or "Good",
        "category": row.get("category") or "",
    }


# Fill by the field's visible label (robust on React marketplaces where inputs have no
# stable id/name). (value_key, label_text). Verified working on Facebook Marketplace.
_LABEL_FILL: dict = {
    "facebook":   [("title", "Title"), ("price", "Price"), ("description", "Description")],
    "offerup":    [("title", "Title"), ("price", "Price"), ("description", "Description")],
    "mercari":    [("title", "Listing title"), ("title", "Title"), ("price", "Price"), ("description", "Description")],
    "craigslist": [("title", "Title"), ("price", "Price"), ("description", "Description"),
                   ("title", "posting title"), ("description", "posting body")],
}


# Plain-form (Craigslist-style) selectors by field, tried in addition to label matching.
_CSS_FILL = {
    "title":       ['input[name="PostingTitle"]', '#PostingTitle'],
    "price":       ['input[name="Ask"]', '#Ask'],
    "description": ['textarea[name="PostingBody"]', '#PostingBody'],
}


def _merge_overrides(vals: dict, overrides: dict) -> dict:
    """Apply user-edited draft values (title/price/description) over the listing defaults."""
    if overrides:
        for k in ("title", "price", "description"):
            v = overrides.get(k)
            if v not in (None, ""):
                vals[k] = str(v)
    return vals


def _fill_current(tab, row: dict, overrides: dict = None) -> dict:
    """Fill whatever create form is currently open (label match + plain-form selectors).
    Works for single-page (Facebook) and multi-step (Craigslist, after you reach the form)."""
    vals = _merge_overrides(_listing_fill_values(row), overrides)
    filled = {}
    for key, label in [("title", "Title"), ("price", "Price"), ("description", "Description")]:
        if vals.get(key):
            try:
                if tab.type_by_label(label, vals[key]):
                    filled[key] = True
            except Exception:
                pass
    for key, sels in _CSS_FILL.items():
        if filled.get(key) or not vals.get(key):
            continue
        for sel in sels:
            try:
                if tab.exists(sel) and tab.type_into(sel, vals[key]):
                    filled[key] = True
                    break
            except Exception:
                pass
    return filled


@router.post("/api/resell/listings/{lid}/browser-fill")
def resell_browser_fill(lid: int, body: dict = None):
    """Fill the CURRENTLY-OPEN browser page from a listing (no navigation).
    Use this on multi-step sites (Craigslist) after you've clicked through to the form."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Listing not found")
    tab = _browser.browser._tab
    if not tab:
        raise HTTPException(400, "No browser page open — click a platform button or Launch Browser first.")
    row = dict(row)
    try:
        filled = _fill_current(tab, row, (body or {}).get("overrides"))
        paths = _listing_photo_paths(lid, row)
        uploaded = False
        if paths:
            try:
                uploaded = tab.upload_files('input[type="file"]', paths[:10])
            except Exception:
                uploaded = False
        shot = _browser.browser.screenshot_b64()
    except Exception as e:
        _alog("fill", lid, "failed", str(e))
        raise HTTPException(502, f"Browser error: {e}")
    n_filled = sum(1 for v in filled.values() if v)
    if n_filled == 0 and not uploaded:
        _alog("fill", lid, "failed", "No matching fields on the current page")
        return {"ok": False, "fields_filled": filled, "n_filled": 0, "photos_uploaded": False,
                "screenshot": shot,
                "note": ("⚠️ Couldn't find a Title/Price/Description field on this page. "
                         "Make sure you've clicked through to the actual posting form, then retry.")}
    _alog("fill", lid, "done", f"{n_filled} field(s) filled")
    return {"ok": True, "fields_filled": filled, "n_filled": n_filled,
            "photos_uploaded": uploaded, "screenshot": shot,
            "note": "✅ Filled the current page. Review and submit in the browser window."}


def _autofill(tab, platform: str, row: dict, overrides: dict = None) -> dict:
    vals = _merge_overrides(_listing_fill_values(row), overrides)
    filled = {}
    for key, label in _LABEL_FILL.get(platform, []):
        val = vals.get(key, "")
        if not val or filled.get(key):   # skip if no value or already filled by an earlier label
            continue
        try:
            if tab.type_by_label(label, val):
                filled[key] = True
        except Exception:
            pass
    return filled
