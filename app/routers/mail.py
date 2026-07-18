"""Mail / Quotes — read customer email from the self-hosted Mailcow mailbox, draft a
labor quote with the local LLM (respecting Acme Carpentry's terms), and send replies.

The Store app runs on the host, so it reaches Mailcow's IMAP (993) + submission (587)
directly on 127.0.0.1. Credentials live in the settings table (mail_* keys), seeded to
the Mailcow support@example.com mailbox.
"""
import imaplib, smtplib, ssl, email, re, os, io, base64
import httpx
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr, formataddr, make_msgid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import *          # get_conn, get_setting, orch, _call_lmstudio, BASE
from services import *

router = APIRouter()

ATTACH_DIR = BASE / "mail_attachments"
ATTACH_DIR.mkdir(exist_ok=True)

_DEFAULTS = {
    "mail_imap_host": "127.0.0.1", "mail_imap_port": "993",
    "mail_smtp_host": "127.0.0.1", "mail_smtp_port": "587",
    "mail_user": "support@example.com",
}

def _cfg(k):
    return get_setting(k, "") or _DEFAULTS.get(k, "")

def _ssl_noverify():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
    return c

def _imap():
    pw = _cfg("mail_pass")
    if not pw:
        raise HTTPException(400, "Mail password not set (Settings → mail_pass).")
    try:
        M = imaplib.IMAP4_SSL(_cfg("mail_imap_host"), int(_cfg("mail_imap_port")), ssl_context=_ssl_noverify())
        M.login(_cfg("mail_user"), pw)
        return M
    except Exception as e:
        raise HTTPException(502, f"IMAP connect/login failed: {e}")

def _dec(s):
    if not s: return ""
    out = []
    for part, enc in decode_header(s):
        out.append(part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part)
    return "".join(out)

def _body_and_images(msg, uid):
    """Return (text_body, [image_urls]). Saves image attachments under mail_attachments/uid/."""
    text, html, imgs = "", "", []
    idx = 0
    for part in msg.walk():
        ctype = part.get_content_type()
        disp = str(part.get("Content-Disposition") or "")
        if ctype == "text/plain" and "attachment" not in disp and not text:
            text = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
        elif ctype == "text/html" and "attachment" not in disp and not html:
            html = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
        elif ctype.startswith("image/"):
            data = part.get_payload(decode=True)
            if data:
                ext = ctype.split("/")[-1].split("+")[0][:4] or "jpg"
                d = ATTACH_DIR / str(uid); d.mkdir(exist_ok=True)
                fn = f"{idx}.{ext}"; (d / fn).write_bytes(data)
                imgs.append(f"/mail-attachments/{uid}/{fn}")
                idx += 1
    if not text and html:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
    return text.strip(), imgs


# ── config ───────────────────────────────────────────────────────────────────
class MailCfg(BaseModel):
    mail_imap_host: Optional[str] = None
    mail_imap_port: Optional[str] = None
    mail_smtp_host: Optional[str] = None
    mail_smtp_port: Optional[str] = None
    mail_user: Optional[str] = None
    mail_pass: Optional[str] = None

@router.get("/api/mail/config")
def mail_config_get():
    return {k: _cfg(k) for k in _DEFAULTS} | {"mail_pass_set": bool(_cfg("mail_pass"))}

@router.post("/api/mail/config")
def mail_config_set(c: MailCfg):
    conn = get_conn()
    for k, v in c.dict().items():
        if v is not None:
            val = v.strip()
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                         (k, _enc(val) if _is_secret(k) else val))
    conn.commit(); conn.close()
    return {"ok": True}


# ── inbox ────────────────────────────────────────────────────────────────────
@router.get("/api/mail/inbox")
def inbox(limit: int = 30):
    M = _imap()
    try:
        M.select("INBOX")
        typ, data = M.search(None, "ALL")
        ids = data[0].split()[-limit:][::-1]
        out = []
        for i in ids:
            t, d = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] FLAGS UID)")
            raw = b""; uid = i.decode(); seen = False
            for item in d:
                if isinstance(item, tuple):
                    raw += item[1]
                    m = re.search(rb"UID (\d+)", item[0]);
                    if m: uid = m.group(1).decode()
                    if b"\\Seen" in item[0]: seen = True
            h = email.message_from_bytes(raw)
            frm = parseaddr(_dec(h.get("From")))
            out.append({"uid": uid, "from_name": frm[0] or frm[1], "from_email": frm[1],
                        "subject": _dec(h.get("Subject")) or "(no subject)",
                        "date": _dec(h.get("Date")), "seen": seen})
        return {"count": len(out), "messages": out}
    finally:
        try: M.logout()
        except Exception: pass

@router.get("/api/mail/message/{uid}")
def message(uid: str):
    M = _imap()
    try:
        M.select("INBOX")
        t, d = M.uid("fetch", uid, "(RFC822)")
        if not d or not d[0]:
            raise HTTPException(404, "Message not found")
        msg = email.message_from_bytes(d[0][1])
        M.uid("store", uid, "+FLAGS", "\\Seen")
        frm = parseaddr(_dec(msg.get("From")))
        body, imgs = _body_and_images(msg, uid)
        return {"uid": uid, "from_name": frm[0] or frm[1], "from_email": frm[1],
                "subject": _dec(msg.get("Subject")), "date": _dec(msg.get("Date")),
                "message_id": msg.get("Message-ID", ""), "body": body, "images": imgs}
    finally:
        try: M.logout()
        except Exception: pass


