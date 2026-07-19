"""Profit & Loss (margin) engine.

The ONLY live sales channel is Printify → Etsy: print-on-demand products listed on
Etsy and fulfilled by Printify. The store's own Etsy API is unapproved (403), so we
DON'T use it here. Printify's orders API, however, already knows about every Etsy
order it fulfils AND its production/shipping cost, so it is the primary source.

Per real sale the economics are:
    net  =  revenue (Etsy sale price)  −  Printify fulfilment cost  −  Etsy fees(est.)

Etsy fees can't be read from Printify, so we ESTIMATE them from a configurable fee
model (transaction % + payment-processing % + flat processing + flat listing). The
rates live in the settings table (keys below) so they're tunable, not magic numbers.

`summary()` NEVER raises. Zero sales — or Printify being unreachable/unconfigured —
is a normal "ready" state that returns a zero summary with an explanatory `note`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from db import get_conn
from printify import PRINTIFY_API

log = logging.getLogger("store")

# ── Fee model defaults (Etsy's published rates, 2026) ─────────────────────────
# All configurable via the settings table / PATCH /api/settings; these are only the
# fallbacks used when a key isn't set. Percentages are whole-number percents.
PNL_FEE_DEFAULTS: dict[str, float] = {
    "pnl_etsy_txn_pct":              6.5,   # transaction fee on item price (+ shipping)
    "pnl_etsy_processing_pct":       3.0,   # payment-processing percentage
    "pnl_etsy_processing_flat_cents": 25,   # payment-processing flat, per order
    "pnl_etsy_listing_flat_cents":    20,   # listing fee, per sale
}

# How many orders (pages) to pull before we stop — plenty of headroom for a new shop.
_PAGE_LIMIT = 50
_MAX_PAGES = 5
_HTTP_TIMEOUT = 8  # short — a dead Printify must not hang the P&L panel


def _settings() -> dict:
    try:
        conn = get_conn()
        rows = conn.execute("SELECT key,value FROM settings").fetchall()
        conn.close()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def _fee_model(s: dict) -> dict:
    """Resolve the configurable fee rates, falling back to PNL_FEE_DEFAULTS."""
    out = {}
    for k, default in PNL_FEE_DEFAULTS.items():
        raw = s.get(k, None)
        try:
            out[k] = float(raw) if raw not in (None, "") else float(default)
        except (TypeError, ValueError):
            out[k] = float(default)
    return out


def _printify_creds(s: dict) -> tuple[str, str]:
    """(key, shop_id) from settings, decrypted, with env fallback. ('','') if absent."""
    key = shop = ""
    try:
        from crypto import dec_secrets as _dec_secrets
        s = _dec_secrets(dict(s))
    except Exception:
        pass
    key = s.get("printify_key") or ""
    shop = s.get("printify_shop_id") or ""
    if not key or not shop:
        try:
            from config import PRINTIFY_API_KEY, PRINTIFY_SHOP_ID
            key = key or (PRINTIFY_API_KEY or "")
            shop = shop or (PRINTIFY_SHOP_ID or "")
        except Exception:
            pass
    return key, shop


def _parse_dt(raw) -> datetime | None:
    """Printify timestamps look like '2026-07-18 13:24:28+00:00' (also ISO 'T')."""
    if not raw:
        return None
    txt = str(raw).strip().replace(" ", "T", 1)
    for candidate in (txt, txt.split("+")[0], txt.split(".")[0]):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _period_start(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if period == "30d":
        return now - timedelta(days=30)
    if period == "mtd":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None  # 'all'


def _fetch_orders(key: str, shop: str) -> list:
    """Pull orders from Printify (paginated). Returns [] on any failure."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "StoreCommandCenter/1.0",
    }
    orders: list = []
    with httpx.Client(timeout=_HTTP_TIMEOUT, headers=headers) as c:
        for page in range(1, _MAX_PAGES + 1):
            url = f"{PRINTIFY_API}/shops/{shop}/orders.json?limit={_PAGE_LIMIT}&page={page}"
            r = c.get(url)
            r.raise_for_status()
            data = r.json()
            batch = data if isinstance(data, list) else (data.get("data") or [])
            if not batch:
                break
            orders.extend(batch)
            # Stop when we've drained the last page.
            last_page = (data.get("last_page") if isinstance(data, dict) else None)
            if last_page is not None and page >= last_page:
                break
            if len(batch) < _PAGE_LIMIT:
                break
    return orders


