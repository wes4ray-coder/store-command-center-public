"""Shared base for the wallets package: the single router, the idempotent schema
(run ONCE at import), the seed lock, and the cross-domain wallet helpers (mnemonic
storage, seed generation, address derivation, Monero RPC).

Split out of the former monolithic ``routers/wallets.py``. The shared ``APIRouter``,
the one-time ``_ensure_schema()`` side effect, and the helpers used by two or more
submodules live here so there are no import cycles between the submodules.

SECURITY: the mnemonic controls REAL funds. ``_store_mnemonic`` encrypts it at rest
when `wallet_mnemonic` is in SECRET_KEYS and it is NEVER logged. The send-gating that
protects real crypto lives in the ``sends`` submodule."""
import json

from fastapi import APIRouter

from deps import *          # get_conn, get_setting, logger, _enc, _is_secret, httpx, ...
from services import *      # (kept consistent with sibling routers)

import wallet_lib as wl

router = APIRouter()

XMR_RPC_URL = "http://127.0.0.1:18083/json_rpc"   # monero-wallet-rpc, when running

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


# ── Monero JSON-RPC (wallet-rpc when available) ───────────────────────────────
def _xmr_rpc(method: str, params: Optional[dict] = None, timeout: float = 8.0):
    r = httpx.post(XMR_RPC_URL, timeout=timeout,
                   json={"jsonrpc": "2.0", "id": "0", "method": method,
                         "params": params or {}})
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"])[:160])
    return data.get("result") or {}
