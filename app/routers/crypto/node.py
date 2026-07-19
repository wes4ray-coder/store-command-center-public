"""Bitcoin (regtest) node + coin market stats + the gated key-backup export.

The backup zip CONTAINS PRIVATE KEYS (the BIP39 master seed + every decrypted
crypto/trading secret) — its export is gated behind a HUMAN-blessed `secret_export`
prayer in the God Console; a localhost/MCP caller that bypasses auth cannot
self-approve it. That gate is preserved here verbatim.
"""
import io
import json as _json
import os
import re as _re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from deps import *          # get_conn, get_setting, orch, _call_lmstudio, _dec, logger
from services import *      # (kept consistent with sibling routers)

from ._base import router, BTC_RPC_URL, BTC_WALLET, FT_STRATS, FT_DRAFTS, _BACKUP_PREFIXES


# ── bitcoin RPC ───────────────────────────────────────────────────────────────
def _btc_rpc(method: str, params: Optional[list] = None, wallet: Optional[str] = None,
             timeout: int = 15):
    """JSON-RPC call against the local regtest bitcoind. Raises RuntimeError with the
    node's own message on RPC errors (bitcoind answers errors with a JSON body)."""
    user = get_setting("btc_rpc_user", "") or ""
    pw   = get_setting("btc_rpc_pass", "") or ""
    if not user or not pw:
        raise RuntimeError("btc_rpc_user / btc_rpc_pass not set — add them in the Crypto tab settings.")
    url = BTC_RPC_URL + (f"/wallet/{wallet}" if wallet else "")
    r = httpx.post(url, json={"jsonrpc": "1.0", "id": "store", "method": method,
                              "params": params or []},
                   auth=(user, pw), timeout=timeout)
    if r.status_code in (401, 403):
        raise RuntimeError("bitcoind rejected the RPC credentials (401/403).")
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"bitcoind returned non-JSON (HTTP {r.status_code}).")
    if data.get("error"):
        err = data["error"]
        raise RuntimeError(f"{method}: {err.get('message', err)} (code {err.get('code')})")
    return data.get("result")


def _btc_balances():
    """Core v25+ dropped balance fields from getwalletinfo — use getbalances."""
    mine = (_btc_rpc("getbalances", wallet=BTC_WALLET) or {}).get("mine") or {}
    return {"balance": mine.get("trusted"), "immature": mine.get("immature"),
            "unconfirmed": mine.get("untrusted_pending")}


def _ensure_btc_wallet():
    """Make sure wallet 'store' exists and is loaded. Handles the whole matrix of
    'already exists' / 'already loaded' / 'not found' RPC errors idempotently."""
    try:
        if BTC_WALLET in (_btc_rpc("listwallets") or []):
            return
    except RuntimeError:
        pass
    try:
        _btc_rpc("loadwallet", [BTC_WALLET])
        return
    except RuntimeError as e:
        msg = str(e).lower()
        if "already loaded" in msg:
            return
        # "not found" / "does not exist" → fall through to create
    try:
        _btc_rpc("createwallet", [BTC_WALLET])
    except RuntimeError as e:
        msg = str(e).lower()
        if "already exists" not in msg and "already loaded" not in msg:
            raise
        try:
            _btc_rpc("loadwallet", [BTC_WALLET])
        except RuntimeError:
            pass  # exists + loaded — fine


# ── 📊 coin market stats (CoinGecko, free/no key, TTL 120s) ──────────────────
@router.get("/api/crypto/stats")
def crypto_stats():
    from cache import cached

    def _fetch():
        import requests
        coins_raw = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 20,
                    "page": 1, "price_change_percentage": "24h,7d"},
            timeout=15).json()
        coins = [{
            "rank":   c.get("market_cap_rank"),
            "id":     c.get("id"),
            "symbol": (c.get("symbol") or "").upper(),
            "name":   c.get("name"),
            "image":  c.get("image"),
            "price":  c.get("current_price"),
            "chg24h": c.get("price_change_percentage_24h_in_currency"),
            "chg7d":  c.get("price_change_percentage_7d_in_currency"),
            "mcap":   c.get("market_cap"),
        } for c in coins_raw] if isinstance(coins_raw, list) else []
        trending = []
        try:
            tr = requests.get("https://api.coingecko.com/api/v3/search/trending",
                              timeout=15).json()
            for it in (tr.get("coins") or [])[:10]:
                item = it.get("item") or {}
                trending.append({"symbol": (item.get("symbol") or "").upper(),
                                 "name": item.get("name"),
                                 "rank": item.get("market_cap_rank"),
                                 "thumb": item.get("thumb")})
        except Exception:
            pass  # trending is a bonus; the coin table is the payload
        return {"coins": coins, "trending": trending, "fetched_at": datetime.now().isoformat(timespec="seconds")}

    try:
        return cached("crypto:stats", 120, _fetch)
    except Exception as e:
        return {"error": f"CoinGecko unreachable: {str(e)[:180]}", "coins": [], "trending": []}