# ── AI quote draft ───────────────────────────────────────────────────────────
_QUOTE_SYS = (
    "You are the assistant for Acme Carpentry, a solo precision carpenter in "
    "your local area. Draft a friendly, professional email REPLY to a customer's "
    "request. Follow these NON-NEGOTIABLE terms exactly:\n"
    "- Labor only: $40/hour, 4-hour minimum. The clock starts when the job starts.\n"
    "- NO fixed-price bids or contracts — only a simple labor agreement. Give an HOURLY estimate "
    "as a RANGE of hours (e.g. 'roughly 6–10 hours'), never a fixed total price promise.\n"
    "- The customer buys/provides all materials from a list the carpenter gives them; the carpenter does not supply materials.\n"
    "- No work, no charge. If unhappy, they can ask him to stop and pay only for hours worked.\n"
    "- The carpenter does NOT do: full re-siding, sheetrock finishing (tape/bed/paint — he hangs it), "
    "shingles (he dry-ins watertight), concrete beyond a fence post or two, custom cabinets from "
    "scratch, or windows past a one-person (~5'6\") reach. If the request is clearly outside this, "
    "say so kindly and suggest what he CAN do.\n"
    "Keep it warm, concise, and confident. Include the hours estimate, the $40/hr + 4-hr-min terms, "
    "the materials note, and a friendly close inviting them to book. Sign as 'Acme Carpentry'. "
    "Output ONLY the email reply body text, no subject line."
)

class DraftIn(BaseModel):
    uid: Optional[str] = None
    text: Optional[str] = None

def _img_data_url(path, max_px=1024):
    """Resize an image for the vision model and return a data: URL (keeps payload small)."""
    from PIL import Image
    im = Image.open(path).convert("RGB"); im.thumbnail((max_px, max_px))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

@router.post("/api/mail/draft-quote")
def draft_quote(req: DraftIn):
    text = (req.text or "").strip()
    image_paths = []
    if req.uid:
        m = message(req.uid)                 # fetches body + saves photo attachments to disk
        if not text:
            text = m.get("body", "")
        for url in m.get("images", []):      # /mail-attachments/{uid}/{fn} → disk path
            # NB: URL uses the hyphenated mount (/mail-attachments) but files live in
            # ATTACH_DIR (mail_attachments, underscore) — map by the tail, not the URL verbatim.
            p = ATTACH_DIR / url.split("/mail-attachments/", 1)[-1]
            if p.exists():
                image_paths.append(p)
    if not text and not image_paths:
        raise HTTPException(400, "No message text to quote from.")

    def _work():
        content = [{"type": "text", "text": f"Customer request:\n{text[:2500]}"}]
        for p in image_paths[:4]:            # cap at 4 photos
            try:
                content.append({"type": "image_url", "image_url": {"url": _img_data_url(p)}})
            except Exception:
                pass
        model = getattr(orch, "_current_llm_model", None) or ENHANCE_MODEL
        try:                            # editable copy in the prompt registry (mail_quote)
            from prompts import get_prompt
            quote_sys = get_prompt("mail_quote")
        except Exception:
            quote_sys = _QUOTE_SYS
        if len(content) > 1:
            # Vision: the model 400s on a separate system role next to images → fold the
            # instructions into the user turn instead.
            content[0]["text"] = (quote_sys + "\n\n----\n" + content[0]["text"] +
                "\n\nThe customer attached the photo(s) above. Look at them to judge the actual "
                "scope, materials, and any rot/damage, and factor that into your hours estimate. "
                "Mention what you can see in the photos.")
            messages = [{"role": "user", "content": content}]
        else:
            messages = [{"role": "system", "content": quote_sys},
                        {"role": "user", "content": content[0]["text"]}]
        body = {"model": model, "messages": messages,
                "max_tokens": 750, "temperature": 0.7, "reasoning_effort": "none"}
        r = httpx.post(f"{LMSTUDIO_URL}/chat/completions", json=body, headers=_llm_headers(), timeout=400)
        r.raise_for_status()
        out = (r.json()["choices"][0]["message"].get("content") or "").strip()
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.DOTALL).strip()
        return {"quote": out, "photos_analyzed": len(content) - 1}
    tid = orch.submit_llm(_work, desc="Draft carpentry quote (vision)", task="mail_quote")
    return {"task_id": tid}


# ── send reply ───────────────────────────────────────────────────────────────
class SendIn(BaseModel):
    to: str
    subject: str
    body: str
    in_reply_to: Optional[str] = ""

@router.post("/api/mail/send")
def send(req: SendIn):
    to = parseaddr(req.to)[1]
    if not to or "@" not in to:
        raise HTTPException(400, "Invalid recipient.")
    pw = _cfg("mail_pass")
    if not pw:
        raise HTTPException(400, "Mail password not set.")
    frm = _cfg("mail_user")
    msg = MIMEMultipart()
    msg["From"] = formataddr(("Acme Carpentry", frm))
    msg["To"] = to
    msg["Subject"] = req.subject or "Re: your project"
    msg["Message-ID"] = make_msgid(domain="example.com")
    if req.in_reply_to:
        msg["In-Reply-To"] = req.in_reply_to; msg["References"] = req.in_reply_to
    msg.attach(MIMEText(req.body, "plain", "utf-8"))
    try:
        s = smtplib.SMTP(_cfg("mail_smtp_host"), int(_cfg("mail_smtp_port")), timeout=25)
        s.starttls(context=_ssl_noverify()); s.login(frm, pw)
        s.sendmail(frm, [to], msg.as_string()); s.quit()
    except Exception as e:
        raise HTTPException(502, f"Send failed: {e}")
    return {"ok": True, "to": to}
