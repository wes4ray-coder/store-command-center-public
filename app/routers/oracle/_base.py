"""Shared foundation for the oracle package: the single APIRouter, the SQLite
schema + default-analyst seed (both run once at import), the tournament constants,
and the low-level helpers (meta key/value store, tracked-asset list, price lookup,
searx research) used across the forecast / scoring / agents submodules."""
from typing import Optional

import requests
from fastapi import APIRouter

from deps import *          # get_conn, get_setting, orch, logger, _call_lmstudio
from services import *      # (kept consistent with sibling routers)

router = APIRouter()

SEARX_URL = "http://127.0.0.1:8899"

# The competitors. name → LM Studio model id (seeded on first use; toggle in the UI).
# Chosen for SPEED + reliable JSON on this single-GPU box. Gemma and Ministral were
# dropped — they took up to ~17 min/call and never returned clean JSON. Coder models
# are the most JSON-compliant; GLM-flash adds non-Qwen diversity.
DEFAULT_ANALYSTS = [
    ("GLM-4.7",        "zai-org/glm-4.7-flash"),
    ("GLM-4.6v",       "zai-org/glm-4.6v-flash"),
    ("Qwen3.5-9B",     "qwen/qwen3.5-9b"),
    ("Qwen-Coder-32B", "qwen2.5-coder-32b-instruct"),
    ("Qwen3-Coder-30B", "qwen3-coder-30b-a3b-instruct"),
]

# Auto-resolvable assets. Crypto → CoinGecko id; stocks come from stocks_watchlist.
CRYPTO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
              "DOGE": "dogecoin", "ADA": "cardano", "LTC": "litecoin"}


# ── schema ────────────────────────────────────────────────────────────────────
def _ensure_schema():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS oracle_agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, model TEXT,
        active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE IF NOT EXISTS oracle_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, agent_name TEXT,
        market TEXT, asset TEXT, current_value REAL, direction TEXT,
        target_value REAL, horizon_days INTEGER, resolve_at TEXT, confidence REAL,
        thesis TEXT, sources TEXT, status TEXT DEFAULT 'open',
        actual_value REAL, rel_error REAL, correct INTEGER, score REAL,
        created_at TEXT DEFAULT (datetime('now')), resolved_at TEXT);
    CREATE TABLE IF NOT EXISTS oracle_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, text TEXT,
        created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE IF NOT EXISTS oracle_meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    conn.commit()
    conn.close()

_ensure_schema()


def _seed_agents():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM oracle_agents").fetchone()["n"]
    if n == 0:
        for name, model in DEFAULT_ANALYSTS:
            conn.execute("INSERT INTO oracle_agents (name,model,active) VALUES (?,?,1)", (name, model))
        conn.commit()
    conn.close()

_seed_agents()


# ── small helpers ─────────────────────────────────────────────────────────────
def _meta_get(k, d=""):
    conn = get_conn(); r = conn.execute("SELECT v FROM oracle_meta WHERE k=?", (k,)).fetchone(); conn.close()
    return r["v"] if r else d


def _meta_set(k, v):
    conn = get_conn(); conn.execute("INSERT OR REPLACE INTO oracle_meta (k,v) VALUES (?,?)", (k, str(v)))
    conn.commit(); conn.close()


def _assets() -> list:
    """Tracked assets: the crypto majors + any non-crypto stock tickers on the watchlist."""
    out = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    wl = (get_setting("stocks_watchlist", "") or "").upper()
    for s in [x.strip() for x in wl.split(",") if x.strip()]:
        if "-" in s or s in CRYPTO_IDS:      # skip BTC-USD style + crypto dupes
            continue
        out.append(s)
    return out


def _price(asset: str) -> Optional[float]:
    """Current USD price. Crypto via CoinGecko, stocks via yfinance. None on failure."""
    try:
        if asset in CRYPTO_IDS:
            r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                             params={"ids": CRYPTO_IDS[asset], "vs_currencies": "usd"}, timeout=15)
            return float(r.json()[CRYPTO_IDS[asset]]["usd"])
        import yfinance as yf
        fi = yf.Ticker(asset).fast_info
        p = None
        for k in ("last_price", "lastPrice"):
            p = getattr(fi, k, None) if hasattr(fi, k) else (fi.get(k) if hasattr(fi, "get") else None)
            if p:
                break
        return float(p) if p else None
    except Exception as e:
        logger.warning("oracle price(%s) failed: %s", asset, e)
        return None


def _searx(query: str, n: int = 5) -> list:
    try:
        r = requests.get(f"{SEARX_URL}/search",
                         params={"q": query, "format": "json", "language": "en"}, timeout=20)
        r.raise_for_status()
        return [{"title": (x.get("title") or "")[:160], "url": x.get("url") or "",
                 "snippet": (x.get("content") or "")[:280]}
                for x in (r.json().get("results") or [])[:n]]
    except Exception as e:
        logger.warning("oracle searx failed: %s", e)
        return []