# ── ⛓️ nodes ──────────────────────────────────────────────────────────────────
# Honest catalog: your spendable coins live as REAL mainnet light-wallets in the
# Wallets tab (no node, no download). Running your OWN full node is optional and
# only about self-sovereignty/learning — never home-mining income.
NODE_CATALOG = [
    {"key": "monero",   "name": "Monero", "installed": False,
     "note": "Real XMR wallet is live in the Wallets tab. The one coin still CPU-minable "
             "at home — but a desktop CPU earns pennies/day. xmrig is installed below "
             "(off); point it at your XMR address. A full node needs ~80 GB pruned."},
    {"key": "litecoin", "name": "Litecoin", "installed": False,
     "note": "Real LTC wallet is live in the Wallets tab. Scrypt ASICs mine LTC; a "
             "GPU/CPU earns effectively nothing. A pruned full node is optional."},
    {"key": "dogecoin", "name": "Dogecoin", "installed": False,
     "note": "Real DOGE wallet is live in the Wallets tab. Merge-mined with Litecoin by "
             "ASICs — home mining isn't income."},
    {"key": "ethereum", "name": "Ethereum", "installed": False,
     "note": "Real ETH wallet is live in the Wallets tab (via public RPC). Proof-of-stake "
             "— no mining at all; validating needs 32 ETH staked. A full node needs 600 GB+."},
    {"key": "kaspa",    "name": "Kaspa", "installed": False,
     "note": "Real KAS wallet is live in the Wallets tab. GPU-minable in theory but ASICs "
             "dominate; a home GPU nets cents/day minus power."},
]


@router.get("/api/crypto/nodes")
def crypto_nodes():
    return {"catalog": NODE_CATALOG,
            "note": "Spendable balances live in the Wallets tab as real mainnet "
                    "light-wallets — no local node or blockchain download required."}


# ── 🔑 key backup (PRIVATE KEYS INSIDE) ──────────────────────────────────────
@router.post("/api/crypto/backup/request")
def crypto_backup_request():
    """Step 1 of the secret export: file a gated `secret_export` prayer. The backup zip
    (which contains the BIP39 master seed + all decrypted secrets) only unlocks after a
    HUMAN blesses this in the God Console — a localhost/MCP caller that bypasses auth
    cannot self-approve a secret export."""
    import world_ops as wo
    p = wo.pray("secret_export",
                "Export crypto secret backup (master seed + keys)",
                detail=("Streams the BIP39 master recovery phrase and every decrypted "
                        "crypto/trading secret. Bless ONLY if you personally requested a backup."),
                cost_cents=0)
    return {"prayer": p,
            "note": "Bless this in the God Console, then GET /api/crypto/backup?prayer_id=<id> "
                    "to download once."}


def _backup_gate(prayer_id: int):
    """Return the blessed, not-yet-consumed secret_export prayer row, or raise 403."""
    import world_ops as wo
    conn = get_conn()
    try:
        wo.ensure(conn)
        row = None
        if prayer_id:
            row = conn.execute("SELECT * FROM world_prayers WHERE id=? AND kind='secret_export'",
                               (prayer_id,)).fetchone()
        if not row or row["status"] not in ("approved", "done"):
            raise HTTPException(403,
                "Secret export must be blessed first: POST /api/crypto/backup/request, "
                "approve the prayer in the God Console, then retry with ?prayer_id=<id>.")
        return dict(row)
    finally:
        conn.close()


