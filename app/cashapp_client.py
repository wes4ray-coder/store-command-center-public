"""
Cash App client — the second real-money rail (alongside paypal_client.py).

Research summary (2026): there is NO official API for personal Cash App accounts
(no balance / send / receive endpoints — the reverse-engineered ones violate ToS and
are not used here). The two legitimate rails, both RECEIVE-only, are:

  1. $cashtag payment links — https://cash.app/$yourtag/12.34 deep links open the
     Cash App payment sheet pre-filled with the amount. Works for personal AND
     business accounts, needs no credentials, moves no money by itself (the payer
     still confirms in their app). Business accounts pay ~2.75% per received payment;
     personal accounts are free but have receive limits until verified.

  2. Cash App Pay via the Square (Block) developer platform — a Square developer
     account + Square application gives an access token; the Checkout / Payment
     Links API creates hosted checkout pages that accept Cash App Pay. Sandbox is
     fully supported (connect.squareupsandbox.com + sandbox test accounts). Online
     fees are Square's standard 3.3% + 30¢ on the free plan (post-Jan-2026 pricing).
     Requires Square seller onboarding (SSN/ITIN for US identity verification) to
     go LIVE; sandbox needs none.

Like paypal_client.py, every call is best-effort and returns {ok/connected, error}
dicts instead of throwing, so the UI can show status. Anything that CREATES a real
payment request only ever runs from a blessed prayer (see routers/cashapp.py).
"""
from __future__ import annotations
import io
import logging
import re

import httpx

logger = logging.getLogger("store")

_LIVE = "https://connect.squareup.com"
_SANDBOX = "https://connect.squareupsandbox.com"
_SQ_VERSION = "2025-01-23"          # Square-Version API pin


def _base(mode) -> str:
    return _SANDBOX if str(mode or "").lower() == "sandbox" else _LIVE


def _headers(cfg) -> dict:
    return {"Authorization": f"Bearer {cfg.get('access_token', '')}",
            "Square-Version": _SQ_VERSION,
            "Content-Type": "application/json"}


# ── $cashtag deep links (no credentials needed) ──────────────────────────────
def normalize_cashtag(tag: str) -> str:
    """'$Acme ' / 'acme' → 'Acme' (bare tag, no $). Empty if invalid."""
    t = (tag or "").strip().lstrip("$").strip()
    return t if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,29}", t) else ""


def cashtag_link(cashtag: str, amount_dollars=None) -> str:
    """Payment-request deep link. With an amount it opens the payer's Cash App
    pre-filled: https://cash.app/$Tag/12.34 — without, it's the profile link."""
    tag = normalize_cashtag(cashtag)
    if not tag:
        return ""
    url = f"https://cash.app/${tag}"
    if amount_dollars is not None:
        try:
            amt = round(float(amount_dollars), 2)
        except Exception:
            return ""
        if amt <= 0:
            return ""
        # Cash App accepts both /25 and /25.50 forms; keep cents only when needed.
        url += f"/{int(amt)}" if amt == int(amt) else f"/{amt:.2f}"
    return url


def qr_png(data: str) -> bytes | None:
    """QR code PNG for a link (scanned by the payer's phone). None if the optional
    `qrcode` package isn't installed — callers degrade to showing the plain link."""
    try:
        import qrcode
        img = qrcode.make(data, box_size=6, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning("cashapp qr generation unavailable: %s", e)
        return None


# ── Square / Cash App Pay (credentials required) ─────────────────────────────
def verify(cfg):
    """Prove the stored Square token works. Safe, read-only — lists locations.
    Also resolves a default location_id when one isn't configured."""
    if not cfg.get("access_token"):
        return {"connected": False, "mode": cfg.get("mode"),
                "error": "Square not configured (access token missing)"}
    try:
        with httpx.Client(timeout=20) as c:
            r = c.get(f"{_base(cfg.get('mode'))}/v2/locations", headers=_headers(cfg))
        if r.status_code != 200:
            return {"connected": False, "mode": cfg.get("mode"),
                    "error": f"auth failed ({r.status_code}): {r.text[:160]}"}
        locs = r.json().get("locations") or []
        return {"connected": True, "mode": cfg.get("mode"),
                "locations": [{"id": l.get("id"), "name": l.get("name"),
                               "status": l.get("status")} for l in locs],
                "location_id": cfg.get("location_id") or (locs[0]["id"] if locs else None),
                "error": None}
    except Exception as e:
        return {"connected": False, "mode": cfg.get("mode"), "error": str(e)}


def create_payment_link(cfg, amount_cents: int, name: str = "Payment",
                        note: str = "", idempotency_key: str | None = None):
    """Create a hosted Square checkout page that accepts Cash App Pay (+ cards).
    This CREATES a real payable link, so it only ever runs from a blessed
    cashapp_checkout prayer. Returns {ok, url, link_id, order_id, error}."""
    try:
        amt = int(amount_cents)
    except Exception:
        return {"ok": False, "error": "bad amount"}
    if amt <= 0:
        return {"ok": False, "error": "amount must be positive"}
    if not cfg.get("access_token"):
        return {"ok": False, "error": "Square not configured (access token missing)"}

    location_id = cfg.get("location_id")
    if not location_id:
        v = verify(cfg)
        location_id = v.get("location_id")
        if not location_id:
            return {"ok": False, "error": v.get("error") or "no Square location found"}

    body = {
        "idempotency_key": idempotency_key or f"store-{name[:20]}-{amt}",
        "quick_pay": {
            "name": (name or "Payment")[:255],
            "price_money": {"amount": amt, "currency": "USD"},
            "location_id": location_id,
        },
        "checkout_options": {
            "accepted_payment_methods": {
                "cash_app_pay": True,
                "apple_pay": True,
                "google_pay": True,
            },
        },
    }
    if note:
        body["payment_note"] = note[:500]
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{_base(cfg.get('mode'))}/v2/online-checkout/payment-links",
                       json=body, headers=_headers(cfg))
        if r.status_code not in (200, 201):
            return {"ok": False, "error": f"payment link failed ({r.status_code}): {r.text[:200]}"}
        link = r.json().get("payment_link") or {}
        return {"ok": True, "url": link.get("url") or link.get("long_url"),
                "link_id": link.get("id"), "order_id": link.get("order_id")}
    except Exception as e:
        logger.exception("square payment link failed")
        return {"ok": False, "error": str(e)}


def list_payments(cfg, limit: int = 10):
    """Recent payments on the Square account (shows Cash App Pay money arriving).
    Read-only. Returns {ok, payments: [...], error}."""
    if not cfg.get("access_token"):
        return {"ok": False, "error": "Square not configured", "payments": []}
    try:
        with httpx.Client(timeout=20) as c:
            r = c.get(f"{_base(cfg.get('mode'))}/v2/payments",
                      params={"limit": max(1, min(int(limit), 100)), "sort_order": "DESC"},
                      headers=_headers(cfg))
        if r.status_code != 200:
            return {"ok": False, "error": f"({r.status_code}): {r.text[:160]}", "payments": []}
        out = []
        for p in r.json().get("payments") or []:
            out.append({"id": p.get("id"),
                        "amount_cents": (p.get("amount_money") or {}).get("amount"),
                        "status": p.get("status"),
                        "source": p.get("source_type"),
                        "created_at": p.get("created_at")})
        return {"ok": True, "payments": out, "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e), "payments": []}
