"""Wallets — REAL mainnet light-wallets (receive + monitor). One BIP39 seed drives
deterministic addresses for BTC/LTC/DOGE/ETH/KAS (app/wallet_lib.py); Monero gets a
primary address from the same seed, with live balance only when monero-wallet-rpc is
up. No node, no blockchain download — balances come from public explorers.

SECURITY: the mnemonic controls REAL funds. It is stored in the settings table under
`wallet_mnemonic` (encrypted at rest when that key is in SECRET_KEYS — see
app/crypto.py) and is NEVER logged. Receiving is always safe. SENDING IS DOUBLE-GATED:
/api/wallets/send queues a `wallet_sends` row ('proposed'); /prepare dry-runs the fee;
/broadcast does NOT sign directly — it files a `wallet_send` prayer in the God Console
and the transaction is only signed + broadcast once a HUMAN blesses that prayer. A
localhost/MCP caller (which bypasses auth) therefore cannot move real crypto on its own.
"""
import json

from fastapi import APIRouter

from deps import *          # get_conn, get_setting, logger, _enc, _is_secret, httpx, ...
from services import *      # (kept consistent with sibling routers)

import wallet_lib as wl
import world_ops as wo

router = APIRouter()

XMR_RPC_URL = "http://127.0.0.1:18083/json_rpc"   # monero-wallet-rpc, when running

# Where "view on explorer" links point (public, address-level; XMR has none — privacy).
EXPLORER_URL = {
    "BTC":  "https://blockstream.info/address/{a}",
    "LTC":  "https://litecoinspace.org/address/{a}",
    "DOGE": "https://blockchair.com/dogecoin/address/{a}",
    "ETH":  "https://etherscan.io/address/{a}",
    "KAS":  "https://explorer.kaspa.org/addresses/{a}",
}

_seed_lock = threading.Lock()   # so two concurrent first-requests can't mint two seeds


