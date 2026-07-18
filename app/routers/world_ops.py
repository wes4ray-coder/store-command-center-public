"""
The Company — God Console HTTP surface.

Thin endpoints over world_ops (budget ledger, prayers approval queue, community
messages, PayPal config). All under /api/world/ops/*.
"""
import json, logging, threading, os
from fastapi import APIRouter, HTTPException, Body

from deps import get_conn
from config import DESIGNS_PENDING, DESIGNS_APPROVED, DESIGNS_REJECTED
import world_ops as wo
import world_auto
import world_strategy
import world_bible          # registers the library_research executor on import
import world_sell           # registers the post_etsy/post_printify executors on import
import world_control        # unified automation control plane (runs init() on import)
import paypal_client

router = APIRouter()
logger = logging.getLogger("store")


# ── executor: a blessed payout sends REAL money to your PayPal ───────────────
def _exec_paypal_payout(conn, prayer):
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    amt_cents = int(payload.get("amount_cents") or 0)
    # SECURITY: the payout recipient is ALWAYS the configured owner email — never a
    # value carried in the (attacker-controllable) payload. A local/MCP caller that
    # files a payout can never redirect the money to a different account.
    email = wo.cfg("world_paypal_email")
    if amt_cents <= 0 or not email:
        raise ValueError("invalid payout (amount/owner email)")
    if wo.balance_cents(conn) < amt_cents:
        raise ValueError("insufficient wallet balance for this payout")
    res = paypal_client.create_payout(wo.paypal_cfg(), amt_cents / 100.0, email,
                                      note=payload.get("note") or "Company earnings",
                                      prayer_id=prayer["id"])
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "payout failed")
    wo._ledger(conn, -amt_cents, "payout", source="paypal",
               note=f"withdraw to {email}", prayer_id=prayer["id"])
    wo.note(f"💸 Sent ${amt_cents/100:.2f} to your PayPal ({email}).", kind="praise", conn=conn)
    return f"payout {res.get('batch_id')} ({res.get('status')})"


wo.register_executor("paypal_payout", _exec_paypal_payout)


# ── media path → browser URL (served under /store) ───────────────────────────
def _media_url(path):
    if not path:
        return None
    if path.startswith("/store") or path.startswith("http"):
        return path
    for seg in ("/designs/", "/videos/"):
        i = path.find(seg)
        if i != -1:
            return "/store" + path[i:]
    return None


def _designs_url(image_path):
    """Browser URL for a generated design image, resolved to its CURRENT folder.

    A design's file moves pending → approved/rejected as it's reviewed, but the
    generations row keeps the original pending path — so a cached board URL 404s after a
    move. Resolve by filename against the live folders; return None if it's gone entirely
    (so the board skips it rather than emitting a 404)."""
    if not image_path:
        return None
    name = os.path.basename(str(image_path))
    for d in (DESIGNS_PENDING, DESIGNS_APPROVED, DESIGNS_REJECTED):
        if (d / name).exists():
            return f"/store/designs/{d.name}/{name}"
    return None


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
            # keep the control-plane's auto_publish desired state in sync, or its
            # next cascade would silently revert a mode set from the God Console
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                         ("company_desired_auto_publish", "1" if m == "budget" else "0"))
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


# ── prayers ──────────────────────────────────────────────────────────────────
def _prayer_thumb(conn, payload_raw):
    """Preview image for a creative prayer, resolved to its current folder."""
    try:
        payload = json.loads(payload_raw) if payload_raw else {}
        if payload.get("type") != "image":
            return None
        path = payload.get("path")
        gid = payload.get("gen_id")
        if gid:
            r = conn.execute("SELECT image_path FROM generations WHERE id=?", (gid,)).fetchone()
            if r and r["image_path"]:
                path = r["image_path"]
        return _designs_url(path)
    except Exception:
        return None


