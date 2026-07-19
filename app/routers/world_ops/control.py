"""God Console — the automation controls (Chunk 4 auto-config + run-now), the
unified Company Control Plane, and the Workboard (the whole plan→done pipeline)."""
import json, logging, threading, os
from fastapi import HTTPException, Body

from deps import get_conn
import world_ops as wo
import world_auto
import world_strategy
import world_control
from ._base import router


# ── automation controls (Chunk 4) ────────────────────────────────────────────
@router.get("/api/world/ops/auto-config")
def ops_auto_config_get():
    return world_auto.status()


@router.post("/api/world/ops/auto-config")
def ops_auto_config_set(body: dict = Body(...)):
    updates = {}
    if "enabled" in body:
        updates["world_auto_enabled"] = "1" if body["enabled"] in (True, 1, "1", "true", "on") else "0"
    for k, sk in (("interval_min", "world_auto_interval_min"),
                  ("active_start", "world_auto_active_start"),
                  ("active_end", "world_auto_active_end"),
                  ("govern_min", "world_auto_govern_min")):
        if k in body:
            updates[sk] = int(body[k])
    if "kinds" in body:
        v = body["kinds"]
        updates["world_auto_kinds"] = ",".join(v) if isinstance(v, list) else str(v)
    world_auto.save_config(updates)
    return world_auto.status()


@router.post("/api/world/ops/auto-run-now")
def ops_auto_run_now(body: dict = Body(default={})):
    """Kick one creation cycle in the background (generation blocks on the GPU)."""
    if world_auto._state["running"]:
        return {"ok": False, "error": "a creation is already in progress"}
    kind = body.get("kind") or world_auto.pick_kind()
    threading.Thread(target=world_auto.run_cycle, args=(kind, True), daemon=True).start()
    return {"ok": True, "started": kind}


# ── Company Control Plane: unified automation panel + capabilities ───────────
@router.get("/api/world/control/panel")
def control_panel():
    return world_control.panel()


@router.post("/api/world/control/master")
def control_master(body: dict = Body(...)):
    return world_control.set_master(bool(body.get("on")))


@router.post("/api/world/control/system")
def control_system(body: dict = Body(...)):
    sid = body.get("id")
    res = world_control.set_system(sid, bool(body.get("on")))
    if res is None:
        raise HTTPException(404, f"unknown system '{sid}'")
    return res


@router.post("/api/world/control/trigger")
def control_trigger(body: dict = Body(...)):
    return world_control.invoke(body.get("id"), body.get("args"))


@router.post("/api/world/control/sell-config")
def control_sell_config(body: dict = Body(...)):
    pc = body.get("price_cents")
    if pc is None and body.get("price_dollars") is not None:
        pc = int(round(float(body["price_dollars"]) * 100))
    return world_control.set_sell_config(price_cents=pc, product_type=body.get("product_type"))


# ── Company Workboard: the whole pipeline (plan → to-do → doing → done) ──────
@router.get("/api/world/ops/workboard")
def ops_workboard():
    conn = get_conn()
    try:
        wo.ensure(conn)
        pending = [dict(r) for r in conn.execute(
            "SELECT * FROM world_prayers WHERE status='pending' ORDER BY "
            "CASE WHEN cost_cents>0 THEN 0 ELSE 1 END, id DESC").fetchall()]
        done = [dict(r) for r in conn.execute(
            "SELECT * FROM world_prayers WHERE status IN ('done','approved','failed','rejected') "
            "ORDER BY resolved_at DESC, id DESC LIMIT 14").fetchall()]
        rep = world_strategy.state(conn)
        auto = world_auto.status()
        summ = wo.summary(conn)
        return {"pending": pending, "done": done, "republic": rep, "auto": auto,
                "balance_cents": summ["balance_cents"], "owed_cents": summ["owed_cents"]}
    finally:
        conn.close()
