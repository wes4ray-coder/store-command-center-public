"""God Console — treasury/budget surface: summary, full ledger, the learned-taste
readout + test, automation config (mode + monthly cap), manual budget entries, and
the on-demand revenue sync."""
import json, logging, threading, os
from fastapi import HTTPException, Body

from deps import get_conn
import world_ops as wo
from ._base import router


# ── summary / budget ─────────────────────────────────────────────────────────
@router.get("/api/world/ops/summary")
def ops_summary():
    conn = get_conn()
    try:
        return wo.summary(conn)
    finally:
        conn.close()


@router.get("/api/world/ops/ledger")
def ops_ledger(limit: int = 200):
    """Full transaction history + totals by kind, for the Treasury tab."""
    conn = get_conn()
    try:
        wo.ensure(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM world_ops_ledger ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        totals = {r["kind"]: r["s"] for r in conn.execute(
            "SELECT kind, COALESCE(SUM(amount_cents),0) AS s FROM world_ops_ledger GROUP BY kind")}
        return {"ledger": rows, "totals": totals}
    finally:
        conn.close()


@router.get("/api/world/taste")
def taste_stats():
    """What the town has learned about god's taste (the world_taste model)."""
    import world_taste
    conn = get_conn()
    try:
        st = world_taste.stats(conn)
        st["by_source"] = {r["source"]: r["n"] for r in conn.execute(
            "SELECT source, COUNT(*) n FROM world_taste GROUP BY source")}
        st["recent"] = [dict(r) for r in conn.execute(
            "SELECT kind, substr(text,1,70) AS text, label, source FROM world_taste "
            "ORDER BY id DESC LIMIT 6")]
        return st
    finally:
        conn.close()


@router.post("/api/world/taste/test")
def taste_test(body: dict = Body(...)):
    """Score a candidate idea against the learned taste model."""
    import world_taste
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    conn = get_conn()
    try:
        return {"text": text, "score": round(world_taste.score(conn, text), 3)}
    finally:
        conn.close()


@router.post("/api/world/ops/config")
def ops_config(body: dict = Body(...)):
    """Set automation mode (review|budget) and the monthly bill cap (dollars)."""
    conn = get_conn()
    try:
        wo.ensure(conn)
        updates = {}
        if "mode" in body:
            m = body["mode"]
            if m not in ("review", "budget"):
                raise HTTPException(400, "mode must be 'review' or 'budget'")
            updates["world_ops_automation_mode"] = m
            # (world_control now reads world_ops_automation_mode live — no shadow to sync)
        if "cap_cents" in body:
            updates["world_ops_cap_cents"] = int(body["cap_cents"])
        elif "cap_dollars" in body:
            updates["world_ops_cap_cents"] = int(round(float(body["cap_dollars"]) * 100))
        wo._save_cfg(conn, updates)
        return wo.summary(conn)
    finally:
        conn.close()


@router.post("/api/world/ops/budget/entry")
def ops_budget_entry(body: dict = Body(...)):
    """Manually record money: fund (credit), revenue (e.g. Cults3D), or payment
    (you paid the bill). amount in cents (or amount_dollars)."""
    kind = (body.get("kind") or "fund").lower()
    if kind not in ("fund", "revenue", "payment"):
        raise HTTPException(400, "kind must be fund|revenue|payment")
    amt = body.get("amount_cents")
    if amt is None and body.get("amount_dollars") is not None:
        amt = int(round(float(body["amount_dollars"]) * 100))
    amt = int(amt or 0)
    if amt <= 0:
        raise HTTPException(400, "amount must be positive")
    conn = get_conn()
    try:
        wo.ensure(conn)
        wo._ledger(conn, amt, kind, source=body.get("source") or "manual", note=body.get("note"))
        return wo.summary(conn)
    finally:
        conn.close()


@router.post("/api/world/ops/sync-revenue")
def ops_sync_revenue():
    """Pull real sales (Etsy receipts) into the treasury as +revenue — the same sync the
    world loop runs, on demand. Deduped; safe to call repeatedly."""
    import world_sell
    r = world_sell.sync_revenue()
    conn = get_conn()
    try:
        r["summary"] = wo.summary(conn)
    finally:
        conn.close()
    return r
