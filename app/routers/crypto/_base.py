"""Shared base for the crypto package: the single router, the cross-domain
constants/contracts, the idempotent schema, the shared docker/settings helpers,
and the reserved-keys settings endpoints.

Imported first (via ``__init__``) so ``_ensure_schema()`` runs EXACTLY ONCE,
before any submodule's ``@router.*`` routes are registered.
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
from config import _env

router = APIRouter()

# ── constants / contracts ─────────────────────────────────────────────────────
BTC_RPC_URL   = "http://127.0.0.1:8332"
BTC_CONTAINER = "crypto-bitcoind"
BTC_WALLET    = "store"

FT_API_URL    = "http://127.0.0.1:8898"   # 8899 is taken by searxng
FT_CONTAINER  = "crypto-freqtrade"
FT_USER_DATA  = Path(_env("STORE_FT_USER_DATA", "/home/user/crypto/freqtrade/user_data"))
FT_STRATS     = FT_USER_DATA / "strategies"
FT_DRAFTS     = FT_USER_DATA / "strategies_drafts"

# Only these containers may ever be touched by this router (allowlist).
_ALLOWED_CONTAINERS = {BTC_CONTAINER, FT_CONTAINER}

# Settings keys this router owns. Secrets are masked on read (last 4 chars only).
CRYPTO_SETTING_KEYS = [
    "btc_rpc_user", "btc_rpc_pass", "ft_api_user", "ft_api_pass",
    "xmr_wallet", "rh_username", "rh_password", "rh_mfa_secret",
    "stocks_watchlist", "kraken_api_key", "kraken_api_secret",
]
_CRYPTO_SECRETS = {"btc_rpc_pass", "ft_api_pass", "rh_password", "rh_mfa_secret",
                   "kraken_api_key", "kraken_api_secret"}
# settings.key prefixes included in the key backup zip
_BACKUP_PREFIXES = ("btc_", "ft_", "xmr_", "rh_", "money_", "kraken_", "jelly_", "pearl_")


# ── schema (kept here to stay decoupled from db.py, like homelab.py) ──────────
def _ensure_schema():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS crypto_strategy_drafts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT,
        goal       TEXT,
        code       TEXT,
        status     TEXT DEFAULT 'proposed',
        notes      TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS crypto_backtests (
        strategy_id   INTEGER PRIMARY KEY,
        metrics       TEXT,
        profit_pct    REAL,
        profit_factor REAL,
        sharpe        REAL,
        passed        INTEGER DEFAULT 0,
        created_at    TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()

_ensure_schema()


def _set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


# ── docker helpers (same socket-forcing gotcha as homelab.py) ─────────────────
def _docker_env() -> dict:
    """Force the SYSTEM docker socket — the CLI's default context may be the empty
    Docker Desktop one. Overridable via the `docker_host` setting."""
    env = dict(os.environ)
    env["DOCKER_HOST"] = get_setting("docker_host", "") or "unix:///var/run/docker.sock"
    return env


def _container_status(name: str) -> str:
    """running | exited | created | ... | not-found | docker-error."""
    if name not in _ALLOWED_CONTAINERS:
        raise HTTPException(400, f"Container '{name}' is not managed here.")
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", name],
                           capture_output=True, text=True, timeout=10, env=_docker_env())
    except Exception:
        return "docker-error"
    if r.returncode != 0:
        return "not-found"
    return r.stdout.strip() or "unknown"


# ── ⚙️ crypto settings (reserved keys only) ───────────────────────────────────
@router.get("/api/crypto/settings")
def get_crypto_settings():
    out = {}
    for k in CRYPTO_SETTING_KEYS:
        v = get_setting(k, "") or ""
        if k in _CRYPTO_SECRETS and v:
            out[k] = ("•" * max(len(v) - 4, 4)) + v[-4:]
        else:
            out[k] = v
    return {"settings": out, "secret_keys": sorted(_CRYPTO_SECRETS)}


@router.post("/api/crypto/settings")
def set_crypto_settings(body: dict):
    """Set any of the reserved crypto/stocks settings keys. Send only the keys you
    want to change — the UI leaves secret fields blank unless re-entered."""
    bad = [k for k in body if k not in CRYPTO_SETTING_KEYS]
    if bad:
        raise HTTPException(400, f"Unknown key(s): {', '.join(bad)}")
    saved = []
    for k, v in body.items():
        if v is None:
            continue
        _set_setting(k, str(v).strip())
        saved.append(k)
    # bust caches + cached logins that depend on these values
    from cache import invalidate_prefix
    from .trading import _ft_jwt
    from .stocks import _rh_state
    invalidate_prefix("crypto:")
    _ft_jwt["token"] = None
    _rh_state["logged_in"] = False
    return {"ok": True, "saved": saved}
