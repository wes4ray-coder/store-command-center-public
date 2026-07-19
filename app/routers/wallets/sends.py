"""wallets — the SPENDING engine and the gated send lifecycle.

Sends are DOUBLE-GATED: /send queues a `wallet_sends` row ('proposed'); /prepare
dry-runs the fee (signs but broadcasts nothing); /broadcast does NOT sign directly —
it files a `wallet_send` prayer in the God Console, and the transaction is only signed
+ broadcast once a HUMAN blesses that prayer (the executor registered here). A
localhost/MCP caller (which bypasses auth) therefore cannot move real crypto on its own."""
import json

from fastapi import APIRouter

from deps import *
from services import *

import wallet_lib as wl
import world_ops as wo

from ._base import router, _ensure_seed, _xmr_rpc


# ── gated sends (queue only — NO signing, NO broadcast at this step) ──────────
@router.get("/api/wallets/sends")
def wallets_sends(status: Optional[str] = None):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM wallet_sends WHERE status=? "
                            "ORDER BY id DESC LIMIT 200", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM wallet_sends "
                            "ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return {"sends": [dict(r) for r in rows]}


class SendIn(BaseModel):
    sym: str
    to: str
    amount: float
    note: Optional[str] = ""


@router.post("/api/wallets/send")
def wallets_send(body: SendIn):
    """Queue a send proposal. INTENTIONALLY does not sign or broadcast anything —
    review-gating first; the hot path to real funds comes later, behind more checks."""
    sym = (body.sym or "").upper().strip()
    to = (body.to or "").strip()
    if sym not in wl.COINS:
        raise HTTPException(400, f"Unknown coin '{sym}' — one of {', '.join(wl.COINS)}.")
    if not to:
        raise HTTPException(400, "Destination address is required.")
    if not body.amount or body.amount <= 0:
        raise HTTPException(400, "Amount must be > 0.")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO wallet_sends (sym,to_addr,amount,status,note) VALUES (?,?,?,?,?)",
        (sym, to, float(body.amount), "proposed", body.note or ""))
    conn.commit()
    row = conn.execute("SELECT * FROM wallet_sends WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return {"send": dict(row),
            "note": "queued — now Prepare (fee preview) then Broadcast (with confirm)"}


# ── SPENDING engine: prepare (dry) → broadcast (confirm) ──────────────────────
def _engine_send(sym: str, seed: str, to: str, amount: float, broadcast: bool) -> dict:
    """Dispatch to the right chain. Returns {fee, ...} on dry run, {txid, fee} on
    broadcast. Raises on any failure (insufficient funds, bad address, node down)."""
    if sym == "ETH":
        return wl.eth_send(seed, to, amount, broadcast)
    if sym in ("BTC", "LTC", "DOGE"):
        return wl.btc_family_send(sym, seed, to, amount, broadcast)
    if sym == "XMR":
        atomic = int(round(amount * 10 ** wl.COIN_DECIMALS["XMR"]))
        params = {"destinations": [{"amount": atomic, "address": to}], "priority": 0}
        if not broadcast:
            params["do_not_relay"] = True
            r = _xmr_rpc("transfer", params, timeout=30)
            return {"fee": (r.get("fee") or 0) / 1e12}
        r = _xmr_rpc("transfer", params, timeout=60)
        return {"txid": r.get("tx_hash"), "fee": (r.get("fee") or 0) / 1e12}
    raise RuntimeError(f"sending not supported for {sym}")


