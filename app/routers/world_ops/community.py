"""God Console — community messages, PayPal config/verify/withdraw (the gated
real-money payout is filed here as a prayer), and the Info Board collage."""
import json, logging, threading, os
from fastapi import HTTPException, Body

from deps import get_conn
import world_ops as wo
import world_auto
import paypal_client
from ._base import router, _media_url, _designs_url


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
