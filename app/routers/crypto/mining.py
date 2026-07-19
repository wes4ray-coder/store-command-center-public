"""Monero CPU mining (official xmrig, installed but OFF by default)."""
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

from ._base import router, _set_setting


# ── ⛏️ Monero CPU mining (official xmrig, installed but OFF by default) ────────
XMRIG_DIR    = Path.home() / "crypto"
XMRIG_BIN    = XMRIG_DIR / "xmrig-dist" / "xmrig"
XMRIG_CFG    = XMRIG_DIR / "xmrig-config.json"
XMRIG_LOG    = XMRIG_DIR / "xmrig.log"
DEFAULT_POOL = "gulf.moneroocean.stream:10128"   # MoneroOcean auto-switches algos


def _xmr_payout() -> str:
    """The Monero address xmrig mines to: explicit xmr_wallet setting, else the
    real XMR receive address derived from the wallet seed."""
    w = (get_setting("xmr_wallet", "") or "").strip()
    if w:
        return w
    try:
        import wallet_lib
        m = get_setting("wallet_mnemonic", "") or ""
        if m:
            return wallet_lib.derive_xmr_primary(m)
    except Exception as e:
        logger.warning("xmr payout derive failed: %s", e)
    return ""


def _xmrig_running() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "xmrig-dist/xmrig"],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


@router.get("/api/crypto/mining")
def crypto_mining():
    return {
        "installed": XMRIG_BIN.exists(),
        "running":   _xmrig_running(),
        "wallet":    _xmr_payout(),
        "pool":      get_setting("xmr_pool", DEFAULT_POOL),
        "threads":   int(get_setting("xmr_threads", "0") or 0),  # 0 = auto
        "note":      "CPU mining on this shared box earns pennies/day and adds heat/load. "
                     "Off by default — this is real mining to your real XMR address.",
    }


class MiningCfg(BaseModel):
    pool: Optional[str] = None
    wallet: Optional[str] = None
    threads: Optional[int] = None


@router.post("/api/crypto/mining/config")
def crypto_mining_config(cfg: MiningCfg):
    if cfg.pool is not None:
        _set_setting("xmr_pool", cfg.pool.strip() or DEFAULT_POOL)
    if cfg.wallet is not None:
        _set_setting("xmr_wallet", cfg.wallet.strip())
    if cfg.threads is not None:
        _set_setting("xmr_threads", str(max(0, min(int(cfg.threads), 8))))
    return crypto_mining()


@router.post("/api/crypto/mining/{action}")
def crypto_mining_action(action: str):
    if action not in ("start", "stop"):
        raise HTTPException(400, "action must be start or stop")
    if action == "stop":
        subprocess.run(["pkill", "-f", "xmrig-dist/xmrig"], capture_output=True)
        return {"ok": True, "running": False}
    # start
    if not XMRIG_BIN.exists():
        raise HTTPException(400, "xmrig binary not installed")
    payout = _xmr_payout()
    if not payout:
        raise HTTPException(400, "no XMR address — set one in Wallets or the xmr_wallet setting")
    if _xmrig_running():
        return {"ok": True, "running": True, "note": "already running"}
    threads = int(get_setting("xmr_threads", "0") or 0)
    cpu = {"enabled": True} if threads == 0 else {"enabled": True, "max-threads-hint": min(threads * 25, 100)}
    conf = {
        "autosave": False, "cpu": cpu,
        "pools": [{"url": get_setting("xmr_pool", DEFAULT_POOL), "user": payout,
                   "pass": get_setting("xmr_pool_pass", "x"),   # pool worker label, not a secret
                   "keepalive": True, "tls": False}],
    }
    XMRIG_CFG.write_text(_json.dumps(conf, indent=2))
    with open(XMRIG_LOG, "ab") as log:
        subprocess.Popen([str(XMRIG_BIN), "--config", str(XMRIG_CFG)],
                         stdout=log, stderr=log, cwd=str(XMRIG_DIR),
                         start_new_session=True)
    return {"ok": True, "running": True, "wallet": payout}
