"""Shared base for the world_ops (God Console) package.

Split out of the former monolithic ``routers/world_ops.py``. Holds the single
shared ``APIRouter``, the media→URL helpers used across submodules, and the ONE
import-time side effect the original module had at its top: importing the
executor-registering world modules (world_bible / world_sell / world_control) and
registering the ``paypal_payout`` executor. Imported first (via ``__init__``), so
those registrations happen exactly once, before any submodule's routes load.

Note: ``import world_ops`` here resolves to the top-level ``app/world_ops.py``
backbone module (on sys.path), NOT this package (``routers.world_ops``)."""
import json, logging, threading, os
from fastapi import APIRouter, HTTPException, Body

from deps import get_conn
from config import DESIGNS_PENDING, DESIGNS_APPROVED, DESIGNS_REJECTED
import world_ops as wo
import world_auto
import world_strategy
import world_bible          # registers the library_research executor on import
import world_sell           # registers the post_etsy/post_printify executors on import
import world_control        # unified automation control plane (runs init() on import)
import paypal_client

router = APIRouter()
logger = logging.getLogger("store")


# ── executor: a blessed payout sends REAL money to your PayPal ───────────────
def _exec_paypal_payout(conn, prayer):
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    amt_cents = int(payload.get("amount_cents") or 0)
    # SECURITY: the payout recipient is ALWAYS the configured owner email — never a
    # value carried in the (attacker-controllable) payload. A local/MCP caller that
    # files a payout can never redirect the money to a different account.
    email = wo.cfg("world_paypal_email")
    if amt_cents <= 0 or not email:
        raise ValueError("invalid payout (amount/owner email)")
    if wo.balance_cents(conn) < amt_cents:
        raise ValueError("insufficient wallet balance for this payout")
    res = paypal_client.create_payout(wo.paypal_cfg(), amt_cents / 100.0, email,
                                      note=payload.get("note") or "Company earnings",
                                      prayer_id=prayer["id"])
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "payout failed")
    wo._ledger(conn, -amt_cents, "payout", source="paypal",
               note=f"withdraw to {email}", prayer_id=prayer["id"])
    wo.note(f"💸 Sent ${amt_cents/100:.2f} to your PayPal ({email}).", kind="praise", conn=conn)
    return f"payout {res.get('batch_id')} ({res.get('status')})"


wo.register_executor("paypal_payout", _exec_paypal_payout)


# ── media path → browser URL (served under /store) ───────────────────────────
def _media_url(path):
    if not path:
        return None
    if path.startswith("/store") or path.startswith("http"):
        return path
    for seg in ("/designs/", "/videos/"):
        i = path.find(seg)
        if i != -1:
            return "/store" + path[i:]
    return None


def _designs_url(image_path):
    """Browser URL for a generated design image, resolved to its CURRENT folder.

    A design's file moves pending → approved/rejected as it's reviewed, but the
    generations row keeps the original pending path — so a cached board URL 404s after a
    move. Resolve by filename against the live folders; return None if it's gone entirely
    (so the board skips it rather than emitting a 404)."""
    if not image_path:
        return None
    name = os.path.basename(str(image_path))
    for d in (DESIGNS_PENDING, DESIGNS_APPROVED, DESIGNS_REJECTED):
        if (d / name).exists():
            return f"/store/designs/{d.name}/{name}"
    return None


def _prayer_thumb(conn, payload_raw):
    """Preview image for a creative prayer, resolved to its current folder."""
    try:
        payload = json.loads(payload_raw) if payload_raw else {}
        if payload.get("type") != "image":
            return None
        path = payload.get("path")
        gid = payload.get("gen_id")
        if gid:
            r = conn.execute("SELECT image_path FROM generations WHERE id=?", (gid,)).fetchone()
            if r and r["image_path"]:
                path = r["image_path"]
        return _designs_url(path)
    except Exception:
        return None
