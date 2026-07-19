"""resell — AI vision analysis + price research (routes through the orchestrator queue)."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from starlette.concurrency import run_in_threadpool
from deps import *
from services import *
from ._base import router


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
