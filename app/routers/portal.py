"""Portal — the WordPress / WooCommerce bridge.

Curate items from every corner of the Store (affiliate + software you enter here,
plus live Etsy / Printify / Cults3D listings and your generated media) and push the
ones you pick to example.com:

  • products  → WooCommerce EXTERNAL/affiliate products (Buy button links out)
  • media     → a "Portfolio" Gallery page (generated images/videos as previews)

Nothing goes live without an explicit push. Credentials come from the `settings`
table (wp_url, wp_consumer_key, wp_consumer_secret for products; wp_mcp_url,
wp_mcp_token for media/pages). See app/wc_client.py for the transport details.
"""
from pathlib import Path
from typing import Optional
import json as _json

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import *   # get_conn, get_setting, config (BASE, VIDEOS_DIR, etc.), PrintifyClient, EtsyClient
from wc_client import WooClient, WPMcpClient, WCError

router = APIRouter()

PORTFOLIO_SLUG = "portfolio"
PORTFOLIO_TITLE = "Portfolio"


# ─────────────────────────────────────────────────────────────────────────────
# Client factories (read fresh creds each call so Settings edits apply w/o restart)
# ─────────────────────────────────────────────────────────────────────────────
def _wc() -> WooClient:
    # DB setting (Portal UI) wins; fall back to config/env for pre-seeded deployments.
    url = get_setting("wp_url", "") or WP_URL
    ck = get_setting("wp_consumer_key", "") or WP_CONSUMER_KEY
    cs = get_setting("wp_consumer_secret", "") or WP_CONSUMER_SECRET
    if not (url and ck and cs):
        raise HTTPException(400, "WordPress not configured — set WooCommerce URL + API key "
                                 "in the Portal settings.")
    return WooClient(url, ck, cs)


def _mcp() -> WPMcpClient:
    ep = get_setting("wp_mcp_url", "") or WP_MCP_URL
    tok = get_setting("wp_mcp_token", "") or WP_MCP_TOKEN
    if not (ep and tok):
        raise HTTPException(400, "WordPress MCP not configured (wp_mcp_url / wp_mcp_token).")
    return WPMcpClient(ep, tok)


def _err(e: Exception) -> HTTPException:
    if isinstance(e, HTTPException):
        return e   # already-classified (e.g. 400 "not configured") — don't downgrade to 502
    if isinstance(e, WCError):
        return HTTPException(e.status if 400 <= e.status < 600 else 502, str(e))
    return HTTPException(502, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Connection status
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/api/portal/status")
def portal_status():
    """Connection health + what's configured, for the banner at the top of the tab."""
    url = get_setting("wp_url", "") or WP_URL
    ck = get_setting("wp_consumer_key", "") or WP_CONSUMER_KEY
    cs = get_setting("wp_consumer_secret", "") or WP_CONSUMER_SECRET
    have = {
        "wp_url": url,
        "products_configured": bool(url and ck and cs),
        "media_configured": bool((get_setting("wp_mcp_url") or WP_MCP_URL) and (get_setting("wp_mcp_token") or WP_MCP_TOKEN)),
    }
    out = {**have, "connected": False, "total_products": None, "error": None}
    if not have["products_configured"]:
        out["error"] = "WooCommerce API key not set."
        return out
    try:
        ping = _wc().ping()
        out["connected"] = True
        out["total_products"] = ping.get("total_products")
    except Exception as e:
        out["error"] = str(e)
    return out


class ConfigIn(BaseModel):
    wp_url: Optional[str] = None
    wp_consumer_key: Optional[str] = None
    wp_consumer_secret: Optional[str] = None
    wp_mcp_url: Optional[str] = None
    wp_mcp_token: Optional[str] = None


@router.post("/api/portal/config")
def portal_config(cfg: ConfigIn):
    conn = get_conn()
    for k, v in cfg.dict().items():
        if v is not None:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, v.strip()))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Affiliate / software local catalog (greenfield manual entry)
# ─────────────────────────────────────────────────────────────────────────────
class AffiliateIn(BaseModel):
    kind: str = "affiliate"           # affiliate | software
    title: str
    description: Optional[str] = ""
    price: Optional[str] = ""
    external_url: str
    image_url: Optional[str] = ""
    category: Optional[str] = ""
    tags: Optional[str] = ""
    button_text: Optional[str] = "Buy now"
    program_id: Optional[int] = None  # link to a portal_programs row → auto-append your tag