@router.get("/api/world/ops/prayers")
def ops_prayers(status: str = "", limit: int = 50):
    conn = get_conn()
    try:
        wo.ensure(conn)
        if status:
            rows = conn.execute("SELECT * FROM world_prayers WHERE status=? ORDER BY id DESC LIMIT ?",
                                (status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM world_prayers ORDER BY "
                                "CASE status WHEN 'pending' THEN 0 ELSE 1 END, id DESC LIMIT ?",
                                (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # split creations (art/products the agents MAKE → judge/like) from operations
            d["group"] = "creation" if d.get("kind") in wo.CREATION_KINDS else "operation"
            d["thumb"] = _prayer_thumb(conn, d.get("payload")) if d["group"] == "creation" else None
            out.append(d)
        return {"prayers": out}
    finally:
        conn.close()


@router.post("/api/world/ops/prayers")
def ops_pray(body: dict = Body(...)):
    """Raise a prayer (used by the UI to test, or by agents/automation)."""
    kind = body.get("kind")
    title = body.get("title")
    if not kind or not title:
        raise HTTPException(400, "kind and title required")
    # Irreversible money-out / secret-export prayers may ONLY be filed by their
    # dedicated endpoints (which validate amount, recipient and balance) — never
    # through this generic path with an arbitrary payload/recipient/cost.
    if kind in wo.ALWAYS_GATE:
        raise HTTPException(403, f"'{kind}' must be filed via its dedicated endpoint, "
                                 "not the generic prayer API")
    p = wo.pray(kind, title, detail=body.get("detail", ""),
                cost_cents=body.get("cost_cents"), payload=body.get("payload"),
                agent_name=body.get("agent_name"))
    return {"prayer": p}


@router.post("/api/world/ops/prayers/{pid}/approve")
def ops_approve(pid: int, body: dict = Body(default={})):
    conn = get_conn()
    try:
        wo.ensure(conn)
        p = wo._get(conn, pid)
        if not p:
            raise HTTPException(404, "prayer not found")
        if p["status"] != "pending":
            raise HTTPException(400, f"prayer already {p['status']}")
        if p["cost_cents"] and not wo.can_spend(conn, p["cost_cents"]) and not body.get("force"):
            raise HTTPException(400, "over the monthly budget cap — raise the cap or pass force=true")
        return {"prayer": wo._resolve(conn, pid, approve=True, god_comment=body.get("comment") or "approved")}
    finally:
        conn.close()


@router.post("/api/world/ops/prayers/{pid}/reject")
def ops_reject(pid: int, body: dict = Body(default={})):
    conn = get_conn()
    try:
        wo.ensure(conn)
        p = wo._get(conn, pid)
        if not p:
            raise HTTPException(404, "prayer not found")
        return {"prayer": wo._resolve(conn, pid, approve=False, god_comment=body.get("comment") or "rejected")}
    finally:
        conn.close()


# ── gates (each a toggle) ────────────────────────────────────────────────────
@router.get("/api/world/ops/gates")
def ops_gates():
    """Every gate and whether it's on: the 'always judge creations' gate + the per-kind
    always-need-a-blessing gates. Each is user-toggleable."""
    return {
        "creations": wo.cfg("world_ops_gate_creations") == "1",
        "kinds": [{"kind": k, "label": lbl, "gated": wo.cfg(f"world_ops_gate_{k}") == "1"}
                  for k, lbl in wo.GATEABLE],
    }


@router.post("/api/world/ops/gates")
def ops_set_gate(body: dict = Body(...)):
    """Flip a gate. {key: 'creations' | <kind>, on: bool}."""
    key = (body.get("key") or "").strip()
    on = "1" if body.get("on") else "0"
    # Irreversible money-out / secret-export gates are the deliberate exception to the
    # "every gate is toggleable" rule — they can never be turned off.
    if on == "0" and key in wo.ALWAYS_GATE:
        raise HTTPException(400, f"'{key}' is an irreversible money-out gate and cannot "
                                 "be turned off")
    conn = get_conn()
    try:
        wo.ensure(conn)
        if key == "creations":
            wo._save_cfg(conn, {"world_ops_gate_creations": on})
        elif key in {k for k, _ in wo.GATEABLE}:
            wo._save_cfg(conn, {f"world_ops_gate_{key}": on})
        else:
            raise HTTPException(400, f"unknown gate: {key!r}")
        return {"ok": True, "key": key, "on": on == "1"}
    finally:
        conn.close()


# ── community messages ───────────────────────────────────────────────────────
@router.get("/api/world/ops/messages")
def ops_messages(limit: int = 30):
    conn = get_conn()
    try:
        wo.ensure(conn)
        rows = conn.execute("SELECT * FROM world_messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {"messages": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/api/world/ops/messages")
def ops_add_message(body: dict = Body(...)):
    text = body.get("text")
    if not text:
        raise HTTPException(400, "text required")
    wo.note(text, kind=body.get("kind", "info"), from_agent=body.get("from_agent"))
    return {"ok": True}


@router.post("/api/world/ops/messages/seen")
def ops_messages_seen():
    conn = get_conn()
    try:
        wo.ensure(conn)
        conn.execute("UPDATE world_messages SET seen=1 WHERE seen=0")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ── PayPal config (funding wiring lands in Chunk 5; keys are stored now) ──────
@router.post("/api/world/ops/paypal/config")
def ops_paypal_config(body: dict = Body(...)):
    conn = get_conn()
    try:
        wo.ensure(conn)
        updates = {}
        for k, sk in (("client_id", "world_paypal_client_id"), ("secret", "world_paypal_secret"),
                      ("mode", "world_paypal_mode"), ("email", "world_paypal_email")):
            if k in body:
                updates[sk] = body[k]
        wo._save_cfg(conn, updates)
        s = wo.summary(conn)
        return {"ok": True, "paypal": s["paypal"]}
    finally:
        conn.close()


@router.post("/api/world/ops/paypal/verify")
def ops_paypal_verify():
    """Prove the stored keys work (real OAuth client-credentials). Moves no money."""
    return paypal_client.verify(wo.paypal_cfg())


@router.post("/api/world/ops/paypal/withdraw")
def ops_paypal_withdraw(body: dict = Body(...)):
    """Queue a payout of your earnings to your PayPal. Files a gated prayer —
    real money only moves once you bless it in the God Console."""
    amt = body.get("amount_cents")
    if amt is None and body.get("amount_dollars") is not None:
        amt = int(round(float(body["amount_dollars"]) * 100))
    amt = int(amt or 0)
    if amt <= 0:
        raise HTTPException(400, "amount must be positive")
    cfg = wo.paypal_cfg()
    if not (cfg["client_id"] and cfg["secret"]):
        raise HTTPException(400, "PayPal not configured")
    if not cfg["email"]:
        raise HTTPException(400, "no PayPal email set to receive the payout")
    conn = get_conn()
    try:
        wo.ensure(conn)
        bal = wo.balance_cents(conn)
        if bal < amt:
            raise HTTPException(400, f"wallet has only ${bal/100:.2f} available to withdraw")
    finally:
        conn.close()
    # cost_cents carries the REAL amount so the budget cap (can_spend) and the
    # auto-approve affordability check both see it — a payout can't slip past the cap
    # by hiding its value in the payload. (The recipient is always the owner email,
    # re-read from config at execute time — the payload email is never trusted.)
    p = wo.pray("paypal_payout",
                f"Withdraw ${amt/100:.2f} to your PayPal",
                detail=f"Send ${amt/100:.2f} of company earnings to {cfg['email']}. Real money — needs your blessing.",
                cost_cents=amt,
                payload={"amount_cents": amt, "note": "Company earnings"})
    return {"prayer": p}


# ── Info Board: the collage of recent creations + community + automation ─────
@router.get("/api/world/ops/board")
def ops_board(limit: int = 24):
    conn = get_conn()
    try:
        wo.ensure(conn)
        items = []

        def add(rows, typ, path_col, title_col, source, url_fn=_media_url):
            for r in rows:
                url = url_fn(r[path_col])
                if not url:
                    continue
                items.append({"type": typ, "url": url, "title": r[title_col] or typ,
                              "created_at": r["created_at"], "source": source})

        add(conn.execute("SELECT image_path,prompt,created_at FROM generations "
                         "WHERE status='done' AND image_path IS NOT NULL ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall(), "image", "image_path", "prompt", "generations",
            url_fn=_designs_url)
        add(conn.execute("SELECT audio_path,prompt,created_at FROM audio_clips "
                         "WHERE status='done' AND audio_path IS NOT NULL ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall(), "audio", "audio_path", "prompt", "audio_clips")
        add(conn.execute("SELECT video_path,prompt,created_at FROM videos "
                         "WHERE status='done' AND video_path IS NOT NULL ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall(), "video", "video_path", "prompt", "videos")
        add(conn.execute("SELECT image_path,label,created_at FROM world_props "
                         "WHERE image_path IS NOT NULL ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall(), "prop", "image_path", "label", "world_props")

        items.sort(key=lambda x: x["created_at"] or "", reverse=True)
        items = items[:limit]

        msgs = [dict(r) for r in conn.execute(
            "SELECT * FROM world_messages ORDER BY id DESC LIMIT 12").fetchall()]
        pend = conn.execute("SELECT COUNT(*) AS n FROM world_prayers WHERE status='pending'").fetchone()["n"]
        recent_pushes = [dict(r) for r in conn.execute(
            "SELECT title,wp_link,kind,pushed_at FROM portal_pushes ORDER BY id DESC LIMIT 6").fetchall()]
        return {"items": items, "messages": msgs, "pending_prayers": pend,
                "recent_published": recent_pushes, "auto": world_auto.status()}
    finally:
        conn.close()


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


# ── The Republic (survival strategy engine) ──────────────────────────────────
@router.get("/api/world/republic/state")
def republic_state():
    return world_strategy.state()


@router.post("/api/world/republic/convene")
def republic_convene():
    """Convene the assembly: assess → propose → vote → adopt → act → measure."""
    conn = get_conn()
    try:
        return world_strategy.run_cycle(conn)
    finally:
        conn.close()


# ── The Bible (BOOK.md is the Word; agents grow the teachings) ───────────────
@router.get("/api/world/bible/word")
def bible_word():
    return world_bible.word()


@router.get("/api/world/bible/teachings")
def bible_teachings(limit: int = 100):
    return {"teachings": world_bible.teachings(limit)}


@router.post("/api/world/republic/strategy/{sid}/override")
def republic_override(sid: int, body: dict = Body(...)):
    """God overrides the vote: 'adopt' (force + act) or 'reject' a strategy."""
    decision = body.get("decision")
    if decision not in ("adopt", "reject"):
        raise HTTPException(400, "decision must be 'adopt' or 'reject'")
    conn = get_conn()
    try:
        res = world_strategy.override(conn, sid, decision)
        if res is None:
            raise HTTPException(404, "strategy not found")
        return res
    finally:
        conn.close()