def _get_send(send_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM wallet_sends WHERE id=?", (send_id,)).fetchone()
    conn.close()
    return row


@router.post("/api/wallets/sends/{send_id}/prepare")
def wallets_send_prepare(send_id: int):
    """Dry-run: build + sign the tx and return the network fee. Broadcasts NOTHING."""
    row = _get_send(send_id)
    if not row:
        raise HTTPException(404, "No such send.")
    if row["status"] not in ("proposed", "prepared"):
        raise HTTPException(400, f"Send is '{row['status']}', can't prepare.")
    seed = _ensure_seed()
    try:
        res = _engine_send(row["sym"], seed, row["to_addr"], row["amount"], False)
    except Exception as e:
        raise HTTPException(400, f"Prepare failed: {str(e)[:200]}")
    fee = res.get("fee")
    note = f"fee ≈ {fee:.8f} {row['sym']}" if fee is not None else "prepared"
    conn = get_conn()
    conn.execute("UPDATE wallet_sends SET status='prepared', note=?, "
                 "updated_at=datetime('now') WHERE id=?", (note, send_id))
    conn.commit()
    conn.close()
    return {"send": dict(_get_send(send_id)), "fee": fee, "detail": res,
            "confirm_hint": f"Broadcasting sends {row['amount']} {row['sym']} to "
                            f"{row['to_addr']} — irreversible."}


class BroadcastIn(BaseModel):
    confirm: bool = False


# CoinGecko ids for a best-effort USD valuation of a send (drives the God Console
# budget-cap check). Missing/failed price → 0, and the human blessing still gates it.
_CG_IDS = {"BTC": "bitcoin", "LTC": "litecoin", "DOGE": "dogecoin",
           "ETH": "ethereum", "KAS": "kaspa", "XMR": "monero"}


def _usd_cents(sym: str, amount: float) -> int:
    """Best-effort fiat value of a crypto amount, in cents (0 if the price is unknown)."""
    try:
        from cache import cached
        cid = _CG_IDS.get(sym)
        if not cid:
            return 0
        price = cached(f"wallets:usd:{cid}", 300, lambda: float(
            httpx.get("https://api.coingecko.com/api/v3/simple/price",
                      params={"ids": cid, "vs_currencies": "usd"}, timeout=8)
            .json().get(cid, {}).get("usd") or 0))
        return int(round(float(amount) * price * 100))
    except Exception:
        return 0


def _exec_wallet_send(conn, prayer):
    """EXECUTOR for a blessed `wallet_send` prayer: NOW sign + broadcast the real tx.
    Only ever reached after a human blessed the prayer in the God Console."""
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    send_id = int(payload.get("send_id") or 0)
    row = _get_send(send_id)
    if not row:
        raise ValueError(f"send #{send_id} not found")
    if row["status"] not in ("proposed", "prepared", "pending_blessing"):
        raise ValueError(f"send #{send_id} is '{row['status']}', can't broadcast")
    seed = _ensure_seed()
    res = _engine_send(row["sym"], seed, row["to_addr"], row["amount"], True)
    txid = res.get("txid") or ""
    fee = res.get("fee")
    note = f"sent · fee {fee:.8f} {row['sym']}" if fee is not None else "sent"
    conn.execute("UPDATE wallet_sends SET status='sent', txid=?, note=?, "
                 "updated_at=datetime('now') WHERE id=?", (txid, note, send_id))
    # book the outflow on the God Console ledger (best-effort fiat value)
    val = _usd_cents(row["sym"], row["amount"])
    if val > 0:
        wo._ledger(conn, -val, "payout", source="wallet",
                   note=f"sent {row['amount']} {row['sym']} to {row['to_addr']}",
                   prayer_id=prayer["id"])
    conn.commit()
    try:
        from cache import invalidate_prefix
        invalidate_prefix("wallets:bal:")   # balance changed
    except Exception:
        pass
    logger.info("wallet send %d broadcast (blessed): %s %s txid=%s",
                send_id, row["amount"], row["sym"], txid)
    return f"broadcast {row['amount']} {row['sym']} txid={txid}"


wo.register_executor("wallet_send", _exec_wallet_send)


@router.post("/api/wallets/sends/{send_id}/broadcast")
def wallets_send_broadcast(send_id: int, body: BroadcastIn):
    """Request a real broadcast. IRREVERSIBLE. This does NOT sign anything itself — it
    files a gated `wallet_send` prayer, and the transaction is only signed + broadcast
    once a HUMAN blesses that prayer in the God Console. A localhost/MCP caller (auth
    bypass) therefore cannot move real crypto with just confirm=true."""
    if not body.confirm:
        raise HTTPException(400, "confirm=true is required to request a real broadcast.")
    row = _get_send(send_id)
    if not row:
        raise HTTPException(404, "No such send.")
    if row["status"] not in ("proposed", "prepared"):
        raise HTTPException(400, f"Send is '{row['status']}', can't broadcast.")
    cost = _usd_cents(row["sym"], row["amount"])
    p = wo.pray("wallet_send",
                f"Broadcast {row['amount']} {row['sym']} to {row['to_addr'][:18]}…",
                detail=(f"Sign + broadcast {row['amount']} {row['sym']} to {row['to_addr']} — "
                        "IRREVERSIBLE real funds. Bless only if you initiated this."),
                cost_cents=cost,
                payload={"send_id": send_id})
    conn = get_conn()
    conn.execute("UPDATE wallet_sends SET status='pending_blessing', note=?, "
                 "updated_at=datetime('now') WHERE id=?",
                 (f"awaiting God Console blessing (prayer #{p['id']})", send_id))
    conn.commit()
    conn.close()
    return {"send": dict(_get_send(send_id)), "prayer": p,
            "note": "Filed for blessing — real crypto will NOT move until you bless this "
                    "prayer in the God Console."}


@router.post("/api/wallets/sends/{send_id}/cancel")
def wallets_send_cancel(send_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM wallet_sends WHERE id=?", (send_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "No such send.")
    conn.execute("UPDATE wallet_sends SET status='cancelled', "
                 "updated_at=datetime('now') WHERE id=?", (send_id,))
    conn.commit()
    row = conn.execute("SELECT * FROM wallet_sends WHERE id=?", (send_id,)).fetchone()
    conn.close()
    return {"send": dict(row)}
