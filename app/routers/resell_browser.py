"""Resale browser automation — the Store's own headless Chrome for marketplace
posting, auto-fill, AI haggling, and the inbox reader. A second router, included in
main.py alongside resell.py (which keeps the listings/offers/research endpoints)."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from deps import *
from services import *

router = APIRouter()


import browser as _browser


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


# ─── AI haggling: draft a negotiation reply for an offer ─────────────────────
_HAGGLE_SYSTEM = (
    "You are a friendly, street-smart reseller negotiating a LOCAL marketplace sale. "
    "Given the listing and a buyer's offer/message, decide ACCEPT, COUNTER, or DECLINE and "
    "write a short, polite reply to send the buyer.\n"
    "Rules:\n"
    "- NEVER go below the seller's minimum price.\n"
    "- If the offer meets/exceeds the minimum (or is close and fair), lean toward accepting.\n"
    "- When countering, pick a sensible number between the offer and the asking price.\n"
    "- Factor in distance & the seller's gas cost: if the buyer is far, either hold price firmer or "
    "propose meeting at a safe PUBLIC spot near the midpoint (e.g. a gas station / store parking lot).\n"
    "- If accepting or close, propose a meeting spot + a time window.\n"
    "Output EXACTLY these three lines and nothing else:\n"
    "DECISION: accept|counter|decline\n"
    "COUNTER: <number, or - if not countering>\n"
    "REPLY: <the exact message to send the buyer>"
)


def _parse_haggle(raw: str) -> dict:
    """Parse DECISION/COUNTER/REPLY. Reasoning models restate the format while thinking,
    so we take the LAST real occurrence (the final answer) and ignore the template echo."""
    lines = (raw or "").splitlines()
    decision, counter, reply_idx = "", None, -1
    for i, line in enumerate(lines):
        low = line.strip().lower()
        if low.startswith("decision:"):
            d = line.split(":", 1)[1].strip().lower()
            for w in ("accept", "counter", "decline"):
                if d == w or (w in d and "|" not in d and " or " not in d):
                    decision = w
                    break
        elif low.startswith("counter:"):
            nums = "".join(c for c in line.split(":", 1)[1] if c.isdigit() or c == ".")
            if nums:
                try:
                    counter = float(nums)
                except Exception:
                    pass
        elif low.startswith("reply:"):
            reply_idx = i
    reply = ""
    if reply_idx >= 0:
        first = lines[reply_idx].split(":", 1)[1].strip()
        rest = "\n".join(lines[reply_idx + 1:]).strip()
        reply = (first + ("\n" + rest if rest else "")).strip()
    if not reply or reply.startswith("<"):
        reply = (raw or "").strip()[-800:]   # fallback: tail of the output
    return {"decision": decision or "counter", "counter_price": counter, "reply": reply}


@router.post("/api/resell/offers/{offer_id}/ai-reply")
def resell_offer_ai_reply(offer_id: int):
    """Have the local model draft an accept/counter/decline reply for an offer."""
    conn = get_conn()
    o = conn.execute("SELECT * FROM resell_offers WHERE id=?", (offer_id,)).fetchone()
    if not o:
        conn.close()
        raise HTTPException(404, "Offer not found")
    o = dict(o)
    l = conn.execute("SELECT * FROM resell_listings WHERE id=?", (o["listing_id"],)).fetchone()
    conn.close()
    l = dict(l) if l else {}
    ctx = (
        f"Listing: {l.get('title','item')} — asking ${l.get('asking_price')}, "
        f"minimum acceptable ${l.get('min_accept_price') or 'not set (use your judgment above asking*0.8)'}, "
        f"condition {l.get('condition','')}, pricing mode {l.get('price_mode','obo')}.\n"
        f"Buyer offered: ${o.get('offer_amount') or 'no number given'}. "
        f"Buyer message: \"{o.get('buyer_message') or '(none)'}\"\n"
        f"Buyer location: {o.get('buyer_location') or 'unknown'}"
        + (f", ~{o['distance_miles']} miles away, seller round-trip gas ~${o.get('gas_cost')}." if o.get('distance_miles') else ".")
        + f"\nAccepted payment: {l.get('payment_methods','cash')}. Shipping policy: {l.get('shipping_policy','pickup')}."
    )

    def _work():
        try:
            raw = _call_lmstudio(get_prompt('resell_haggle'), ctx, max_tokens=1800)
        except Exception as e:
            _alog("ai-reply", offer_id, "failed", str(e))
            raise
        out = _parse_haggle(raw)
        out["raw"] = raw
        _alog("ai-reply", offer_id, "done", f"{out.get('decision','?')} — draft ready")
        return out

    tid = orch.submit_llm(_work, desc=f"Haggle offer {offer_id}")
    return {"task_id": tid}


@router.post("/api/resell/offers/{offer_id}/send-reply")
def resell_offer_send_reply(offer_id: int, body: dict):
    """Type a (reviewed) reply into the chat composer open in the Store browser.
    You navigate to the buyer's conversation, then this fills the box — you press Enter."""
    reply = (body or {}).get("reply", "").strip()
    if not reply:
        raise HTTPException(400, "reply text required")
    tab = _browser.browser._tab
    if not tab:
        raise HTTPException(400, "Open the chat in the Store browser first (Launch Browser → go to the conversation).")
    try:
        ok = tab.fill_composer(reply)
        shot = _browser.browser.screenshot_b64()
    except Exception as e:
        _alog("reply", offer_id, "failed", str(e))
        raise HTTPException(502, f"Browser error: {e}")
    _alog("reply", offer_id, "done" if ok else "failed",
          "Typed into chat box" if ok else "No message box found on page")
    return {"ok": ok, "screenshot": shot,
            "note": ("✅ Reply typed into the chat box — review and press Enter to send."
                     if ok else "⚠️ Couldn't find a message box on this page. Open the conversation first.")}


