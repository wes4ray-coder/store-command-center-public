"""
The Company — real paid listings on Etsy / Printify.

The one place the Company spends real money and puts real products in public. So
every listing is (a) budget-gated (Etsy's $0.20 draws the treasury) and (b)
ALWAYS reviewed — post_etsy/post_printify never auto-publish, even in budget
mode. The Company does all the work (pick a design → draft the listing → price
it) and queues a prayer; you glance at it and bless. One tap = a live listing.

Reuses the proven internal endpoints (design approve → /api/etsy/publish or
/api/printify/publish) over localhost, so there's no duplicated publish logic.
"""
import json, logging, time
import httpx
from deps import get_conn, get_setting
import world_ops as wo

logger = logging.getLogger("store")
_LOCAL = "http://127.0.0.1:8787"

DEFAULTS = {
    "world_sell_price_cents":   "2499",    # default retail price ($24.99)
    "world_sell_product_type":  "Poster",  # what the generated art is sold as
    "world_sell_auto":          "0",       # autonomously queue listings on a cadence
    "world_sell_channel":       "etsy",    # which channel autonomous listing uses
    "world_sell_interval_min":  "180",     # how often the auto-lister queues one
    "world_sell_revenue_sync":  "1",       # pull real sales into the treasury (closes the loop)
}


def cfg(k):
    return get_setting(k, DEFAULTS.get(k))


def price_cents():
    try:
        return max(100, int(cfg("world_sell_price_cents")))
    except Exception:
        return 2499


# ── pick an unlisted, finished design ────────────────────────────────────────
def _pick_design(conn):
    """Best unlisted design: god-approved status first, then ranked by the
    learned taste model — the shop leads with what god actually likes."""
    rows = conn.execute(
        "SELECT id, prompt FROM designs WHERE (etsy_listing_id IS NULL OR etsy_listing_id='') "
        "AND (printify_id IS NULL OR printify_id='') AND image_path IS NOT NULL "
        "AND image_path!='' ORDER BY (status IN ('approved','published')) DESC, id DESC LIMIT 10").fetchall()
    if not rows:
        return None
    try:
        import world_taste
        if len(rows) > 1 and world_taste.stats(conn)["trained"]:
            return max(rows, key=lambda r: world_taste.score(conn, r["prompt"] or ""))["id"]
    except Exception:
        pass
    return rows[0]["id"]


# ── draft the listing (title/desc/tags) via the proven LLM endpoint ─────────
def _metadata(design_id):
    try:
        r = httpx.post(f"{_LOCAL}/api/designs/{design_id}/generate-listing", timeout=30).json()
        if r.get("ready"):
            return r.get("title"), r.get("description"), r.get("tags")
        tid = r.get("task_id")
        if tid:
            for _ in range(30):
                time.sleep(3)
                ts = httpx.get(f"{_LOCAL}/api/tasks/{tid}", timeout=15).json()
                st = ts.get("status")
                if st == "done":
                    res = ts.get("result") or {}
                    if isinstance(res, str):
                        try:
                            res = json.loads(res)
                        except Exception:
                            res = {}
                    return res.get("title"), res.get("description"), res.get("tags")
                if st in ("error", "cancelled", "not_found"):
                    break
    except Exception:
        logger.exception("listing metadata gen failed")
    return None, None, None


def list_design(channel="etsy", design_id=None):
    """Draft + queue a paid-listing prayer for a design. Returns a status dict."""
    conn = get_conn()
    try:
        did = design_id or _pick_design(conn)
        prompt = None
        if did:
            row = conn.execute("SELECT prompt FROM designs WHERE id=?", (did,)).fetchone()
            prompt = row["prompt"] if row else None
    finally:
        conn.close()
    if not did:
        return {"ok": False, "error": "no unlisted design available — create some art first"}

    title, desc, tags = _metadata(did)
    if not title:
        title = (prompt or "New design")[:80]
        desc = desc or title
        tags = tags or ""

    price = price_cents()
    ptype = cfg("world_sell_product_type")
    kind = "post_printify" if channel == "printify" else "post_etsy"
    wo.pray(kind,
            f"List on {channel.title()}: {title[:40]}",
            detail=f"Design #{did} · ${price/100:.2f} · {ptype}. Real paid listing — review the art, then bless to go live.",
            cost_cents=20,
            payload={"design_id": did, "title": title, "description": desc or title,
                     "tags": tags or "", "price_cents": price, "product_type": ptype},
            agent_name="Storefront")
    return {"ok": True, "design_id": did, "channel": channel, "title": title}


