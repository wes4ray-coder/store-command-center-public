"""JellyCoin — NFTs + the buddy-share (peers federation) compute economy.

Extracted verbatim from jellycoin.py to keep that module under the size budget.
These are leaf concerns of the chain: nothing else in jellycoin.py calls them
(only routers/jellycoin.py, routers/peers/* and world_sim do). The core chain
primitives (transfer/_wallet/_ensure/_tip_height/_sha256_hex + constants) live
in jellycoin.py; each function lazy-imports it so there is no import cycle
(jellycoin.py re-exports these names).
"""
import hashlib
import json
import time

from deps import get_conn, get_setting


# ── NFTs ─────────────────────────────────────────────────────────────────────
def mint_nft(owner: str, file_path: str, title: str, meta: dict | None = None) -> dict:
    """Mint an NFT from a real art file. Fee goes to the treasury; content hash on-chain."""
    import os
    import jellycoin
    if not os.path.isfile(file_path):
        raise ValueError(f"file not found: {file_path}")
    with open(file_path, "rb") as f:
        content_hash = hashlib.sha256(f.read()).hexdigest()
    conn = get_conn()
    try:
        jellycoin._ensure(conn)
        if conn.execute("SELECT 1 FROM jelly_nfts WHERE sha256=?", (content_hash,)).fetchone():
            raise ValueError("this exact artwork is already minted")
    finally:
        conn.close()
    if owner != jellycoin.TREASURY:   # treasury mints its own store art fee-free
        jellycoin.transfer(owner, jellycoin.TREASURY, jellycoin.NFT_MINT_FEE,
                           memo=f"NFT mint fee: {title[:60]}", kind="nft_fee")
    conn = get_conn()
    try:
        jellycoin._ensure(conn)
        token_id = "jnft_" + jellycoin._sha256_hex(f"{content_hash}:{owner}:{time.time()}".encode())[:24]
        conn.execute("INSERT INTO jelly_nfts (token_id,title,file_path,sha256,meta,owner,minted_height)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (token_id, title[:120], file_path, content_hash,
                      json.dumps(meta or {}), owner, jellycoin._tip_height(conn)))
        conn.commit()
        return {"ok": True, "token_id": token_id, "sha256": content_hash,
                "fee": jellycoin.NFT_MINT_FEE / jellycoin.UNIT}
    finally:
        conn.close()


def transfer_nft(token_id: str, frm: str, dst: str) -> dict:
    import jellycoin
    conn = get_conn()
    try:
        jellycoin._ensure(conn)
        row = conn.execute("SELECT * FROM jelly_nfts WHERE token_id=?", (token_id,)).fetchone()
        if not row:
            raise ValueError("unknown NFT")
        if row["owner"] != frm:
            raise ValueError(f"{frm} does not own this NFT")
        jellycoin._wallet(conn, dst)
        conn.execute("UPDATE jelly_nfts SET owner=? WHERE token_id=?", (dst, token_id))
        conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,?,?,0,?,?)",
                     (jellycoin._tip_height(conn), int(time.time()), frm, dst, "nft_transfer", token_id))
        conn.commit()
        return {"ok": True, "token_id": token_id, "owner": dst}
    finally:
        conn.close()


# ── buddy-share compute economy (peers federation) ───────────────────────────
# JLY is the working coin of the peer network: when a buddy's box does AI work
# for us (client.delegate_llm), our treasury PAYS their peer:<name> wallet; when
# a buddy runs a job on OUR AI helper (rpc_job), their wallet is CHARGED into the
# company wallet. Code reviews bill the same way (rpc_review charges, the
# requester's refresh credits) — a review is our LLM's time spent on their diff.
# A broke buddy is never blocked — the job runs comped (amount-0
# tx keeps the tab) because compute sharing must not break over play money.
PEER_BILLING_KEY = "jelly_peer_billing"            # settings toggle, default on
PEER_PRICE_KEY = "jelly_peer_job_price_jly"        # JLY per llm job, default 1
PEER_PRICE_DEFAULT = 1.0


def peer_billing_enabled() -> bool:
    # A JOINED node runs no chain of its own, so it has no ledger to bill on — the
    # economy it takes part in is the home node's, and that node does the billing.
    # Without this the transfers would just fail into "comped"/"treasury empty" on
    # every job, which reads like a broken wallet rather than a deliberate mode.
    import jellycoin
    if jellycoin.jelly_mode() == "joined":
        return False
    return str(get_setting(PEER_BILLING_KEY) or "1") in ("1", "true", "on")


def peer_job_price(kind: str = "llm") -> int:
    """Price in ujly. Embeddings are 1/10th of an llm job (they borrow, never swap);
    a code review ("review") bills like a full llm job — their diff, our model's time."""
    import jellycoin
    try:
        jly = float(get_setting(PEER_PRICE_KEY) or PEER_PRICE_DEFAULT)
    except Exception:
        jly = PEER_PRICE_DEFAULT
    price = int(max(0.0, jly) * jellycoin.UNIT)
    return price // 10 if kind == "embedding" else price


def peer_job_charge(peer_name: str, kind: str = "llm") -> dict:
    """Inbound: a buddy used OUR AI helper. Charge their wallet → company (or comp)."""
    import jellycoin
    if not peer_billing_enabled():
        return {"billed": False, "reason": "billing off"}
    price = peer_job_price(kind)
    wname = f"peer:{peer_name}"
    if price <= 0:
        return {"billed": False, "reason": "free"}
    try:
        jellycoin.transfer(wname, jellycoin.COMPANY, price, memo=f"{kind} job on our node", kind="compute")
        return {"billed": True, "amount": price}
    except ValueError:                      # broke buddy → job still runs, tab recorded
        conn = get_conn()
        try:
            jellycoin._ensure(conn)
            jellycoin._wallet(conn, wname, kind="peer")
            conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,?,?,0,?,?)",
                         (jellycoin._tip_height(conn), int(time.time()), wname, jellycoin.COMPANY,
                          "compute_comped", f"{kind} job comped (insufficient JLY)"))
            conn.commit()
        finally:
            conn.close()
        return {"billed": False, "reason": "comped"}


def peer_job_credit(peer_name: str, kind: str = "llm") -> dict:
    """Outbound: a buddy's box did AI work FOR us. Treasury pays their peer wallet."""
    import jellycoin
    if not peer_billing_enabled():
        return {"billed": False, "reason": "billing off"}
    price = peer_job_price(kind)
    if price <= 0:
        return {"billed": False, "reason": "free"}
    try:
        jellycoin.transfer(jellycoin.TREASURY, f"peer:{peer_name}", price,
                           memo=f"{kind} job lent to us — thanks!", kind="compute")
        return {"billed": True, "amount": price}
    except ValueError:
        return {"billed": False, "reason": "treasury empty"}
