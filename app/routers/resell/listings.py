"""resell — listings CRUD, per-listing photos, platform copy/paste content, eBay post stub."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from starlette.concurrency import run_in_threadpool
from deps import *
from services import *
from ._base import router


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
