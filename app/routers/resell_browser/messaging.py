"""resell_browser — Domain C: AI haggling (draft accept/counter/decline replies),
sending a reviewed reply into the chat composer, and the marketplace inbox reader."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from deps import *
from services import *
from ._base import router, _alog, _login_guard, _PLATFORM_CREATE
import browser as _browser


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
