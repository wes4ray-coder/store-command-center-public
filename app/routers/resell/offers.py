"""resell — buyer offers, browser-automation posting tasks, and monitor status."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from starlette.concurrency import run_in_threadpool
from deps import *
from services import *
from ._base import router


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
