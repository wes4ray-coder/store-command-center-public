"""wallets — Monero: bring the wallet online (open/restore), start the wallet daemon
from the UI, and report live balance via monero-wallet-rpc (derived address fallback)."""
import json

from fastapi import APIRouter

from deps import *
from services import *

import wallet_lib as wl

from ._base import router, _ensure_seed, _addresses, _xmr_rpc


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
