"""
Cash App — real-money rail #2 (receive-only), surfaced in the Money tab.

Two legitimate ways in (see cashapp_client.py for the 2026 research):
  • $cashtag payment-request links (https://cash.app/$Tag/12.34) — free, no creds.
  • Cash App Pay checkout pages via the Square (Block) platform — needs a Square
    access token; full sandbox support; real hosted checkout links.

Both actions that CREATE a payment request are approval-gated the same way as the
other money flows: they file a world_ops prayer (kinds cashapp_request /
cashapp_checkout) and only run once blessed in the God Console — unless you flip
their per-kind gate toggles OFF (every gate gets a toggle; these are money-IN, not
irreversible money-out, so unlike paypal_payout they ARE toggleable). Credentials
are stored via the settings table with secrets-at-rest encryption
(square_access_token is in crypto.SECRET_KEYS).
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import Response
from pydantic import BaseModel

from deps import get_conn, get_setting, _enc, _is_secret
import world_ops as wo
import cashapp_client

router = APIRouter()
logger = logging.getLogger("store")


# ── schema ───────────────────────────────────────────────────────────────────
def _ensure_schema():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS cashapp_requests (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        kind         TEXT,                 -- 'cashtag' | 'checkout'
        amount_cents INTEGER DEFAULT 0,
        note         TEXT DEFAULT '',
        url          TEXT DEFAULT '',
        link_id      TEXT DEFAULT '',
        prayer_id    INTEGER,
        created_at   TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()

_ensure_schema()


# ── config plumbing ──────────────────────────────────────────────────────────
# setting key → short name used by the config API/UI
_CFG_KEYS = (("cashapp_cashtag", "cashtag"), ("square_access_token", "access_token"),
             ("square_location_id", "location_id"), ("square_mode", "mode"))


def square_cfg() -> dict:
    return {"access_token": get_setting("square_access_token", "") or "",
            "location_id": get_setting("square_location_id", "") or "",
            "mode": get_setting("square_mode", "sandbox") or "sandbox"}


def _save_setting(conn, key: str, value: str):
    val = _enc(str(value)) if _is_secret(key) else str(value)
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, val))


# ── executors: only a blessed prayer creates a payable request ───────────────
def _exec_cashapp_request(conn, prayer):
    """Blessed cashapp_request → record the $cashtag payment-request link."""
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    amt_cents = int(payload.get("amount_cents") or 0)
    tag = cashapp_client.normalize_cashtag(get_setting("cashapp_cashtag", "") or "")
    if not tag:
        raise RuntimeError("no $cashtag configured")
    url = cashapp_client.cashtag_link(tag, amt_cents / 100.0 if amt_cents else None)
    if not url:
        raise RuntimeError("could not build cashtag link")
    conn.execute("INSERT INTO cashapp_requests (kind,amount_cents,note,url,prayer_id) "
                 "VALUES ('cashtag',?,?,?,?)",
                 (amt_cents, str(payload.get("note") or ""), url, prayer["id"]))
    conn.commit()
    return f"payment-request link ready: {url}"


def _exec_cashapp_checkout(conn, prayer):
    """Blessed cashapp_checkout → create a REAL Square checkout link (Cash App Pay).
    The prayer id doubles as the Square idempotency key, so a retry of the same
    blessed prayer never creates a second live link."""
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    amt_cents = int(payload.get("amount_cents") or 0)
    if amt_cents <= 0:
        raise RuntimeError("bad amount")
    res = cashapp_client.create_payment_link(
        square_cfg(), amt_cents,
        name=str(payload.get("name") or "Payment"),
        note=str(payload.get("note") or ""),
        idempotency_key=f"prayer-{prayer['id']}")
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "payment link failed")
    conn.execute("INSERT INTO cashapp_requests (kind,amount_cents,note,url,link_id,prayer_id) "
                 "VALUES ('checkout',?,?,?,?,?)",
                 (amt_cents, str(payload.get("note") or ""), res.get("url") or "",
                  res.get("link_id") or "", prayer["id"]))
    conn.commit()
    return f"checkout link ready: {res.get('url')}"


wo.register_executor("cashapp_request", _exec_cashapp_request)
wo.register_executor("cashapp_checkout", _exec_cashapp_checkout)


# ── status / config ──────────────────────────────────────────────────────────
@router.get("/api/cashapp/status")
def cashapp_status():
    """Everything the Money tab's Cash App card needs in one call. No network."""
    tag = cashapp_client.normalize_cashtag(get_setting("cashapp_cashtag", "") or "")
    sq = square_cfg()
    conn = get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM cashapp_requests").fetchone()["n"]
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM world_prayers WHERE status='pending' "
            "AND kind IN ('cashapp_request','cashapp_checkout')").fetchone()["n"]
    except Exception:
        n, pending = 0, 0
    finally:
        conn.close()
    return {
        "cashtag": tag,
        "cashtag_link": cashapp_client.cashtag_link(tag) if tag else "",
        "square": {"configured": bool(sq["access_token"]), "mode": sq["mode"],
                   "location_id": sq["location_id"]},
        "gates": {k: wo.cfg(f"world_ops_gate_{k}") == "1"
                  for k in ("cashapp_request", "cashapp_checkout")},
        "requests": n,
        "pending_prayers": pending,
    }


