"""
PayPal REST client — the real money rail (Chunk 5).

Two things the company actually needs:
  • verify()        — prove the stored keys work (OAuth client-credentials). Safe,
                      read-only; used to show "Connected ✓ (live)".
  • create_payout() — the company pays YOU real money (Cults3D/store earnings)
                      to your PayPal email via the Payouts API. This MOVES REAL
                      MONEY, so it only ever runs when a paypal_payout prayer is
                      blessed in the God Console — never automatically.

Live vs sandbox is chosen by cfg['mode']. All calls are best-effort and return
{ok/connected, error} dicts instead of throwing, so the UI can show status.
"""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger("store")

_LIVE = "https://api-m.paypal.com"
_SANDBOX = "https://api-m.sandbox.paypal.com"


def _base(mode):
    return _SANDBOX if str(mode).lower() == "sandbox" else _LIVE


def get_token(cfg):
    """OAuth client-credentials token. Returns (token, error)."""
    cid, secret = cfg.get("client_id"), cfg.get("secret")
    if not (cid and secret):
        return None, "PayPal not configured (client_id/secret missing)"
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(f"{_base(cfg.get('mode'))}/v1/oauth2/token",
                       data={"grant_type": "client_credentials"},
                       auth=(cid, secret),
                       headers={"Accept": "application/json"})
        if r.status_code != 200:
            return None, f"auth failed ({r.status_code}): {r.text[:160]}"
        return r.json().get("access_token"), None
    except Exception as e:
        return None, str(e)


def verify(cfg):
    """Prove the keys work. Safe — only fetches an OAuth token."""
    tok, err = get_token(cfg)
    return {"connected": bool(tok), "mode": cfg.get("mode"),
            "email": cfg.get("email"), "error": err}


def create_payout(cfg, amount_dollars, receiver_email, note="Company earnings", prayer_id=None):
    """Send a real PayPal payout to receiver_email. Returns {ok, batch_id, status, error}.
    Only called by the blessed paypal_payout prayer. `prayer_id`, when given, becomes the
    PayPal sender_batch_id so a retry of the SAME prayer is de-duplicated by PayPal
    (never pays twice)."""
    if not receiver_email:
        return {"ok": False, "error": "no receiver email configured"}
    try:
        amt = round(float(amount_dollars), 2)
    except Exception:
        return {"ok": False, "error": "bad amount"}
    if amt <= 0:
        return {"ok": False, "error": "amount must be positive"}

    tok, err = get_token(cfg)
    if not tok:
        return {"ok": False, "error": err or "no token"}

    header = {
        "email_subject": "Your company sent you earnings",
        "email_message": note,
    }
    if prayer_id is not None:
        # idempotency: PayPal rejects a duplicate sender_batch_id, so retrying the same
        # blessed prayer can never send the money twice.
        header["sender_batch_id"] = f"prayer-{prayer_id}"
    body = {
        "sender_batch_header": header,
        "items": [{
            "recipient_type": "EMAIL",
            "amount": {"value": f"{amt:.2f}", "currency": "USD"},
            "receiver": receiver_email,
            "note": note,
        }],
    }
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{_base(cfg.get('mode'))}/v1/payments/payouts",
                       json=body,
                       headers={"Authorization": f"Bearer {tok}",
                                "Content-Type": "application/json"})
        if r.status_code not in (200, 201, 202):
            return {"ok": False, "error": f"payout failed ({r.status_code}): {r.text[:200]}"}
        data = r.json()
        bh = data.get("batch_header", {})
        return {"ok": True, "batch_id": bh.get("payout_batch_id"),
                "status": bh.get("batch_status")}
    except Exception as e:
        logger.exception("paypal payout failed")
        return {"ok": False, "error": str(e)}