# ── executors: a blessed listing goes live (reusing the real endpoints) ──────
def _publish(conn, prayer, channel):
    try:
        p = json.loads(prayer["payload"] or "{}")
    except Exception:
        p = {}
    did = p.get("design_id")
    if not did:
        return "no design in payload"
    ptype = p.get("product_type") or "Poster"
    try:
        # approve the design so it's publishable (the prayer blessing IS the review)
        httpx.patch(f"{_LOCAL}/api/designs/{did}/approve", json={"product_types": [ptype]}, timeout=20)
        if channel == "etsy":
            r = httpx.post(f"{_LOCAL}/api/etsy/publish", json={
                "design_id": did, "title": (p.get("title") or "")[:140],
                "description": p.get("description") or "", "tags": p.get("tags") or "",
                "price": (p.get("price_cents") or 2499) / 100.0, "product_type": ptype}, timeout=40)
        else:
            r = httpx.post(f"{_LOCAL}/api/printify/publish", json={
                "design_id": did, "title": (p.get("title") or "")[:140],
                "description": p.get("description") or "", "tags": p.get("tags") or "",
                "product_type": ptype, "retail_price_cents": p.get("price_cents") or 2499}, timeout=40)
        if r.status_code >= 400:
            try:
                msg = (r.json() or {}).get("detail") or r.text[:160]
            except Exception:
                msg = r.text[:160]
            wo.note(f"{channel.title()} listing failed for design {did}: {msg}", kind="warning",
                    from_agent=prayer.get("agent_name"), conn=conn)
            return f"{channel} rejected: {msg}"
        wo.note(f"🛍️ Design {did} is going live on {channel.title()}.", kind="praise",
                from_agent=prayer.get("agent_name"), conn=conn)
        return f"listing on {channel}"
    except Exception as e:
        logger.exception("%s publish failed", channel)
        wo.note(f"Tried to list design {did} on {channel.title()} but hit an error ({e}).",
                kind="warning", from_agent=prayer.get("agent_name"), conn=conn)
        return f"error: {e}"


def _exec_post_etsy(conn, prayer):
    return _publish(conn, prayer, "etsy")


def _exec_post_printify(conn, prayer):
    return _publish(conn, prayer, "printify")


def register():
    wo.register_executor("post_etsy", _exec_post_etsy)
    wo.register_executor("post_printify", _exec_post_printify)


register()


# ── revenue ingestion: real sales → treasury (closes the money loop) ──────────
def _revenue_ledgered(conn, source, ref):
    """Has this sale already been recorded? (dedupe by the id stamped in the note.)"""
    return conn.execute(
        "SELECT 1 FROM world_ops_ledger WHERE kind='revenue' AND source=? AND note LIKE ? LIMIT 1",
        (source, f"%#{ref}%")).fetchone() is not None


def _sync_etsy_revenue(conn, client=None):
    """Ledger new Etsy sales (receipts) as revenue. Returns (count, cents). client is
    injectable for tests. Deduped by receipt id; a high-water mark limits the fetch."""
    if client is None:
        try:
            import services
            client = services.build_etsy_client()
        except Exception:
            client = None
    if not client:
        return 0, 0
    try:
        hwm = int(get_setting("world_sell_etsy_rev_hwm", "0") or 0)
    except Exception:
        hwm = 0
    try:
        receipts = client.get_receipts(min_created=hwm)
    except Exception as e:
        logger.warning("etsy revenue sync failed: %s", e)
        return 0, 0
    added, total, maxc = 0, 0, hwm
    for rc in receipts:
        rid = rc.get("receipt_id")
        created = int(rc.get("created") or 0)
        cents = int(rc.get("total_cents") or 0)
        maxc = max(maxc, created)
        if not rid or cents <= 0 or _revenue_ledgered(conn, "etsy", rid):
            continue
        wo._ledger(conn, cents, "revenue", source="etsy", note=f"Etsy sale #{rid}")
        wo.note(f"💰 Etsy sale — ${cents/100:.2f} landed in the treasury.", kind="praise", conn=conn)
        added += 1
        total += cents
    if maxc > hwm:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('world_sell_etsy_rev_hwm',?)", (str(maxc),))
    conn.commit()
    return added, total


def sync_revenue(conn=None, etsy_client=None):
    """Pull REAL sales into the treasury as revenue — the missing half of the money loop.
    Reads Etsy receipts newer than the last high-water mark and ledgers each new one as
    +revenue (deduped by receipt id). Toggle world_sell_revenue_sync (default on). Safe
    no-op if Etsy isn't configured or there are no new sales."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        wo.ensure(conn)
        if cfg("world_sell_revenue_sync") != "1":
            return {"ok": False, "reason": "disabled", "added": 0, "revenue_cents": 0}
        added, cents = _sync_etsy_revenue(conn, etsy_client)
        return {"ok": True, "added": added, "revenue_cents": cents}
    finally:
        if own:
            conn.close()
