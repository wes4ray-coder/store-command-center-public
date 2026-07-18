"""resell routes."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from starlette.concurrency import run_in_threadpool
from deps import *
from services import *

router = APIRouter()


def _resell_llm(job, desc, model, wait=120):
    """Run a resell LLM/vision call THROUGH the orchestrator queue instead of hitting
    LM Studio directly — so it appears in the unified queue and never races the orch's
    GPU model management (which is the single authority for loading models). priority=0
    because the user is waiting on the response. Returns the job's result or None."""
    tid = orch.submit_llm(job, desc, model=model, priority=0)
    end = time.time() + wait
    while time.time() < end:
        p = orch.poll(tid)
        if p["status"] == "done":
            return p["result"]
        if p["status"] in ("error", "cancelled", "not_found"):
            return None
        time.sleep(0.4)
    orch.cancel(tid)
    return None


@router.post("/api/resell/analyze")
async def resell_analyze(file: UploadFile = File(...), description: str = Form("")):
    """Accept an image upload, call Gemma 4 vision, return item analysis."""
    ext = Path(file.filename or "item.jpg").suffix.lower()
    if ext not in IMAGE_EXTS:
        raise HTTPException(400, "Unsupported file type. Upload a JPG, PNG, or WebP image.")

    # Save upload
    safe_name = f"resell_{int(time.time())}_{random.randint(1000,9999)}{ext}"
    dest = RESELL_UPLOADS / safe_name
    content = await file.read()
    dest.write_bytes(content)

    # Encode for vision model
    b64 = base64.b64encode(content).decode()
    mime = mimetypes.guess_type(str(dest))[0] or "image/jpeg"
    data_url = f"data:{mime};base64,{b64}"

    # Call Gemma 4 vision via LM Studio
    try:
        seller_context = f"Seller says: {description.strip()}" if description.strip() else ""
        analyze_prompt = get_prompt('resell_analyze').format(seller_context=seller_context)
        payload = {
            "model": "google/gemma-4-12b-qat",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text",      "text": analyze_prompt},
                    ],
                }
            ],
            "temperature": 0.3,
            "max_tokens": 600,
        }
        def _job():
            r = httpx.post(f"{LMSTUDIO_URL}/chat/completions", json=payload,
                           headers=_llm_headers(), timeout=90)
            r.raise_for_status()
            return r.json()
        raw = await run_in_threadpool(_resell_llm, _job, "resell:analyze",
                                      "google/gemma-4-12b-qat")
        if raw is None:
            raise RuntimeError("vision analysis job failed or timed out")
        raw_text = (raw["choices"][0]["message"].get("content") or
                    raw["choices"][0]["message"].get("reasoning_content") or "{}").strip()
        # Strip possible markdown fences
        if raw_text.startswith("```"):
            raw_text = "\n".join(raw_text.split("\n")[1:])
            raw_text = raw_text.rstrip("`").strip()
        analysis = json.loads(raw_text)
    except Exception as ex:
        logger.error("Resell analyze error: %s", ex)
        analysis = {
            "title": Path(file.filename or "Item").stem.replace("_", " ").title(),
            "category": "Other",
            "condition_guess": "Good",
            "description": "Item in good condition. See photos for details.",
            "price_low": 5.0,
            "price_fair": 10.0,
            "price_high": 20.0,
            "key_features": [],
        }

    return {
        "image_path": f"resell_uploads/{safe_name}",
        **analysis,
    }

