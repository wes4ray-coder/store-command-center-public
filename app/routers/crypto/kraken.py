"""Kraken account: real balances (read-only display) + the sync that copies the
Kraken key/secret into FreqTrade's config (dry_run STAYS TRUE — going live is a
separate, deliberate flip of dry_run)."""
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

from ._base import router, FT_USER_DATA, FT_CONTAINER, _docker_env


# ── 🐙 Kraken account (real balances + trading readiness) ─────────────────────
# Kraken uses weird asset codes (XXBT=BTC, XETH=ETH, ZUSD=USD). Map the common ones
# for display; unmapped assets show their raw code.
_KRAKEN_ASSET = {
    "XXBT": "BTC", "XBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC",
    "XXDG": "DOGE", "XDG": "DOGE", "ZUSD": "USD", "ZEUR": "EUR", "XXMR": "XMR",
    "ZGBP": "GBP", "XZEC": "ZEC", "XREP": "REP",
}


def _kraken_priv(path: str, data: dict) -> dict:
    """Signed Kraken private REST call. Returns the 'result' dict; raises on error."""
    import hmac as _h, hashlib, base64, urllib.parse, time as _t
    key = get_setting("kraken_api_key", "") or ""
    secret = get_setting("kraken_api_secret", "") or ""
    if not key or not secret:
        raise RuntimeError("Kraken API key/secret not set")
    data = dict(data)
    data["nonce"] = str(int(_t.time() * 1000))
    postdata = urllib.parse.urlencode(data)
    encoded = (data["nonce"] + postdata).encode()
    message = path.encode() + hashlib.sha256(encoded).digest()
    try:
        mac = _h.new(base64.b64decode(secret), message, hashlib.sha512)
    except Exception:
        raise RuntimeError("Kraken secret is not valid base64 — re-copy it from Kraken")
    headers = {"API-Key": key, "API-Sign": base64.b64encode(mac.digest()).decode()}
    r = requests.post("https://api.kraken.com" + path, headers=headers, data=data, timeout=20)
    j = r.json()
    if j.get("error"):
        raise RuntimeError("; ".join(j["error"])[:180])
    return j.get("result") or {}


def _kraken_usd_prices(assets: set) -> dict:
    """Best-effort USD price per asset via Kraken public Ticker."""
    prices = {"USD": 1.0}
    want = [a for a in assets if a not in ("USD",)]
    if not want:
        return prices
    pairs = {a: (("XBT" if a == "BTC" else a) + "USD") for a in want}
    try:
        r = requests.get("https://api.kraken.com/0/public/Ticker",
                         params={"pair": ",".join(pairs.values())}, timeout=15)
        res = r.json().get("result", {})
        # Kraken returns canonicalized pair names; match by suffix
        for a, p in pairs.items():
            for kname, kd in res.items():
                if kname.replace("Z", "").replace("X", "").endswith("USD") and (p[:-3] in kname or (a == "BTC" and "XBT" in kname)):
                    try:
                        prices[a] = float(kd["c"][0])
                        break
                    except Exception:
                        pass
    except Exception as e:
        logger.warning("kraken ticker failed: %s", e)
    return prices


@router.get("/api/crypto/kraken")
def crypto_kraken():
    """Real Kraken account balances (read-only display). Graceful when unconfigured."""
    if not (get_setting("kraken_api_key") and get_setting("kraken_api_secret")):
        return {"configured": False}
    try:
        bal = _kraken_priv("/0/private/Balance", {})
    except Exception as e:
        return {"configured": True, "error": str(e)[:180], "balances": [], "total_usd": 0}
    rows = []
    norm = {}
    for raw, amt in bal.items():
        try:
            a = float(amt)
        except Exception:
            a = 0.0
        if a <= 0:
            continue
        sym = _KRAKEN_ASSET.get(raw, raw)
        norm[sym] = norm.get(sym, 0.0) + a
    prices = _kraken_usd_prices(set(norm))
    total = 0.0
    for sym, amt in sorted(norm.items(), key=lambda kv: -kv[1] * prices.get(kv[0], 0)):
        usd = amt * prices.get(sym, 0.0)
        total += usd
        rows.append({"asset": sym, "amount": amt, "usd": round(usd, 2)})
    return {"configured": True, "balances": rows, "total_usd": round(total, 2)}


@router.post("/api/crypto/kraken/sync-freqtrade")
def crypto_kraken_sync_ft():
    """Copy the Kraken API key/secret into the FreqTrade config so the bot can use
    the REAL account — but dry_run STAYS TRUE (still paper). Going live is a separate,
    deliberate flip of dry_run in the config. Restarts the freqtrade container."""
    key = get_setting("kraken_api_key", "") or ""
    secret = get_setting("kraken_api_secret", "") or ""
    if not key or not secret:
        raise HTTPException(400, "Set your Kraken API key/secret first.")
    cfg_path = FT_USER_DATA / "config.json"
    try:
        cfg = _json.loads(cfg_path.read_text())
        cfg.setdefault("exchange", {})["key"] = key
        cfg["exchange"]["secret"] = secret
        cfg["dry_run"] = True   # SAFETY: never auto-enable live trading
        cfg_path.write_text(_json.dumps(cfg, indent=2))
    except Exception as e:
        raise HTTPException(500, f"Could not update freqtrade config: {str(e)[:160]}")
    try:
        subprocess.run(["docker", "restart", FT_CONTAINER],
                       capture_output=True, text=True, timeout=60, env=_docker_env())
    except Exception as e:
        return {"ok": True, "restarted": False, "note": f"config updated; restart failed: {str(e)[:120]}"}
    return {"ok": True, "restarted": True,
            "note": "Kraken keys synced to FreqTrade. Still DRY-RUN (paper) — going live "
                    "means setting dry_run=false in the config, which stays your call."}