# ─── Inbox reader: scrape marketplace messages → parse → auto-create offers ──
_INBOX_URLS = {
    "facebook": "https://www.facebook.com/marketplace/inbox/",
}

_INBOX_PARSE_SYSTEM = (
    "You are parsing the text of a marketplace SELLER inbox. Extract each buyer conversation "
    "you can identify. For EACH conversation output ONE line in EXACTLY this pipe format and "
    "nothing else:\n"
    "buyer name | their latest message | item they're asking about | offer amount in dollars (or -)\n"
    "Ignore UI chrome, nav, and your own listings. If there are no real buyer conversations, output: NONE"
)


def _parse_inbox(raw: str) -> list:
    out = []
    for line in (raw or "").splitlines():
        s = line.strip().strip("`").lstrip("-*• ").strip()
        if s.upper() == "NONE":
            continue
        parts = [p.strip() for p in s.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        name = parts[0][:80]
        msg = parts[1] if len(parts) > 1 else ""
        item = parts[2] if len(parts) > 2 else ""
        amt = None
        if len(parts) > 3:
            nums = "".join(c for c in parts[3] if c.isdigit() or c == ".")
            if nums:
                try:
                    amt = float(nums)
                except Exception:
                    amt = None
        if msg:
            out.append({"buyer_name": name, "buyer_message": msg, "item": item, "offer_amount": amt})
    return out


def _match_listing(item: str):
    """Best-effort match a conversation's item to one of the user's listings."""
    conn = get_conn()
    rows = conn.execute("SELECT id, title FROM resell_listings ORDER BY created_at DESC").fetchall()
    conn.close()
    if not rows:
        return None
    it = (item or "").lower()
    for r in rows:
        t = (r["title"] or "").lower()
        if t and (t in it or it in t or (it and it.split()[0] in t)):
            return r["id"]
    return rows[0]["id"]   # fallback: most recent listing


@router.post("/api/resell/inbox/read")
def resell_inbox_read(body: dict = None):
    """Open a marketplace inbox, read the conversations, and (via the local model) turn new
    ones into offers. Returns {task_id} to poll, or {empty:true} if the inbox has no chats."""
    platform = (body or {}).get("platform", "facebook")
    url = _INBOX_URLS.get(platform)
    if not url:
        raise HTTPException(400, f"Inbox reading not supported for {platform}")
    _alog("inbox", platform, "running", "Opening inbox")
    try:
        tab = _browser.browser.open(url, headless=False)
        time.sleep(8)
        guard = _login_guard(tab, platform, "inbox")
        if guard:
            guard["screenshot"] = _browser.browser.screenshot_b64()
            return guard
        text = (tab.eval_js("(document.querySelector('[role=\"main\"]')||document.body).innerText") or "").strip()
        shot = _browser.browser.screenshot_b64()
    except Exception as e:
        _alog("inbox", platform, "failed", str(e))
        raise HTTPException(502, f"Browser error (is the Store browser logged in?): {e}")
    if "No chats" in text or len(text) < 60:
        _alog("inbox", platform, "done", "Inbox empty")
        return {"empty": True, "created": 0, "conversations": [], "screenshot": shot,
                "note": "📭 No messages in the inbox right now."}

    snippet = text[:6000]

    def _work():
        try:
            raw = _call_lmstudio(get_prompt('resell_inbox'), snippet, max_tokens=1500)
            convos = _parse_inbox(raw)
        except Exception as e:
            _alog("inbox", platform, "failed", f"Parse error: {e}")
            raise
        created = 0
        conn = get_conn()
        for c in convos:
            # dedup: same buyer + message already recorded?
            dup = conn.execute("SELECT id FROM resell_offers WHERE buyer_name=? AND buyer_message=?",
                               (c["buyer_name"], c["buyer_message"])).fetchone()
            if dup:
                continue
            lid = _match_listing(c["item"])
            if not lid:
                continue
            conn.execute("INSERT INTO resell_offers (listing_id, platform, buyer_name, buyer_message, offer_amount, status) "
                         "VALUES (?,?,?,?,?, 'pending')",
                         (lid, platform, c["buyer_name"], c["buyer_message"], c["offer_amount"]))
            created += 1
        conn.commit()
        conn.close()
        _alog("inbox", platform, "done",
              f"Read {len(convos)} conversation(s), {created} new offer(s)")
        return {"created": created, "conversations": convos}

    tid = orch.submit_llm(_work, desc="Read marketplace inbox")
    return {"task_id": tid, "screenshot": shot}