def _backup_consume(prayer_id: int):
    """Single-use + audit: mark the blessing consumed and log the export."""
    conn = get_conn()
    try:
        conn.execute("UPDATE world_prayers SET status='consumed', "
                     "result=COALESCE(result,'') || ' | exported ' || datetime('now') "
                     "WHERE id=?", (prayer_id,))
        conn.execute("INSERT INTO world_ops_ledger (amount_cents,kind,source,note,prayer_id) "
                     "VALUES (0,'audit','secret_export','crypto secret backup downloaded',?)",
                     (prayer_id,))
        conn.commit()
    finally:
        conn.close()
    logger.warning("crypto secret backup EXPORTED (blessed prayer #%s)", prayer_id)


@router.get("/api/crypto/backup")
def crypto_backup(prayer_id: int = 0):
    """One zip with everything needed to reconstruct the crypto setup:
    the BIP39 master RECOVERY PHRASE (controls every coin's real funds), the
    btc_/ft_/xmr_/rh_/money_ settings (decrypted), and every freqtrade strategy.

    GATED: requires ?prayer_id of a blessed (single-use) secret_export prayer —
    see POST /api/crypto/backup/request."""
    _backup_gate(prayer_id)
    buf = io.BytesIO()
    manifest = {"created_at": datetime.now().isoformat(timespec="seconds"),
                "warning": "CONTAINS PRIVATE KEYS AND CREDENTIALS — store offline, never share.",
                "contents": []}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # (a) the real light-wallet master seed (BIP39) + derived addresses.
        # THIS is the master key to every coin balance — recover in any BIP39 wallet.
        try:
            m = get_setting("wallet_mnemonic", "") or ""
            if m:
                import wallet_lib
                addrs = wallet_lib.derive_all(m)
                addrs["XMR"] = wallet_lib.derive_xmr_primary(m)
                z.writestr("wallet/RECOVERY_PHRASE.txt",
                           "Acme Store — master wallet recovery phrase (BIP39, 24 words)\n"
                           "This ALONE controls every coin's real funds. Import into any BIP39\n"
                           "wallet (Electrum, Feather, MetaMask, etc.). Keep offline; never share.\n\n"
                           + m + "\n\n"
                           + "\n".join(f"{k}: {v}" for k, v in addrs.items()) + "\n")
                manifest["contents"].append("wallet/RECOVERY_PHRASE.txt (BIP39 seed — controls real funds)")
            else:
                z.writestr("wallet/NO_SEED.txt", "No wallet seed yet — open the Wallets tab once to create it.")
                manifest["contents"].append("wallet seed NOT YET CREATED")
        except Exception as e:
            z.writestr("wallet/SEED_ERROR.txt", f"Could not export seed: {e}")
            manifest["contents"].append("wallet seed export FAILED")
        # (b) crypto/trading settings rows (decrypted values)
        settings = {}
        conn = get_conn()
        for r in conn.execute("SELECT key,value FROM settings").fetchall():
            if str(r["key"]).startswith(_BACKUP_PREFIXES):
                try:
                    settings[r["key"]] = _dec(r["value"])
                except Exception:
                    settings[r["key"]] = r["value"]
        conn.close()
        z.writestr("settings.json", _json.dumps(settings, indent=2))
        manifest["contents"].append(f"settings.json ({len(settings)} keys)")
        # (c) freqtrade strategies + drafts
        for label, d in (("strategies", FT_STRATS), ("strategies_drafts", FT_DRAFTS)):
            if d.is_dir():
                n = 0
                for f in sorted(d.iterdir()):
                    if f.is_file():
                        try:
                            z.writestr(f"freqtrade/{label}/{f.name}", f.read_bytes())
                            n += 1
                        except Exception:
                            pass
                manifest["contents"].append(f"freqtrade/{label}/ ({n} files)")
        z.writestr("MANIFEST.json", _json.dumps(manifest, indent=2))
    buf.seek(0)
    _backup_consume(prayer_id)   # single-use blessing + audit-log the export
    fname = f"crypto-backup-{datetime.now().strftime('%Y-%m-%d')}.zip"
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})