def _order_econ(o: dict, fees: dict) -> dict:
    """Per-order {revenue, printify_cost, etsy_fees, net, units, title, ...} in cents."""
    line_items = o.get("line_items") or []

    # Revenue = what the customer paid for goods. Prefer the order total; fall back to
    # summing each line item's retail price × quantity.
    revenue = o.get("total_price")
    if not isinstance(revenue, (int, float)) or revenue <= 0:
        revenue = sum(
            int((li.get("metadata") or {}).get("price") or 0) * int(li.get("quantity") or 1)
            for li in line_items
        )
    revenue = int(revenue or 0)

    # Printify's charge to us = production cost + fulfilment shipping across line items.
    cost = 0
    units = 0
    for li in line_items:
        qty = int(li.get("quantity") or 1)
        units += qty
        cost += int(li.get("cost") or 0)
        cost += int(li.get("shipping_cost") or 0)

    # Etsy fees (estimated) — applied on the revenue.
    etsy_fees = int(round(
        revenue * (fees["pnl_etsy_txn_pct"] / 100.0)
        + revenue * (fees["pnl_etsy_processing_pct"] / 100.0)
        + fees["pnl_etsy_processing_flat_cents"]
        + fees["pnl_etsy_listing_flat_cents"]
    )) if revenue else 0

    net = revenue - cost - etsy_fees

    # A representative product label for the order.
    first = line_items[0] if line_items else {}
    meta = first.get("metadata") or {}
    title = meta.get("title") or first.get("product_id") or "Unknown product"
    product_id = first.get("product_id") or title

    return {
        "id": o.get("id"),
        "product_id": product_id,
        "title": title,
        "units": units,
        "revenue_cents": revenue,
        "cost_cents": cost,
        "fees_cents": etsy_fees,
        "net_cents": net,
        "status": o.get("status") or "",
        "date": (o.get("created_at") or ""),
    }


def _zero(period: str, fees: dict, note: str) -> dict:
    return {
        "period": period,
        "orders": 0,
        "revenue_cents": 0,
        "cost_cents": 0,
        "fees_cents": 0,
        "net_cents": 0,
        "margin_pct": 0.0,
        "currency": "USD",
        "fees_model": fees,
        "by_product": [],
        "recent": [],
        "note": note,
    }


def summary(period: str = "all") -> dict:
    """Aggregate P&L for the given period. Never raises.

    period: 'all' | '30d' | 'mtd'. Returns a dict with the shape documented in
    _zero() plus populated aggregates when orders exist.
    """
    period = period if period in ("all", "30d", "mtd") else "all"
    s = _settings()
    fees = _fee_model(s)

    key, shop = _printify_creds(s)
    if not key or not shop:
        return _zero(period, fees,
                     "Printify isn't connected yet — add your API key & shop ID in "
                     "Settings and this lights up on your first Etsy order.")

    try:
        raw_orders = _fetch_orders(key, shop)
    except Exception as e:  # network, auth, plan-not-allowed, etc. — all non-fatal
        log.info("pnl: Printify orders fetch failed: %s", e)
        return _zero(period, fees,
                     "Couldn't reach Printify just now — showing zero. This will "
                     "populate automatically once orders come through.")

    start = _period_start(period)
    econ = []
    for o in raw_orders:
        dt = _parse_dt(o.get("created_at"))
        if start is not None and dt is not None and dt < start:
            continue
        econ.append(_order_econ(o, fees))

    if not econ:
        return _zero(period, fees,
                     "No sales yet — this lights up on your first Etsy order. "
                     "5 products are live.")

    revenue = sum(e["revenue_cents"] for e in econ)
    cost = sum(e["cost_cents"] for e in econ)
    fee_total = sum(e["fees_cents"] for e in econ)
    net = revenue - cost - fee_total
    margin_pct = round((net / revenue) * 100.0, 1) if revenue else 0.0

    # By-product rollup.
    prod: dict = {}
    for e in econ:
        p = prod.setdefault(e["product_id"], {
            "product_id": e["product_id"], "title": e["title"],
            "orders": 0, "units": 0,
            "revenue_cents": 0, "cost_cents": 0, "fees_cents": 0, "net_cents": 0,
        })
        p["orders"] += 1
        p["units"] += e["units"]
        p["revenue_cents"] += e["revenue_cents"]
        p["cost_cents"] += e["cost_cents"]
        p["fees_cents"] += e["fees_cents"]
        p["net_cents"] += e["net_cents"]
    by_product = sorted(prod.values(), key=lambda p: p["revenue_cents"], reverse=True)

    # Most-recent orders first.
    def _key(e):
        dt = _parse_dt(e["date"])
        return dt or datetime.min.replace(tzinfo=timezone.utc)
    recent = sorted(econ, key=_key, reverse=True)[:15]

    return {
        "period": period,
        "orders": len(econ),
        "revenue_cents": revenue,
        "cost_cents": cost,
        "fees_cents": fee_total,
        "net_cents": net,
        "margin_pct": margin_pct,
        "currency": "USD",
        "fees_model": fees,
        "by_product": by_product,
        "recent": recent,
        "note": "",
    }