@router.post("/api/cashapp/config")
def cashapp_config(body: dict = Body(...)):
    """Save $cashtag and/or Square credentials. The access token is encrypted at
    rest (secrets-at-rest); only keys present in the body are touched."""
    updates = {}
    for sk, short in _CFG_KEYS:
        if short in body:
            updates[sk] = str(body[short] or "").strip()
    if "cashapp_cashtag" in updates and updates["cashapp_cashtag"]:
        tag = cashapp_client.normalize_cashtag(updates["cashapp_cashtag"])
        if not tag:
            raise HTTPException(400, "invalid $cashtag (letters/digits/._- , starts with a letter)")
        updates["cashapp_cashtag"] = tag
    if "square_mode" in updates and updates["square_mode"] not in ("", "sandbox", "production"):
        raise HTTPException(400, "mode must be 'sandbox' or 'production'")
    if not updates:
        raise HTTPException(400, "nothing to save")
    conn = get_conn()
    try:
        for k, v in updates.items():
            _save_setting(conn, k, v)
        conn.commit()
    finally:
        conn.close()
    return cashapp_status()


@router.post("/api/cashapp/verify")
def cashapp_verify():
    """Prove the stored Square token works (read-only ListLocations). Moves no money."""
    return cashapp_client.verify(square_cfg())


@router.get("/api/cashapp/payments")
def cashapp_payments(limit: int = 10):
    """Recent Square payments (watch Cash App Pay money arrive). Read-only."""
    return cashapp_client.list_payments(square_cfg(), limit=limit)


# ── gated money actions (each files a prayer) ────────────────────────────────
class RequestIn(BaseModel):
    amount_cents: Optional[int] = None
    amount_dollars: Optional[float] = None
    note: str = ""


def _amount_cents(body: RequestIn, required: bool = True) -> int:
    amt = body.amount_cents
    if amt is None and body.amount_dollars is not None:
        amt = int(round(float(body.amount_dollars) * 100))
    amt = int(amt or 0)
    if required and amt <= 0:
        raise HTTPException(400, "amount must be positive")
    return max(0, amt)


@router.post("/api/cashapp/request")
def cashapp_request(body: RequestIn):
    """Queue a $cashtag payment-request link. Files a gated prayer (kind
    cashapp_request) — the link is generated once you bless it in the God Console
    (or immediately, if you've toggled its gate off in budget mode)."""
    tag = cashapp_client.normalize_cashtag(get_setting("cashapp_cashtag", "") or "")
    if not tag:
        raise HTTPException(400, "no $cashtag configured — set it in the Money tab first")
    amt = _amount_cents(body, required=False)   # 0 = open-amount profile link
    label = f"${amt/100:.2f}" if amt else "any amount"
    p = wo.pray("cashapp_request",
                f"Cash App request: {label} to ${tag}",
                detail=(f"Generate a cash.app/${tag} payment-request link for {label}."
                        + (f" Note: {body.note}" if body.note else "")
                        + " Money-in only — the payer still confirms in their Cash App."),
                cost_cents=0,
                payload={"amount_cents": amt, "note": body.note})
    return {"prayer": p}


class CheckoutIn(RequestIn):
    name: str = "Payment"


@router.post("/api/cashapp/checkout")
def cashapp_checkout(body: CheckoutIn):
    """Queue a REAL Square checkout page (accepts Cash App Pay + cards). Files a
    gated prayer (kind cashapp_checkout); the live link is only created once blessed."""
    sq = square_cfg()
    if not sq["access_token"]:
        raise HTTPException(400, "Square not configured — save an access token first")
    amt = _amount_cents(body, required=True)
    p = wo.pray("cashapp_checkout",
                f"Cash App Pay checkout: ${amt/100:.2f}",
                detail=(f"Create a Square-hosted checkout link for ${amt/100:.2f} "
                        f"({sq['mode']}) that accepts Cash App Pay."
                        + (f" Note: {body.note}" if body.note else "")),
                cost_cents=0,
                payload={"amount_cents": amt, "name": body.name, "note": body.note})
    return {"prayer": p}


# ── request history + QR ─────────────────────────────────────────────────────
@router.get("/api/cashapp/requests")
def cashapp_requests(limit: int = 25):
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM cashapp_requests ORDER BY id DESC LIMIT ?",
                            (limit,)).fetchall()
        return {"requests": [dict(r) for r in rows]}
    finally:
        conn.close()


def _qr_response(data: str) -> Response:
    png = cashapp_client.qr_png(data)
    if not png:
        raise HTTPException(503, "QR generation unavailable (install the 'qrcode' package)")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/cashapp/qr")
def cashapp_profile_qr():
    """QR of the bare cash.app/$tag profile link — 'scan to pay me anything'."""
    tag = cashapp_client.normalize_cashtag(get_setting("cashapp_cashtag", "") or "")
    if not tag:
        raise HTTPException(400, "no $cashtag configured")
    return _qr_response(cashapp_client.cashtag_link(tag))


@router.get("/api/cashapp/requests/{rid}/qr")
def cashapp_request_qr(rid: int):
    """QR for a stored (blessed) request's link only — never arbitrary data."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT url FROM cashapp_requests WHERE id=?", (rid,)).fetchone()
    finally:
        conn.close()
    if not row or not row["url"]:
        raise HTTPException(404, "request not found")
    return _qr_response(row["url"])
