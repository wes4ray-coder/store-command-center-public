"""printify routes."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from deps import *
from services import *

router = APIRouter()


@router.get("/api/printify/shops")
def printify_shops():
    return _get_printify().get_shops()

@router.get("/api/printify/products")
def printify_products():
    return _get_printify().get_products()

class UpdateProductRequest(BaseModel):
    title:       Optional[str]  = None
    description: Optional[str]  = None
    tags:        Optional[str]  = None  # comma-separated

@router.patch("/api/printify/products/{product_id}")
def update_printify_product(product_id: str, req: UpdateProductRequest):
    """Update a Printify product's title, description, or tags."""
    conn = get_conn()
    s = _dec_secrets({r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings").fetchall()})
    conn.close()
    pk = s.get("printify_key", "")
    ps = s.get("printify_shop_id", "")
    if not pk or not ps:
        raise HTTPException(400, "Printify not configured")
    tag_list = [t.strip() for t in (req.tags or "").split(",") if t.strip()] if req.tags else None
    result = PrintifyClient(pk, ps).update_product(
        product_id,
        title=req.title,
        description=req.description,
        tags=tag_list,
    )
    return {"ok": True, "product": result}

class PublishRequest(BaseModel):
    design_id: int
    title: str
    description: Optional[str] = ""
    tags: Optional[str] = ""   # comma-separated string; converted to list internally
    product_type: Optional[str] = None  # overrides design's product_type if supplied
    retail_price_cents: Optional[int] = None  # single price override (legacy / fallback)

@router.post("/api/printify/publish")
def publish_to_printify(req: PublishRequest, background_tasks: BackgroundTasks):
    conn = get_conn()
    design = conn.execute("SELECT * FROM designs WHERE id=?", (req.design_id,)).fetchone()
    if not design:
        conn.close()
        raise HTTPException(404, "Design not found")
    if design["status"] not in ("approved", "published"):
        conn.close()
        raise HTTPException(400, "Design must be approved before publishing")
    product_type = req.product_type or design["product_type"] or "T-Shirt"
    # Guard: refuse if this image+type combo is already live on Printify
    already = conn.execute(
        "SELECT id, printify_id FROM designs WHERE image_path=? AND product_type=? AND status='published' AND printify_id IS NOT NULL",
        (design["image_path"], product_type)
    ).fetchone()
    conn.close()
    if already:
        return {"ok": True, "skipped": True, "reason": "already_published",
                "message": f"{product_type} is already live on Printify (design #{already['id']})"}
    background_tasks.add_task(
        _do_publish, req.design_id, req.title, req.description,
        req.tags, product_type, design["image_path"], req.retail_price_cents
    )
    return {"ok": True, "skipped": False, "message": "Publishing to Printify in background"}

@router.get("/api/printify/images")
def printify_list_images():
    """List images uploaded to the Printify media library, cross-referenced with local designs."""
    try:
        client = _get_printify()
        data = client.get_uploaded_images(limit=50)
        items = data if isinstance(data, list) else data.get("data", [])
        # Cross-reference: find which local published design uses each image id
        conn = get_conn()
        ref_rows = conn.execute(
            """SELECT printify_image_id, image_path, product_type, printify_id, id
               FROM designs WHERE printify_image_id IS NOT NULL AND status='published'"""
        ).fetchall()
        conn.close()
        img_map = {}
        for r in ref_rows:
            iid = r["printify_image_id"]
            if iid not in img_map:
                img_map[iid] = []
            img_map[iid].append({
                "design_id": r["id"],
                "product_type": r["product_type"],
                "printify_id": r["printify_id"],
                "image_path": r["image_path"],
            })
        for img in items:
            img["local_designs"] = img_map.get(img.get("id", ""), [])
        return {"ok": True, "images": items}
    except HTTPException:
        raise   # config errors (e.g. missing API key) are 4xx, not server errors
    except Exception as e:
        raise HTTPException(500, str(e))

@router.delete("/api/printify/images/{image_id}")
def delete_printify_image(image_id: str):
    """Delete an uploaded image from the Printify media library."""
    try:
        client = _get_printify()
        # Printify uses DELETE /v1/uploads/{image_id}.json
        r = __import__('httpx').delete(
            f"https://api.printify.com/v1/uploads/{image_id}.json",
            headers=client.headers, timeout=30
        )
        if not r.is_success:
            try:    detail = r.json()
            except: detail = r.text[:400]
            raise Exception(f"Printify HTTP {r.status_code}: {detail}")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.delete("/api/printify/products/{product_id}")
def delete_printify_product(product_id: str):
    """Delete a product from Printify AND mark the matching design as unpublished."""
    try:
        client = _get_printify()
        client.delete_product(product_id)
    except Exception as e:
        raise HTTPException(500, f"Printify delete failed: {e}")

    # Update DB: mark design(s) with this printify_id back to 'approved'
    conn = get_conn()
    conn.execute(
        "UPDATE designs SET status='approved', printify_id=NULL, updated_at=datetime('now') WHERE printify_id=?",
        (product_id,)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "message": f"Product {product_id} deleted from Printify and unpublished locally"}