@router.post("/api/resell/scan-directory")
def resell_scan_directory(body: dict):
    """List image files in a local directory for batch resell."""
    scan_path = Path(body.get("path", ""))
    if not scan_path.exists() or not scan_path.is_dir():
        raise HTTPException(400, f"Directory not found: {scan_path}")
    images = []
    for f in sorted(scan_path.iterdir()):
        if f.suffix.lower() in IMAGE_EXTS:
            images.append({
                "path": str(f),
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
    return {"images": images[:100]}  # cap at 100

@router.get("/api/resell/listings")
def resell_list(status: str = ""):
    conn = get_conn()
    q = """
        SELECT rl.*,
               COALESCE(rp.image_path, rl.image_path) AS primary_photo
        FROM resell_listings rl
        LEFT JOIN resell_listing_images rp
               ON rp.listing_id = rl.id AND rp.is_primary = 1
    """
    if status:
        rows = conn.execute(q + "WHERE rl.status=? ORDER BY rl.created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute(q + "ORDER BY rl.created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.post("/api/resell/listings")
def resell_create(body: dict):
    conn = get_conn()
    pay = body.get("payment_methods", ["cash"])
    cur = conn.execute(
        """INSERT INTO resell_listings
           (image_path, title, description, condition, category,
            asking_price, min_accept_price, ai_price_min, ai_price_max,
            ai_analysis, notes, price_mode, shipping_policy,
            will_ship_min_price, payment_methods,
            seller_description, why_selling, whats_included, known_defects, tags)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            body.get("image_path"),
            body.get("title", "Untitled Item"),
            body.get("description"),
            body.get("condition", "Good"),
            body.get("category"),
            body.get("asking_price"),
            body.get("min_accept_price"),
            body.get("ai_price_min"),
            body.get("ai_price_max"),
            json.dumps(body.get("ai_analysis", {})),
            body.get("notes"),
            body.get("price_mode", "obo"),
            body.get("shipping_policy", "pickup_only"),
            body.get("will_ship_min_price", 50.0),
            json.dumps(pay) if isinstance(pay, list) else pay,
            body.get("seller_description"),
            body.get("why_selling"),
            body.get("whats_included"),
            body.get("known_defects"),
            body.get("tags"),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM resell_listings WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)

@router.get("/api/resell/listings/{lid}")
def resell_get(lid: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Listing not found")
    return dict(row)

@router.patch("/api/resell/listings/{lid}")
def resell_update(lid: int, body: dict):
    conn = get_conn()
    row = conn.execute("SELECT id FROM resell_listings WHERE id=?", (lid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Listing not found")
    allowed = {"title","description","condition","category","asking_price","status","notes","platforms",
               "min_accept_price","price_mode","shipping_policy","will_ship_min_price","payment_methods",
               "seller_description","why_selling","whats_included","known_defects","tags"}
    for k, v in body.items():
        if k in allowed:
            val = json.dumps(v) if k == "platforms" and isinstance(v, dict) else v
            conn.execute(f"UPDATE resell_listings SET {k}=?,updated_at=datetime('now') WHERE id=?", (val, lid))
    conn.commit()
    updated = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    return dict(updated)

@router.delete("/api/resell/listings/{lid}")
def resell_delete(lid: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Listing not found")
    # Remove image file if it's in our uploads dir
    if row["image_path"] and "resell_uploads" in str(row["image_path"]):
        try:
            (BASE / "static" / row["image_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    conn.execute("DELETE FROM resell_listings WHERE id=?", (lid,))
    conn.commit()
    conn.close()
    return {"ok": True}

@router.post("/api/resell/listings/{lid}/generate-content")
def resell_generate_content(lid: int, body: dict):
    """Generate platform-specific copy/paste content for a listing."""
    platform = body.get("platform", "facebook").lower()
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Listing not found")

    r = dict(row)
    features_text = ""
    try:
        ai = json.loads(r.get("ai_analysis") or "{}")
        features_text = "\n".join(f"• {f}" for f in ai.get("key_features", []))
    except Exception:
        pass

    # Build contextual lines
    defects_line = f"Flaws/defects: {r['known_defects']}" if r.get("known_defects") else ""
    included_line = f"Includes: {r['whats_included']}" if r.get("whats_included") else ""
    ship_pol = r.get("shipping_policy", "pickup_only")
    if ship_pol == "never":
        shipping_line = "Local pickup only — no shipping."
    elif ship_pol == "possible":
        shipping_line = "Shipping possible if buyer covers cost."
    else:
        shipping_line = "Local pickup preferred."
    tags = r.get("tags", "")
    tags_line = "Tags: " + tags if tags else ""
    price_mode = r.get("price_mode", "obo")
    price_mode_line = {"firm": "Price is firm.", "obo": "OBO — best offer welcome.", "haggle": "Price negotiable."}.get(price_mode, "")

    tpl = PLATFORM_TEMPLATES.get(platform, PLATFORM_TEMPLATES["facebook"])
    price_str = f"{r['asking_price']:.2f}" if r.get("asking_price") else "TBD"
    content = tpl.format(
        title=r.get("title","Item"),
        price=price_str,
        condition=r.get("condition","Good"),
        category=r.get("category","Other"),
        description=r.get("description","See photos for details."),
        features=features_text or "• Good condition",
        defects_line=defects_line,
        included_line=included_line,
        shipping_line=shipping_line + " " + price_mode_line,
        tags_line=tags_line,
    )
    # Clean up blank lines
    content = "\n".join(line for line in content.splitlines() if line.strip())
    return {"platform": platform, "content": content}

@router.post("/api/resell/listings/{lid}/post-ebay")
def resell_post_ebay(lid: int):
    """Stub: post listing to eBay via API. Requires eBay OAuth setup in Settings."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Listing not found")

    # Check for eBay token
    token_row = conn.execute("SELECT value FROM settings WHERE key='ebay_access_token'").fetchone()
    conn.close()
    if not token_row or not token_row["value"]:
        raise HTTPException(400, "eBay not connected. Add your eBay credentials in Settings → eBay Developer.")

    # TODO: Full eBay Sell API integration
    # See RESELL_PLAN.md for the full API payload structure.
    # Requires: ebay_app_id, ebay_cert_id, ebay OAuth token, business policies set in eBay Seller Hub.
    # Phase 2 implementation:
    #   1. POST to https://api.ebay.com/sell/inventory/v1/inventory-item/{sku} (create/update item)
    #   2. POST to https://api.ebay.com/sell/inventory/v1/offer (create offer with price/policy)
    #   3. POST to https://api.ebay.com/sell/inventory/v1/offer/{offerId}/publish (go live)
    return {"ok": False, "message": "eBay API integration coming in Phase 2. See RESELL_PLAN.md."}

@router.post("/api/resell/listings/{lid}/photos")
async def resell_add_photo(lid: int, file: UploadFile = File(...)):
    """Upload an additional photo to an existing listing."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM resell_listings WHERE id=?", (lid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Listing not found")
    ext = Path(file.filename or "img.jpg").suffix.lower()
    if ext not in IMAGE_EXTS:
        conn.close()
        raise HTTPException(400, "Unsupported image type")
    safe_name = f"resell_{lid}_{int(time.time())}_{random.randint(100,999)}{ext}"
    dest = RESELL_UPLOADS / safe_name
    content = await file.read()
    dest.write_bytes(content)
    # Is this the first photo? Make it primary.
    existing = conn.execute("SELECT COUNT(*) as n FROM resell_listing_images WHERE listing_id=?", (lid,)).fetchone()
    is_primary = 1 if existing["n"] == 0 else 0
    cur = conn.execute(
        "INSERT INTO resell_listing_images (listing_id, image_path, is_primary) VALUES (?,?,?)",
        (lid, f"resell_uploads/{safe_name}", is_primary)
    )
    conn.commit()
    photo_id = cur.lastrowid
    conn.close()
    return {"id": photo_id, "image_path": f"resell_uploads/{safe_name}", "is_primary": is_primary}

@router.get("/api/resell/listings/{lid}/photos")
def resell_get_photos(lid: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM resell_listing_images WHERE listing_id=? ORDER BY is_primary DESC, id ASC", (lid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.delete("/api/resell/listings/{lid}/photos/{photo_id}")
def resell_delete_photo(lid: int, photo_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_listing_images WHERE id=? AND listing_id=?", (photo_id, lid)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Photo not found")
    try:
        (BASE / "static" / row["image_path"]).unlink(missing_ok=True)
    except Exception:
        pass
    conn.execute("DELETE FROM resell_listing_images WHERE id=?", (photo_id,))
    # If we deleted the primary, promote the next one
    if row["is_primary"]:
        next_photo = conn.execute(
            "SELECT id FROM resell_listing_images WHERE listing_id=? ORDER BY id LIMIT 1", (lid,)
        ).fetchone()
        if next_photo:
            conn.execute("UPDATE resell_listing_images SET is_primary=1 WHERE id=?", (next_photo["id"],))
    conn.commit()
    conn.close()
    return {"ok": True}

@router.patch("/api/resell/listings/{lid}/photos/{photo_id}/primary")
def resell_set_primary(lid: int, photo_id: int):
    conn = get_conn()
    conn.execute("UPDATE resell_listing_images SET is_primary=0 WHERE listing_id=?", (lid,))
    conn.execute("UPDATE resell_listing_images SET is_primary=1 WHERE id=? AND listing_id=?", (photo_id, lid))
    conn.commit()
    conn.close()
    return {"ok": True}

@router.post("/api/resell/research")
async def resell_research_price(body: dict):
    """Get AI-powered price research for an item."""
    title     = body.get("title", "Unknown item")
    condition = body.get("condition", "Good")
    category  = body.get("category", "Other")

    # Try to scrape eBay sold listings for real data
    ebay_prices = []
    try:
        query = title.replace(" ", "+")
        url = f"https://www.ebay.com/sch/i.html?_nkw={query}&LH_Complete=1&LH_Sold=1&_sacat=0"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120"}
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
        # Extract sold prices with regex
        import re
        raw_prices = re.findall(r'\$([0-9,]+\.[0-9]{2})', r.text)
        for p in raw_prices[:20]:
            try:
                v = float(p.replace(",", ""))
                if 0.5 < v < 5000:
                    ebay_prices.append(v)
            except Exception:
                pass
        ebay_prices = ebay_prices[:15]
    except Exception as ex:
        logger.warning("eBay scrape failed: %s", ex)

    ebay_context = ""
    if ebay_prices:
        avg = sum(ebay_prices) / len(ebay_prices)
        ebay_context = f"\nRecent eBay sold prices for similar items: {[f'${p:.2f}' for p in ebay_prices[:8]]}. Average: ${avg:.2f}. Note: eBay prices are typically HIGHER than local marketplace (Facebook/OfferUp) by 20-40%. Adjust your local price accordingly."

    prompt = get_prompt('resell_price').format(title=title, condition=condition, category=category) + ebay_context

    try:
        payload = {
            "model": "google/gemma-4-12b-qat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 500,
        }
        def _job():
            r = httpx.post(f"{LMSTUDIO_URL}/chat/completions", json=payload,
                           headers=_llm_headers(), timeout=60)
            r.raise_for_status()
            return r.json()
        raw = await run_in_threadpool(_resell_llm, _job, "resell:price",
                                      "google/gemma-4-12b-qat")
        if raw is None:
            raise RuntimeError("price job failed or timed out")
        text = (raw["choices"][0]["message"].get("content") or
                raw["choices"][0]["message"].get("reasoning_content") or "{}").strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:]).rstrip("`").strip()
        result = json.loads(text)
    except Exception as ex:
        logger.error("Price research LLM error: %s", ex)
        result = {
            "market_low": None, "market_fair": None, "market_high": None,
            "suggested_list": None, "suggested_minimum": None,
            "price_rationale": "AI unavailable — check LM Studio is running.",
            "sell_fast_tip": "Price 10-20% below similar local listings.",
            "comparable_items": [],
        }

    return {**result, "ebay_sold_prices": ebay_prices}

@router.post("/api/resell/listings/{lid}/post")
def resell_post_to_platforms(lid: int, body: dict):
    """Kick off browser-automation posting to selected platforms."""
    platforms = body.get("platforms", [])
    if not platforms:
        raise HTTPException(400, "No platforms specified")
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Listing not found")
    cur = conn.execute(
        "INSERT INTO resell_auto_tasks (listing_id, platforms, status) VALUES (?,?,?)",
        (lid, json.dumps(platforms), "pending")
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    # Fire and forget
    t = threading.Thread(target=_do_post_via_agent, args=(task_id, lid, platforms), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "pending", "message": "Browser automation started. Check /api/resell/tasks/{id} for progress."}

@router.get("/api/resell/tasks/{task_id}")
def resell_task_status(task_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM resell_auto_tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Task not found")
    return dict(row)

@router.get("/api/resell/offers")
def resell_list_offers(listing_id: int = 0, status: str = ""):
    conn = get_conn()
    clauses, vals = [], []
    if listing_id: clauses.append("listing_id=?"); vals.append(listing_id)
    if status:     clauses.append("status=?");     vals.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT o.*, l.title, l.asking_price, l.min_accept_price, l.shipping_policy "
        f"FROM resell_offers o JOIN resell_listings l ON o.listing_id=l.id {where} "
        f"ORDER BY o.created_at DESC", vals
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.post("/api/resell/offers")
async def resell_record_offer(body: dict):
    """Record an incoming offer (from monitoring or manual entry)."""
    conn = get_conn()
    lid = body.get("listing_id")
    listing = conn.execute("SELECT * FROM resell_listings WHERE id=?", (lid,)).fetchone()
    if not listing: conn.close(); raise HTTPException(404, "Listing not found")

    offer_amt = body.get("offer_amount")
    buyer_loc = body.get("buyer_location", "")

    # Distance calc
    distance_miles, gas_cost = None, None
    if buyer_loc:
        settings_rows = conn.execute("SELECT key,value FROM settings WHERE key IN ('resell_location','resell_gas_cost_per_mile')").fetchall()
        s = {r["key"]: r["value"] for r in settings_rows}
        my_loc = s.get("resell_location", "")
        gas_rate = float(s.get("resell_gas_cost_per_mile", "0.21"))
        if my_loc:
            coords_me  = await geocode(my_loc)
            coords_buy = await geocode(buyer_loc)
            if coords_me and coords_buy:
                distance_miles = round(haversine_miles(*coords_me, *coords_buy), 1)
                gas_cost = round(distance_miles * 2 * gas_rate, 2)  # round trip

    # Auto-qualify offer
    min_accept = listing["min_accept_price"]
    status = "pending"
    if offer_amt and min_accept and offer_amt >= min_accept:
        status = "qualified"
    elif offer_amt and min_accept and offer_amt < min_accept * 0.5:
        status = "lowball"

    cur = conn.execute(
        """INSERT INTO resell_offers
           (listing_id, platform, buyer_name, buyer_message, offer_amount,
            buyer_location, distance_miles, gas_cost, status)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (lid, body.get("platform"), body.get("buyer_name"),
         body.get("buyer_message"), offer_amt, buyer_loc,
         distance_miles, gas_cost, status)
    )
    offer_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": offer_id, "status": status, "distance_miles": distance_miles, "gas_cost": gas_cost}

@router.patch("/api/resell/offers/{offer_id}")
def resell_update_offer(offer_id: int, body: dict):
    conn = get_conn()
    for k, v in body.items():
        if k in {"status", "buyer_message", "buyer_location", "offer_amount", "notified"}:
            conn.execute(f"UPDATE resell_offers SET {k}=? WHERE id=?", (v, offer_id))
    conn.commit()
    row = conn.execute("SELECT * FROM resell_offers WHERE id=?", (offer_id,)).fetchone()
    conn.close()
    return dict(row)

@router.delete("/api/resell/offers/{offer_id}")
def resell_delete_offer(offer_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM resell_offers WHERE id=?", (offer_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@router.get("/api/resell/monitor/status")
def resell_monitor_status():
    """How many active listings are being monitored."""
    conn = get_conn()
    active = conn.execute(
        "SELECT COUNT(*) as n FROM resell_listings WHERE status='listed' AND platforms != '{}'",
    ).fetchone()["n"]
    unread = conn.execute(
        "SELECT COUNT(*) as n FROM resell_offers WHERE status='qualified' AND notified=0"
    ).fetchone()["n"]
    conn.close()
    return {"active_listings": active, "unread_offers": unread, "monitoring": active > 0}


# ─── Store-native browser posting (headed Chrome via CDP, no OpenClaw) ────────