@router.get("/api/portal/affiliate")
def list_affiliate(kind: Optional[str] = None):
    conn = get_conn()
    if kind:
        rows = conn.execute("SELECT * FROM portal_affiliate WHERE kind=? ORDER BY updated_at DESC", (kind,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM portal_affiliate ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/portal/affiliate")
def create_affiliate(item: AffiliateIn):
    if not item.title.strip() or not item.external_url.strip():
        raise HTTPException(400, "Title and link (external_url) are required.")
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO portal_affiliate (kind,title,description,price,external_url,image_url,category,tags,button_text,program_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (item.kind, item.title.strip(), item.description, item.price, item.external_url.strip(),
         item.image_url, item.category, item.tags, item.button_text or "Buy now", item.program_id))
    conn.commit()
    row = conn.execute("SELECT * FROM portal_affiliate WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@router.patch("/api/portal/affiliate/{item_id}")
def update_affiliate(item_id: int, item: AffiliateIn):
    conn = get_conn()
    exists = conn.execute("SELECT id FROM portal_affiliate WHERE id=?", (item_id,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(404, "Not found")
    conn.execute(
        """UPDATE portal_affiliate SET kind=?,title=?,description=?,price=?,external_url=?,
           image_url=?,category=?,tags=?,button_text=?,program_id=?,updated_at=datetime('now') WHERE id=?""",
        (item.kind, item.title.strip(), item.description, item.price, item.external_url.strip(),
         item.image_url, item.category, item.tags, item.button_text or "Buy now", item.program_id, item_id))
    conn.commit()
    row = conn.execute("SELECT * FROM portal_affiliate WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/portal/affiliate/{item_id}")
def delete_affiliate(item_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM portal_affiliate WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Affiliate PROGRAMS — signup portals + your saved tracking tag per program
# ─────────────────────────────────────────────────────────────────────────────
# Built-in catalog: (pkey, name, ptype, via, signup_url, tag_param, sort).
#   ptype  = 'network'  → an affiliate network/platform you SIGN UP TO directly.
#            'merchant' → a brand you APPLY TO *inside* a network (see `via`).
#   via    = which network(s) host this merchant (verified mid-2026; these change —
#            most retailers don't run their own program). '' for networks.
#   tag_param = URL query param that carries YOUR tag on a plain product link.
#            Only Amazon takes a simple ?tag= append; networks hand out deep-links /
#            SubIDs, so everything else is "" (paste the finished link per product).
_PROGRAM_CATALOG = [
    # ── networks / platforms you actually sign up to ─────────────────────────
    ("amazon",     "Amazon Associates",   "network", "",  "https://affiliate-program.amazon.com/",                    "tag", 10),
    ("impact",     "Impact.com",          "network", "",  "https://impact.com/become-a-partner/",                     "", 11),
    ("cj",         "CJ Affiliate",        "network", "",  "https://signup.cj.com/member/signup/publisher/",           "", 12),
    ("rakuten",    "Rakuten Advertising", "network", "",  "https://rakutenadvertising.com/lp/affiliate-application/", "", 13),
    ("awin",       "Awin",                "network", "",  "https://www.awin.com/us/publishers",                       "", 14),
    ("flexoffers", "FlexOffers",          "network", "",  "https://publishers.flexoffers.com/registration/",          "", 15),
    ("sovrn",      "Sovrn Commerce",      "network", "",  "https://www.sovrn.com/commerce-affiliate-marketing/",      "", 16),
    ("shareasale", "ShareASale",          "network", "",  "https://account.shareasale.com/newsignup.cfm",             "", 17),
    # ── retailers — apply INSIDE the network shown in `via` ──────────────────
    ("walmart",    "Walmart",             "merchant", "Impact",                       "https://affiliates.walmart.com/",   "", 30),
    ("target",     "Target Partners",     "merchant", "Impact",                       "https://partners.target.com/",      "", 31),
    ("homedepot",  "The Home Depot",      "merchant", "Impact",                       "https://www.homedepot.com/c/affiliate_program", "", 32),
    ("bestbuy",    "Best Buy",            "merchant", "Impact",                       "https://www.bestbuy.com/site/partnerships/best-buy-affiliate-program/pcmcat198500050002.c?id=pcmcat198500050002", "", 33),
    ("lowes",      "Lowe's",              "merchant", "CJ Affiliate · FlexOffers · Sovrn", "https://www.flexoffers.com/affiliate-programs/lowes-affiliate-program/", "", 34),
    ("newegg",     "Newegg",              "merchant", "Rakuten (moved from CJ)",      "https://rakutenadvertising.com/lp/affiliate-application/", "", 35),
    ("etsy",       "Etsy",                "merchant", "Awin → Rakuten (migrating)", "https://www.etsy.com/affiliates",  "", 36),
    # ── maker / 3D / print-on-demand — mostly their own direct programs ──────
    ("printful",   "Printful",            "merchant", "Direct",  "https://www.printful.com/affiliate",             "", 50),
    ("printify",   "Printify",            "merchant", "Direct",  "https://printify.com/affiliates/",               "", 51),
    ("displate",   "Displate",            "merchant", "Direct",  "https://displate.com/affiliate-program/",        "", 52),
    ("creality",   "Creality",            "merchant", "Direct",  "https://www.creality.com/pages/affiliate",       "", 53),
    ("elegoo",     "Elegoo",              "merchant", "Direct",  "https://www.elegoo.com/pages/affiliate-program", "", 54),
]


def _seed_programs():
    """Upsert the built-in catalog. Inserts new programs and REFRESHES catalog-owned
    fields on existing built-in rows (so corrected links/networks propagate), while
    preserving anything the user set (tag_value, account_id, notes, signed_up)."""
    conn = get_conn()
    for pkey, name, ptype, via, url, tag_param, sort in _PROGRAM_CATALOG:
        net_label = "Network" if ptype == "network" else (via or "Direct")
        conn.execute(
            """INSERT OR IGNORE INTO portal_programs (pkey,name,network,signup_url,tag_param,sort,is_custom,ptype,via)
               VALUES (?,?,?,?,?,?,0,?,?)""",
            (pkey, name, net_label, url, tag_param, sort, ptype, via))
        conn.execute(
            """UPDATE portal_programs SET name=?,network=?,signup_url=?,tag_param=?,sort=?,ptype=?,via=?
               WHERE pkey=? AND is_custom=0""",
            (name, net_label, url, tag_param, sort, ptype, via, pkey))
    conn.commit()
    conn.close()


def _apply_program_tag(url: str, program_id) -> str:
    """Append the saved affiliate tag for `program_id` to `url` if the program uses a
    simple query-param tag (e.g. Amazon ?tag=) and the URL doesn't already carry it.
    Networks with deep-links (tag_param="") are returned unchanged — the user pastes
    the finished deep-link themselves."""
    if not program_id or not url:
        return url
    conn = get_conn()
    row = conn.execute("SELECT tag_param, tag_value FROM portal_programs WHERE id=?", (program_id,)).fetchone()
    conn.close()
    if not row:
        return url
    param = (row["tag_param"] or "").strip()
    val = (row["tag_value"] or "").strip()
    if not param or not val:
        return url
    if f"{param}=" in url:           # already tagged — don't double-append
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{param}={val}"


class ProgramIn(BaseModel):
    name: Optional[str] = None
    network: Optional[str] = None
    signup_url: Optional[str] = None
    tag_param: Optional[str] = None
    tag_value: Optional[str] = None
    account_id: Optional[str] = None
    notes: Optional[str] = None
    signed_up: Optional[int] = None


@router.get("/api/portal/programs")
def list_programs():
    _seed_programs()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM portal_programs ORDER BY sort, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/portal/programs")
def create_program(p: ProgramIn):
    if not (p.name or "").strip():
        raise HTTPException(400, "Program name is required.")
    import re
    base = re.sub(r"[^a-z0-9]+", "-", (p.name or "").lower()).strip("-") or "program"
    conn = get_conn()
    pkey = base
    n = 1
    while conn.execute("SELECT 1 FROM portal_programs WHERE pkey=?", (pkey,)).fetchone():
        n += 1; pkey = f"{base}-{n}"
    cur = conn.execute(
        """INSERT INTO portal_programs (pkey,name,network,signup_url,tag_param,tag_value,account_id,notes,signed_up,sort,is_custom)
           VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
        (pkey, p.name.strip(), p.network or "Custom", p.signup_url or "", p.tag_param or "",
         p.tag_value or "", p.account_id or "", p.notes or "", int(p.signed_up or 0), 200))
    conn.commit()
    row = conn.execute("SELECT * FROM portal_programs WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@router.patch("/api/portal/programs/{pid}")
def update_program(pid: int, p: ProgramIn):
    conn = get_conn()
    row = conn.execute("SELECT * FROM portal_programs WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Program not found")
    fields, vals = [], []
    for k in ("name", "network", "signup_url", "tag_param", "tag_value", "account_id", "notes", "signed_up"):
        v = getattr(p, k)
        if v is not None:
            fields.append(f"{k}=?")
            vals.append(int(v) if k == "signed_up" else v)
    # auto-flag signed_up when a tag is entered
    if p.tag_value and (p.signed_up is None):
        fields.append("signed_up=?"); vals.append(1)
    if fields:
        vals.append(pid)
        conn.execute(f"UPDATE portal_programs SET {','.join(fields)},updated_at=datetime('now') WHERE id=?", vals)
        conn.commit()
    row = conn.execute("SELECT * FROM portal_programs WHERE id=?", (pid,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/portal/programs/{pid}")
def delete_program(pid: int):
    conn = get_conn()
    row = conn.execute("SELECT is_custom FROM portal_programs WHERE id=?", (pid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Program not found")
    if not row["is_custom"]:
        conn.close()
        raise HTTPException(400, "Built-in programs can't be deleted (clear your tag instead).")
    conn.execute("DELETE FROM portal_programs WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Source aggregation → unified pushable items
# item shape: {uid, source, kind, title, description, price, external_url,
#              image_url, local_path, category, tags, pushed, wp_link}
# ─────────────────────────────────────────────────────────────────────────────
def _pushed_map() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT source, source_ref, kind, wp_id, wp_link FROM portal_pushes").fetchall()
    conn.close()
    return {f"{r['source']}:{r['source_ref']}": dict(r) for r in rows}


def _mark(item: dict, pushed: dict) -> dict:
    p = pushed.get(f"{item['source']}:{item['uid']}")
    item["pushed"] = bool(p)
    item["wp_link"] = p["wp_link"] if p else None
    item["wp_id"] = p["wp_id"] if p else None
    return item


def _etsy_valid_token(s: dict) -> str:
    """Return a fresh Etsy access token, refreshing + persisting it if expired/expiring
    (same pattern as dashboard.py). Etsy tokens live ~1h, so this is routine."""
    import time
    from etsy_client import refresh_access_token
    key = s.get("etsy_key", ""); token = s.get("etsy_access_token", "")
    ref = s.get("etsy_refresh_token", ""); secret = s.get("etsy_shared_secret", "")
    exp = int(s.get("etsy_token_expires", "0") or 0)
    if token and ref and time.time() >= exp - 120:
        tokens = refresh_access_token(key, ref, client_secret=secret or None)
        token = tokens["access_token"]
        new_exp = int(time.time()) + tokens.get("expires_in", 3600)
        c = get_conn()
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("etsy_access_token", _enc(token)))
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("etsy_token_expires", str(new_exp)))
        if tokens.get("refresh_token"):
            c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("etsy_refresh_token", _enc(tokens["refresh_token"])))
        c.commit(); c.close()
    return token


def _etsy_items() -> list:
    s = _get_etsy_settings()
    key = s.get("etsy_key"); shop = s.get("etsy_shop_id"); secret = s.get("etsy_shared_secret", "")
    if not (key and s.get("etsy_access_token") and shop):
        raise HTTPException(400, "Etsy not connected — add credentials in Settings.")
    token = _etsy_valid_token(s)
    # Use EtsyClient's headers (x-api-key must be 'keystring:shared_secret', else 403),
    # with includes=Images so listing thumbnails come back inline.
    from etsy_client import EtsyClient, ETSY_BASE
    client = EtsyClient(key, token, shop, shared_secret=secret)
    r = httpx.get(
        f"{ETSY_BASE}/application/shops/{shop}/listings",
        params={"state": "active", "limit": 100, "includes": "Images"},
        headers=client._headers(), timeout=30)
    r.raise_for_status()
    out = []
    for L in r.json().get("results", []):
        price = L.get("price") or {}
        amt = price.get("amount"); div = price.get("divisor") or 100
        dollars = f"{amt/div:.2f}" if isinstance(amt, (int, float)) else ""
        imgs = L.get("images") or []
        img = imgs[0].get("url_570xN") or imgs[0].get("url_fullxfull") if imgs else ""
        out.append({
            "uid": str(L.get("listing_id")), "source": "etsy", "kind": "product",
            "title": L.get("title", ""), "description": _strip(L.get("description", "")),
            "price": dollars, "external_url": L.get("url", ""),
            "image_url": img, "local_path": None,
            "category": "Etsy", "tags": ",".join(L.get("tags", []) or []),
        })
    return out


def _printify_items() -> list:
    client = _get_printify()
    data = client.get_products(limit=50)
    out = []
    for p in data.get("data", []):
        variants = p.get("variants") or []
        prices = [v.get("price") for v in variants if v.get("price")]
        dollars = f"{min(prices)/100:.2f}" if prices else ""
        imgs = p.get("images") or []
        img = imgs[0].get("src") if imgs else ""
        ext = (p.get("external") or {}).get("handle", "")   # set once published to a sales channel
        out.append({
            "uid": str(p.get("id")), "source": "printify", "kind": "product",
            "title": p.get("title", ""), "description": _strip(p.get("description", "")),
            "price": dollars, "external_url": ext, "image_url": img, "local_path": None,
            "category": "Printify", "tags": ",".join(p.get("tags", []) or []),
        })
    return out


def _cults3d_items() -> list:
    from cults import cults_query, CultsError
    try:
        data = cults_query("""{ me { creations(limit: 100) {
            name url price { cents currency } illustrationImageUrl } } }""")
    except CultsError as e:
        raise HTTPException(502, f"Cults3D: {e}")
    me = data.get("me") or {}
    out = []
    for c in me.get("creations") or []:
        price = c.get("price") or {}
        cents = price.get("cents")
        dollars = f"{cents/100:.2f}" if isinstance(cents, (int, float)) else ""
        out.append({
            "uid": c.get("url", ""), "source": "cults3d", "kind": "product",
            "title": c.get("name", ""), "description": "",
            "price": dollars, "external_url": c.get("url", ""),
            "image_url": c.get("illustrationImageUrl", ""), "local_path": None,
            "category": "3D Models", "tags": "",
        })
    return out


def _affiliate_items(kind: str) -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM portal_affiliate WHERE kind=? ORDER BY updated_at DESC", (kind,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        raw_url = d.get("external_url") or ""
        tagged = _apply_program_tag(raw_url, d.get("program_id"))
        out.append({
            "uid": str(d["id"]), "source": kind, "kind": "product",
            "title": d["title"], "description": d.get("description") or "",
            "price": d.get("price") or "", "external_url": tagged,
            "image_url": d.get("image_url") or "", "local_path": None,
            "category": d.get("category") or ("Software" if kind == "software" else "Affiliate"),
            "tags": d.get("tags") or "", "button_text": d.get("button_text") or "Buy now",
            "program_id": d.get("program_id"),
        })
    return out


def _resolve_local(path: str, *subdirs: str) -> Optional[Path]:
    """Best-effort resolve a stored relative/absolute media path to a real file."""
    if not path:
        return None
    p = Path(path)
    candidates = [p]
    if not p.is_absolute():
        candidates += [BASE / path]
        for sd in subdirs:
            candidates.append(BASE / sd / p.name)
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            pass
    return None


def _image_items() -> list:
    """Generated images (designs that have a produced image) → portfolio previews."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, image_path, prompt, status FROM designs "
        "WHERE image_path IS NOT NULL AND image_path != '' "
        "ORDER BY created_at DESC LIMIT 200").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        parts = str(d["image_path"]).split("/")
        fn = parts[-1]
        sub = parts[-2] if len(parts) > 1 else "approved"
        out.append({
            "uid": str(d["id"]), "source": "image", "kind": "portfolio",
            "title": (d.get("prompt") or fn)[:80], "description": d.get("prompt") or "",
            "price": "", "external_url": "",
            "image_url": f"/designs/{sub}/{fn}",   # frontend prefixes API base
            "local_path": d["image_path"], "category": "Gallery", "tags": "",
        })
    return out


def _video_items() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, video_path, prompt, status FROM videos "
        "WHERE status='done' AND video_path IS NOT NULL AND video_path != '' "
        "ORDER BY created_at DESC LIMIT 200").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        fn = str(d["video_path"]).split("/")[-1]
        out.append({
            "uid": str(d["id"]), "source": "video", "kind": "portfolio",
            "title": (d.get("prompt") or fn)[:80], "description": d.get("prompt") or "",
            "price": "", "external_url": "",
            "image_url": f"/videos/{fn}", "local_path": d["video_path"],
            "category": "Gallery", "tags": "",
        })
    return out


_SOURCES = {
    "affiliate": lambda: _affiliate_items("affiliate"),
    "software":  lambda: _affiliate_items("software"),
    "etsy":      _etsy_items,
    "printify":  _printify_items,
    "cults3d":   _cults3d_items,
    "image":     _image_items,
    "video":     _video_items,
}


@router.get("/api/portal/items")
def portal_items(source: str):
    """Aggregated, curate-ready items for one source, each flagged if already pushed."""
    fn = _SOURCES.get(source)
    if not fn:
        raise HTTPException(400, f"Unknown source '{source}'.")
    try:
        items = fn()
    except HTTPException:
        raise
    except Exception as e:
        raise _err(e)
    pushed = _pushed_map()
    items = [_mark(it, pushed) for it in items]
    return {"source": source, "count": len(items), "items": items}


def _strip(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html or "").strip()[:500]


# ─────────────────────────────────────────────────────────────────────────────
# PUSH — products (external/affiliate) and portfolio (media gallery)
# ─────────────────────────────────────────────────────────────────────────────
class PushItem(BaseModel):
    uid: str
    source: str
    title: str
    external_url: Optional[str] = ""
    price: Optional[str] = ""
    description: Optional[str] = ""
    image_url: Optional[str] = ""
    local_path: Optional[str] = ""
    category: Optional[str] = ""
    tags: Optional[str] = ""
    button_text: Optional[str] = "Buy now"


class PushIn(BaseModel):
    items: list[PushItem]
    status: str = "publish"     # publish | draft


def _record_push(source: str, uid: str, kind: str, wp_id, wp_link: str, title: str):
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO portal_pushes (source,source_ref,kind,wp_id,wp_link,title,pushed_at)
           VALUES (?,?,?,?,?,?,datetime('now'))""",
        (source, uid, kind, wp_id, wp_link, title))
    conn.commit()
    conn.close()


@router.post("/api/portal/push")
def portal_push(body: PushIn):
    """Create WooCommerce external/affiliate products for the selected items."""
    if not body.items:
        raise HTTPException(400, "No items selected.")
    wc = _wc()
    results = []
    cat_cache: dict[str, int] = {}
    for it in body.items:
        try:
            if not it.external_url:
                raise WCError("Missing Buy-button link (external_url).", 400)
            cat_ids = []
            if it.category:
                if it.category not in cat_cache:
                    cat_cache[it.category] = wc.ensure_category(it.category)
                if cat_cache[it.category]:
                    cat_ids.append(cat_cache[it.category])
            tags = [t.strip() for t in (it.tags or "").split(",") if t.strip()][:15]
            prod = wc.create_external_product(
                name=it.title, external_url=it.external_url,
                regular_price=it.price or "", description=it.description or "",
                button_text=it.button_text or "Buy now",
                image_urls=[it.image_url] if it.image_url else None,
                category_ids=cat_ids or None, tags=tags or None, status=body.status)
            link = prod.get("permalink", "")
            _record_push(it.source, it.uid, "product", prod.get("id"), link, it.title)
            results.append({"uid": it.uid, "source": it.source, "ok": True,
                            "wp_id": prod.get("id"), "wp_link": link})
        except Exception as e:
            msg = str(e)
            results.append({"uid": it.uid, "source": it.source, "ok": False, "error": msg})
    ok = sum(1 for r in results if r["ok"])
    return {"pushed": ok, "failed": len(results) - ok, "results": results}


@router.post("/api/portal/portfolio")
def portal_portfolio(body: PushIn):
    """Upload selected generated media to WP and (re)build the Portfolio Gallery page."""
    if not body.items:
        raise HTTPException(400, "No media selected.")
    mcp = _mcp()
    uploaded = []
    results = []
    for it in body.items:
        try:
            local = _resolve_local(it.local_path or "", "designs", "designs/approved",
                                   "designs/pending", "videos")
            if not local:
                raise WCError(f"File not found on disk: {it.local_path}", 400)
            data = local.read_bytes()
            att = mcp.upload_media_base64(local.name, data, title=it.title, alt_text=it.title)
            src = att.get("source_url") or att.get("url") or att.get("guid", "")
            mid = att.get("id")
            uploaded.append({"src": src, "title": it.title,
                             "is_video": local.suffix.lower() in (".mp4", ".webm", ".mov")})
            _record_push(it.source, it.uid, "portfolio", mid, src, it.title)
            results.append({"uid": it.uid, "source": it.source, "ok": True, "wp_id": mid, "src": src})
        except Exception as e:
            results.append({"uid": it.uid, "source": it.source, "ok": False, "error": str(e)})

    # Rebuild the gallery page to include ALL portfolio items ever uploaded.
    page_link = None
    try:
        page_link = _rebuild_portfolio_page(mcp)
    except Exception as e:
        logger.warning("portfolio page rebuild failed: %s", e)
    ok = sum(1 for r in results if r["ok"])
    return {"uploaded": ok, "failed": len(results) - ok, "page": page_link, "results": results}


def _rebuild_portfolio_page(mcp: WPMcpClient) -> Optional[str]:
    """Assemble a simple responsive gallery from every portfolio push and upsert the page."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT wp_link, title, source FROM portal_pushes WHERE kind='portfolio' "
        "ORDER BY pushed_at DESC").fetchall()
    conn.close()
    tiles = []
    for r in rows:
        src = r["wp_link"] or ""
        title = esc_html(r["title"] or "")
        if not src:
            continue
        if r["source"] == "video":
            tiles.append(f'<figure style="margin:0"><video src="{src}" controls '
                         f'style="width:100%;border-radius:10px"></video>'
                         f'<figcaption>{title}</figcaption></figure>')
        else:
            tiles.append(f'<figure style="margin:0"><img src="{src}" alt="{title}" loading="lazy" '
                         f'style="width:100%;border-radius:10px"><figcaption>{title}</figcaption></figure>')
    content = (
        '<p>Generated artwork and video previews.</p>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px">'
        + "".join(tiles) + "</div>")
    existing = mcp.find_page_by_slug(PORTFOLIO_SLUG)
    if existing and existing.get("id"):
        mcp.update_page(existing["id"], content, title=PORTFOLIO_TITLE)
        return existing.get("link") or existing.get("permalink")
    created = mcp.create_page(PORTFOLIO_TITLE, content, slug=PORTFOLIO_SLUG, status="publish")
    return created.get("link") or created.get("permalink") or created.get("url")


def esc_html(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ─────────────────────────────────────────────────────────────────────────────
# What's live on WordPress
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/api/portal/wp-products")
def wp_products(per_page: int = 50):
    """WooCommerce products for the Portal tab. Cached ~30s — this hits example.com
    over HTTPS, which is the main reason the tab felt slow on every open. Busted on
    delete/push below."""
    from cache import cached

    def fetch():
        try:
            prods = _wc().list_products(per_page=per_page)
        except Exception as e:
            raise _err(e)
        return [{
            "id": p.get("id"), "name": p.get("name"), "type": p.get("type"),
            "status": p.get("status"), "price": p.get("price"),
            "permalink": p.get("permalink"), "external_url": p.get("external_url"),
            "image": (p.get("images") or [{}])[0].get("src", ""),
        } for p in prods]

    slim = cached(f"portal:wp-products:{per_page}", 30, fetch)
    return {"count": len(slim), "products": slim}


@router.delete("/api/portal/wp-products/{pid}")
def wp_delete_product(pid: int):
    try:
        _wc().delete_product(pid, force=True)
    except Exception as e:
        raise _err(e)
    conn = get_conn()
    conn.execute("DELETE FROM portal_pushes WHERE kind='product' AND wp_id=?", (pid,))
    conn.commit()
    conn.close()
    from cache import invalidate_prefix
    invalidate_prefix("portal:wp-products:")   # list changed → drop cached pages
    return {"ok": True}