# ── schema (kept here to stay decoupled from db.py, like crypto.py) ───────────
def _ensure_schema():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS wallet_sends (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        sym        TEXT,
        to_addr    TEXT,
        amount     REAL,
        status     TEXT DEFAULT 'proposed',
        note       TEXT DEFAULT '',
        txid       TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS wallet_meta (
        k TEXT PRIMARY KEY,
        v TEXT
    );
    """)
    conn.commit()
    conn.close()

_ensure_schema()


# ── small helpers ─────────────────────────────────────────────────────────────
def _meta_get(k: str, default: str = "") -> str:
    conn = get_conn()
    row = conn.execute("SELECT v FROM wallet_meta WHERE k=?", (k,)).fetchone()
    conn.close()
    return row["v"] if row and row["v"] is not None else default


def _meta_set(k: str, v: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO wallet_meta (k,v) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()


def _store_mnemonic(mnem: str):
    """Persist the mnemonic in settings — encrypted at rest when `wallet_mnemonic`
    is registered in SECRET_KEYS (app/crypto.py). NEVER log the value."""
    val = _enc(mnem) if _is_secret("wallet_mnemonic") else mnem
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                 ("wallet_mnemonic", val))
    conn.commit()
    conn.close()


def _ensure_seed() -> str:
    """Return the plaintext mnemonic, generating (and storing) a fresh 24-word one
    on first use. Lock guards against two requests generating two seeds."""
    mnem = get_setting("wallet_mnemonic", "") or ""
    if mnem:
        return mnem
    with _seed_lock:
        mnem = get_setting("wallet_mnemonic", "") or ""   # re-check under the lock
        if mnem:
            return mnem
        from bip_utils import Bip39MnemonicGenerator, Bip39WordsNum
        mnem = str(Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_24))
        _store_mnemonic(mnem)
        logger.info("generated wallet seed")   # the mnemonic itself is NEVER logged
        return mnem


def _addresses(seed: str) -> dict:
    """{sym: address} for every coin incl. XMR. Derivation (PBKDF2 etc.) is pure CPU
    but not free — cache it; addresses are public, the seed never enters the cache."""
    from cache import cached

    def derive():
        addrs = wl.derive_all(seed)
        try:
            addrs["XMR"] = wl.derive_xmr_primary(seed)
        except Exception as e:
            logger.warning("XMR address derivation failed: %s", e)
            addrs["XMR"] = ""
        return addrs

    return cached("wallets:addrs", 3600, derive)


# ── wallets overview ──────────────────────────────────────────────────────────
@router.get("/api/wallets")
def wallets_overview():
    """All coins: address + live balance (explorer-backed, cached ~60s). A dead
    explorer yields an error string on that coin — never a 500."""
    from cache import cached
    seed = _ensure_seed()
    addrs = _addresses(seed)

    def _bal(sym, addr):
        return cached(f"wallets:bal:{sym}:{addr}", 60, lambda: wl.balance(sym, addr))

    # Fetch the 5 queryable balances in parallel — serial worst-case on dead
    # explorers would stall the tab for over a minute.
    import concurrent.futures as _cf
    balances = {}
    q = [s for s in wl.COINS if s != "XMR" and addrs.get(s)]
    with _cf.ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_bal, s, addrs[s]): s for s in q}
        for f in _cf.as_completed(futs):
            sym = futs[f]
            try:
                balances[sym] = f.result()
            except Exception as e:            # belt & braces — wl.balance never raises
                balances[sym] = {"confirmed": None, "error": str(e)[:120]}

    coins = []
    for sym in wl.COINS:
        addr = addrs.get(sym, "")
        if sym == "XMR":
            b = {"confirmed": None,
                 "error": "balance needs the Monero wallet daemon (privacy chain — "
                          "no public address lookup)"}
        else:
            b = balances.get(sym, {"confirmed": None, "error": "no address"})
        coins.append({
            "sym": sym,
            "name": wl.COIN_NAME[sym],
            "address": addr,
            "balance": b.get("confirmed"),
            "decimals": wl.COIN_DECIMALS[sym],
            "explorer": EXPLORER_URL[sym].format(a=addr) if sym in EXPLORER_URL and addr else "",
            "error": b.get("error"),
        })
    return {"coins": coins, "seed_backed_up": _meta_get("seed_ack") == "1"}


# ── seed backup / restore ─────────────────────────────────────────────────────
@router.get("/api/wallets/seed")
def wallets_seed():
    """One-time backup reveal. The app is auth-guarded; still, treat this response
    like cash — it IS the wallet."""
    seed = _ensure_seed()
    return {
        "mnemonic": seed,
        "addresses": _addresses(seed),
        "warning": ("These 24 words ARE your wallet — anyone with them can take every "
                    "coin, on every chain, forever. Write them on paper, store them "
                    "offline, never screenshot or paste them anywhere. The Store cannot "
                    "recover them for you if this database is lost."),
    }


@router.post("/api/wallets/seed/ack")
def wallets_seed_ack():
    """User confirmed they saved the recovery phrase."""
    _meta_set("seed_ack", "1")
    return {"ok": True, "seed_backed_up": True}


class SeedImportIn(BaseModel):
    mnemonic: str


@router.post("/api/wallets/seed/import")
def wallets_seed_import(body: SeedImportIn):
    """Replace the wallet with the user's own BIP39 seed (restore). Resets the
    backup acknowledgement — it's a different wallet now."""
    from bip_utils import Bip39MnemonicValidator
    from cache import invalidate_prefix
    mnem = " ".join((body.mnemonic or "").strip().lower().split())
    if not mnem:
        raise HTTPException(400, "Mnemonic is required.")
    if not Bip39MnemonicValidator().IsValid(mnem):
        raise HTTPException(400, "Not a valid BIP39 mnemonic — check the words, order "
                                 "and count (12/15/18/21/24 words).")
    _store_mnemonic(mnem)
    _meta_set("seed_ack", "0")
    invalidate_prefix("wallets:")   # old addresses + balances are for the old wallet
    logger.info("wallet seed imported (replaced)")   # never the words themselves
    return {"ok": True, "addresses": _addresses(mnem), "seed_backed_up": False}


# ── gated sends (queue only — NO signing, NO broadcast in this version) ───────
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


# ── Monero (wallet-rpc when available, derived address otherwise) ─────────────
def _xmr_rpc(method: str, params: Optional[dict] = None, timeout: float = 8.0):
    r = httpx.post(XMR_RPC_URL, timeout=timeout,
                   json={"jsonrpc": "2.0", "id": "0", "method": method,
                         "params": params or {}})
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"])[:160])
    return data.get("result") or {}


@router.post("/api/wallets/xmr/setup")
def wallets_xmr_setup():
    """Bring the Monero wallet online in monero-wallet-rpc: open it if it exists,
    else restore it from the seed-derived keys (address+spend+view). One-time; after
    this, /api/wallets/xmr shows balance. Needs the daemon reachable."""
    seed = _ensure_seed()
    keys = wl.xmr_keys(seed)
    try:
        _xmr_rpc("open_wallet", {"filename": "store", "password": ""}, timeout=30)
        opened = True
    except Exception:
        opened = False
    if not opened:
        # restore height = current chain tip (fresh wallet, no prior funds to scan)
        rh = 0
        try:
            r = httpx.post("http://node.monerodevs.org:18089/get_info", timeout=10).json()
            rh = int(r.get("height", 0)) - 10
        except Exception:
            rh = 3300000
        try:
            _xmr_rpc("generate_from_keys", {
                "filename": "store", "address": keys["address"],
                "spendkey": keys["spend"], "viewkey": keys["view"],
                "password": "", "restore_height": max(rh, 0), "autosave_current": True,
            }, timeout=90)
        except Exception as e:
            raise HTTPException(502, f"Monero wallet restore failed: {str(e)[:200]}")
    try:
        addr = _xmr_rpc("get_address").get("address", "")
    except Exception as e:
        raise HTTPException(502, f"wallet opened but get_address failed: {str(e)[:160]}")
    return {"ok": True, "address": addr, "matches_derived": addr == keys["address"],
            "note": "Wallet online. Balance refreshes as the remote node syncs the view key."}


from config import _env
_MONERO_RPC_BIN = _env("STORE_MONERO_RPC_BIN", "/home/user/crypto/monero-dist/monero-wallet-rpc")
_MONERO_WALLET  = _env("STORE_MONERO_WALLET",  "/home/user/crypto/monero-wallets/store")
_XMR_DAEMON     = _env("STORE_XMR_DAEMON",     "node.monerodevs.org:18089")
_MONERO_LOG     = _env("STORE_MONERO_LOG",     "/home/user/crypto/monero-wallet-rpc.log")


@router.post("/api/wallets/xmr/daemon/start")
def wallets_xmr_daemon_start():
    """Bring the Monero wallet daemon up from the web UI (no terminal needed).
    Prefers the managed systemd user service; falls back to launching the official
    binary directly. Idempotent — a no-op if it's already answering."""
    import time
    try:
        _xmr_rpc("get_version", timeout=4)
        return {"ok": True, "already_running": True}
    except Exception:
        pass
    started_via = None
    try:
        r = subprocess.run(["systemctl", "--user", "start", "monero-wallet-rpc"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            started_via = "systemd"
    except Exception:
        pass
    if not started_via:
        try:
            with open(_MONERO_LOG, "ab") as log:
                subprocess.Popen(
                    [_MONERO_RPC_BIN, "--rpc-bind-port", "18083",
                     "--rpc-bind-ip", "127.0.0.1", "--disable-rpc-login",
                     "--daemon-address", _XMR_DAEMON, "--trusted-daemon",
                     "--wallet-file", _MONERO_WALLET, "--password", "",
                     "--log-file", _MONERO_LOG, "--log-level", "1"],
                    stdout=log, stderr=log, start_new_session=True)
            started_via = "direct"
        except Exception as e:
            raise HTTPException(500, f"Could not start the Monero daemon: {str(e)[:160]}")
    for _ in range(12):
        time.sleep(1)
        try:
            _xmr_rpc("get_version", timeout=4)
            return {"ok": True, "started_via": started_via}
        except Exception:
            continue
    return {"ok": False, "started_via": started_via,
            "note": "daemon launched but RPC not answering yet — give it a few seconds"}


@router.get("/api/wallets/xmr")
def wallets_xmr():
    """Monero status: live via monero-wallet-rpc when it's up, else the derived
    primary address (receive/mining payout still work). Never 500s."""
    try:
        addr = _xmr_rpc("get_address").get("address", "")
        bal = _xmr_rpc("get_balance")
        atomic = 10 ** wl.COIN_DECIMALS["XMR"]
        return {"configured": True, "address": addr,
                "balance": (bal.get("balance") or 0) / atomic,
                "unlocked": (bal.get("unlocked_balance") or 0) / atomic}
    except Exception:
        try:
            addr = _addresses(_ensure_seed()).get("XMR", "")
        except Exception as e:
            logger.warning("XMR fallback address failed: %s", e)
            addr = ""
        return {"configured": False, "address": addr,
                "note": "Monero wallet daemon not reachable — receive address shown; "
                        "balance/send need the daemon."}
