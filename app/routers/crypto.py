"""Crypto & Markets — local Bitcoin (regtest) node, FreqTrade paper bot, coins & stocks.

What lives here:
  - Coin market data (CoinGecko free API, TTL-cached) for the Stats sub-tab.
  - Bitcoin Core running in Docker (`crypto-bitcoind`) on REGTEST — a private local
    chain with no blockchain download. Blocks are mined instantly via
    `generatetoaddress`, which makes it perfect for learning the REAL node/wallet
    software and for agent automation, but the coins have no market value.
  - FreqTrade (`crypto-freqtrade`) in DRY-RUN mode — a real trading bot, paper money.
    The LLM drafts IStrategy files into user_data/strategies_drafts; a human approves
    a draft to move it into user_data/strategies. Drafts NEVER go live by themselves.
  - Stocks: Robinhood portfolio (robin_stocks, read-only here), a yfinance watchlist,
    and an LLM daily brief (SMA20/50 + RSI14 signals). Not financial advice.
  - A key backup zip (bitcoin wallet descriptors + crypto/trading settings +
    strategy files). The zip CONTAINS PRIVATE KEYS — treat it like cash.
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

router = APIRouter()

# ── constants / contracts ─────────────────────────────────────────────────────
BTC_RPC_URL   = "http://127.0.0.1:8332"
BTC_CONTAINER = "crypto-bitcoind"
BTC_WALLET    = "store"

FT_API_URL    = "http://127.0.0.1:8898"   # 8899 is taken by searxng
FT_CONTAINER  = "crypto-freqtrade"
from config import _env
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
_BACKUP_PREFIXES = ("btc_", "ft_", "xmr_", "rh_", "money_", "kraken_", "jelly_")


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


# ── 🤖 freqtrade proxy ────────────────────────────────────────────────────────
_ft_jwt: dict = {"token": None, "exp": 0.0}   # cached JWT, ~5 min


def _ft_token() -> str:
    now = time.time()
    if _ft_jwt["token"] and _ft_jwt["exp"] > now:
        return _ft_jwt["token"]
    user = get_setting("ft_api_user", "") or ""
    pw   = get_setting("ft_api_pass", "") or ""
    if not user or not pw:
        raise RuntimeError("ft_api_user / ft_api_pass not set")
    r = httpx.post(f"{FT_API_URL}/api/v1/token/login", auth=(user, pw), timeout=8)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError("freqtrade login returned no access_token")
    _ft_jwt["token"], _ft_jwt["exp"] = tok, now + 300
    return tok


def _ft_get(path: str):
    r = httpx.get(f"{FT_API_URL}{path}",
                  headers={"Authorization": f"Bearer {_ft_token()}"}, timeout=10)
    if r.status_code == 401:            # stale JWT — refresh once
        _ft_jwt["token"] = None
        r = httpx.get(f"{FT_API_URL}{path}",
                      headers={"Authorization": f"Bearer {_ft_token()}"}, timeout=10)
    r.raise_for_status()
    return r.json()


@router.get("/api/crypto/trading")
def crypto_trading():
    container = _container_status(FT_CONTAINER)
    try:
        cfg = _ft_get("/api/v1/show_config")
        profit = {}
        try:
            p = _ft_get("/api/v1/profit")
            profit = {k: p.get(k) for k in (
                "profit_closed_coin", "profit_closed_percent_mean", "profit_all_coin",
                "profit_all_percent_mean", "trade_count", "closed_trade_count",
                "winning_trades", "losing_trades", "best_pair", "first_trade_date")}
        except Exception:
            pass
        try:
            open_trades = _ft_get("/api/v1/status")
            open_count = len(open_trades) if isinstance(open_trades, list) else 0
        except Exception:
            open_count = None
        try:
            whitelist = (_ft_get("/api/v1/whitelist") or {}).get("whitelist", [])
        except Exception:
            whitelist = cfg.get("exchange", {}).get("pair_whitelist", []) if isinstance(cfg.get("exchange"), dict) else []
        try:
            balance = (_ft_get("/api/v1/balance") or {}).get("total")
        except Exception:
            balance = None
        return {"configured": True, "container": container,
                "running": (cfg.get("state") == "running"),
                "dry_run": bool(cfg.get("dry_run", True)),
                "strategy": cfg.get("strategy"),
                "stake_currency": cfg.get("stake_currency"),
                "max_open_trades": cfg.get("max_open_trades"),
                "open_trade_count": open_count,
                "balance_total": balance,
                "whitelist": whitelist,
                "profit": profit}
    except Exception as e:
        return {"configured": False, "container": container, "error": str(e)[:200]}


# ── 🧠 LLM strategy drafts (never straight to live strategies/) ──────────────
STRATEGY_SYS = """You are an expert freqtrade strategy developer. Write ONE complete, \
valid freqtrade strategy file for the user's stated goal, intended for DRY-RUN (paper) \
testing only. Requirements:
- All needed imports (from freqtrade.strategy import IStrategy; import talib.abstract as ta \
is NOT available — use pandas / pandas_ta-free pure-pandas indicator math or \
`from technical import qtpylib` style helpers only if standard; prefer pure pandas).
- Exactly one class subclassing IStrategy, named in CamelCase after the goal.
- INTERFACE_VERSION = 3, a conservative minimal_roi dict, a stoploss (e.g. -0.05 to -0.10), \
timeframe (e.g. '5m' or '1h'), and startup_candle_count.
- Implement populate_indicators, populate_entry_trend and populate_exit_trend with clear, \
simple, defensible logic for the goal. Set 'enter_long' / 'exit_long' columns.
- Conservative defaults; no leverage, no shorts unless the goal demands it.
- Use ONLY hardcoded numeric thresholds. Do NOT use hyperopt parameters \
(IntParameter, DecimalParameter, CategoricalParameter, BooleanParameter) or a \
buy_params/sell_params block — they break plain backtesting. Every threshold must be a \
literal number in the code.
Return ONLY the Python code. No markdown fences, no commentary before or after."""


class ProposeIn(BaseModel):
    goal: str


def _generate_strategy_draft(goal: str) -> dict:
    """LLM-write a freqtrade IStrategy for `goal`, save it as a draft, return its
    row id + name. Shared by manual propose and the autonomous hunt."""
    code = _call_lmstudio(STRATEGY_SYS, f"Strategy goal: {goal}", max_tokens=3000)
    code = _re.sub(r"<think>.*?</think>", "", code, flags=_re.DOTALL).strip()
    m = _re.search(r"```(?:python)?\s*(.*?)```", code, flags=_re.DOTALL)
    if m:
        code = m.group(1).strip()
    cm = _re.search(r"class\s+([A-Za-z_]\w*)\s*\(\s*IStrategy", code)
    name = cm.group(1) if cm else f"DraftStrategy{datetime.now().strftime('%m%d%H%M%S')}"
    FT_DRAFTS.mkdir(parents=True, exist_ok=True)
    path = FT_DRAFTS / f"{name}.py"
    i = 2
    while path.exists():                       # never clobber an earlier draft
        path = FT_DRAFTS / f"{name}_{i}.py"
        i += 1
    path.write_text(code, encoding="utf-8")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO crypto_strategy_drafts (name,goal,code,status,notes) VALUES (?,?,?,?,?)",
        (path.stem, goal, code, "proposed", f"file: {path}"))
    conn.commit()
    did = cur.lastrowid
    conn.close()
    return {"id": did, "name": path.stem, "file": str(path), "goal": goal}


@router.post("/api/crypto/trading/strategy/propose")
def propose_strategy(req: ProposeIn):
    goal = (req.goal or "").strip()
    if not goal:
        raise HTTPException(400, "goal required")
    tid = orch.submit_llm(lambda: _generate_strategy_draft(goal),
                          desc=f"FT strategy: {goal[:40]}", priority=0)
    return {"task_id": tid}


# ── 🏁 autonomous strategy hunt: generate → backtest → leaderboard ────────────
STRATEGY_ARCHETYPES = [
    "RSI mean-reversion: buy deep oversold dips (RSI<30) in an uptrend, exit on RSI recovery, tight stop-loss",
    "EMA crossover trend-following: enter when fast EMA crosses above slow EMA with a higher-timeframe trend filter",
    "Bollinger Band bounce: enter near the lower band while price is above the 200 SMA, exit at the middle band",
    "MACD momentum: enter on a bullish MACD cross above the zero line, trail the winners, cut losers fast",
    "Breakout: enter on a candle close above the prior 24-hour high with a volatility (ATR) confirmation filter",
    "Donchian channel breakout with an ATR-based trailing stop and conservative position sizing",
    "Dual-indicator: RSI oversold AND price reclaiming the 50 EMA, take profit at a fixed 3% ROI",
    "Volume-momentum: enter when price and volume both rise over the last few candles, exit on momentum fade",
]

_hunt = {"running": False, "target": 0, "done": 0, "generated": 0,
         "passers": 0, "started_at": None, "log": [], "results": []}
_hunt_lock = threading.Lock()


def _wait_task(tid: int, timeout: float = 240) -> Optional[dict]:
    end = time.time() + timeout
    while time.time() < end:
        p = orch.poll(tid)
        if p["status"] == "done":
            return p.get("result")
        if p["status"] in ("failed", "error", "cancelled", "not_found"):
            return None
        time.sleep(2)
    return None


def _hunt_log(msg: str):
    _hunt["log"].append(msg)
    _hunt["log"][:] = _hunt["log"][-40:]
    logger.info("strategy hunt: %s", msg)


def _run_hunt(target: int):
    _hunt.update(running=True, target=target, done=0, generated=0, passers=0,
                 started_at=datetime.now().isoformat(timespec="seconds"),
                 log=[], results=[])
    try:
        for i in range(target):
            goal = STRATEGY_ARCHETYPES[i % len(STRATEGY_ARCHETYPES)]
            _hunt_log(f"[{i+1}/{target}] generating: {goal[:48]}…")
            tid = orch.submit_llm(lambda g=goal: _generate_strategy_draft(g),
                                  desc=f"hunt gen {i+1}/{target}", priority=2)  # background batch
            res = _wait_task(tid, 240)
            if not res or "id" not in res:
                _hunt_log(f"[{i+1}/{target}] generation failed — skipping")
                _hunt["done"] += 1
                continue
            _hunt["generated"] += 1
            did, name = res["id"], res["name"]
            _hunt_log(f"[{i+1}/{target}] backtesting {name}…")
            try:
                m = _run_backtest(name, False)
                conn = get_conn()
                conn.execute(
                    "INSERT OR REPLACE INTO crypto_backtests "
                    "(strategy_id,metrics,profit_pct,profit_factor,sharpe,passed,created_at) "
                    "VALUES (?,?,?,?,?,?,datetime('now'))",
                    (did, _json.dumps(m), m["profit_pct"], m["profit_factor"],
                     m["sharpe"], 1 if m["passed"] else 0))
                conn.commit()
                conn.close()
                if m["passed"]:
                    _hunt["passers"] += 1
                _hunt["results"].append({"id": did, "name": name, "metrics": m})
                _hunt_log(f"[{i+1}/{target}] {name}: {m['profit_pct']:+}% · "
                          f"{'✓ PASS' if m['passed'] else '✗ fail'}")
            except Exception as e:
                _hunt_log(f"[{i+1}/{target}] backtest failed: {str(e)[:80]}")
            _hunt["done"] += 1
        _hunt_log(f"hunt complete — {_hunt['passers']} passer(s) of {_hunt['generated']} generated")
    except Exception as e:
        _hunt_log(f"hunt aborted: {str(e)[:120]}")
    finally:
        _hunt["running"] = False


class HuntIn(BaseModel):
    count: int = 5


@router.post("/api/crypto/trading/hunt")
def start_hunt(req: HuntIn):
    """Autonomously generate `count` diverse strategies, backtest each on real
    history, and rank them. Runs in the background — poll /hunt/status."""
    with _hunt_lock:
        if _hunt["running"]:
            raise HTTPException(409, "A hunt is already running.")
        n = max(1, min(int(req.count or 5), 12))
        t = threading.Thread(target=_run_hunt, args=(n,), daemon=True, name="strategy-hunt")
        t.start()
    return {"ok": True, "target": n}


@router.get("/api/crypto/trading/hunt/status")
def hunt_status():
    return {k: _hunt[k] for k in
            ("running", "target", "done", "generated", "passers", "started_at", "log")}


@router.get("/api/crypto/trading/leaderboard")
def leaderboard():
    """All backtested strategies ranked best-first (passers, then profit factor,
    then profit %). This is where the hunt's winners surface for approval."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT d.id,d.name,d.goal,d.status,b.metrics,b.profit_pct,b.profit_factor,b.sharpe,b.passed "
        "FROM crypto_strategy_drafts d JOIN crypto_backtests b ON b.strategy_id=d.id "
        "WHERE d.status!='rejected'").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["metrics"] = _json.loads(d["metrics"])
        except Exception:
            d["metrics"] = {}
        out.append(d)
    out.sort(key=lambda x: (x["passed"], x["profit_factor"] or 0, x["profit_pct"] or 0), reverse=True)
    return {"leaderboard": out}


@router.get("/api/crypto/trading/strategies")
def list_strategies():
    conn = get_conn()
    drafts = [dict(r) for r in conn.execute(
        "SELECT id,name,goal,status,notes,created_at FROM crypto_strategy_drafts "
        "ORDER BY id DESC").fetchall()]
    bts = {r["strategy_id"]: dict(r) for r in conn.execute(
        "SELECT strategy_id,metrics,profit_pct,profit_factor,passed FROM crypto_backtests").fetchall()}
    conn.close()
    for d in drafts:
        bt = bts.get(d["id"])
        if bt:
            try:
                d["backtest"] = _json.loads(bt["metrics"])
            except Exception:
                d["backtest"] = {"profit_pct": bt["profit_pct"], "profit_factor": bt["profit_factor"],
                                 "passed": bool(bt["passed"])}
    active = sorted(f.name for f in FT_STRATS.glob("*.py")) if FT_STRATS.is_dir() else []
    return {"drafts": drafts, "active": active,
            "strategies_dir": str(FT_STRATS), "drafts_dir": str(FT_DRAFTS)}


@router.get("/api/crypto/trading/strategy/{sid}")
def get_strategy_draft(sid: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM crypto_strategy_drafts WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Draft not found")
    return dict(row)


# ── 🧪 backtesting gate (prove a strategy on real history before it goes live) ──
BT_PAIRS   = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD"]
BT_DATADIR = "/freqtrade/user_data/data/coinbase"
BT_CONFIG  = "/freqtrade/user_data/backtest-config.json"
BT_RESULTS = FT_USER_DATA / "backtest_results"


def _ft_exec(args, timeout):
    return subprocess.run(["docker", "exec", FT_CONTAINER, "freqtrade", *args],
                          capture_output=True, text=True, timeout=timeout, env=_docker_env())


def _bt_passed(m: dict) -> bool:
    """A strategy 'passes' only if it made money with a real edge over the window."""
    return (m.get("trades", 0) >= 5 and m.get("profit_pct", 0) > 0
            and m.get("profit_factor", 0) > 1.0)


def _run_backtest(name: str, is_approved: bool) -> dict:
    from datetime import timedelta
    import zipfile as _zip
    tr = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d") + "-"
    # 1. refresh Coinbase history (incremental — only missing candles, a few seconds)
    _ft_exec(["download-data", "--exchange", "coinbase", "--timeframe", "1h",
              "--timerange", tr, "--pairs", *BT_PAIRS], timeout=240)
    # 2. backtest the draft (or the live copy) without touching the running bot
    spath = ("/freqtrade/user_data/strategies" if is_approved
             else "/freqtrade/user_data/strategies_drafts")
    r = _ft_exec(["backtesting", "--strategy", name, "--strategy-path", spath,
                  "--datadir", BT_DATADIR, "--timeframe", "1h", "--timerange", tr,
                  "--config", BT_CONFIG], timeout=300)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError(tail[-1][:200] if tail else "backtest failed")
    # 3. read the newest result zip straight off the host-mounted dir
    zips = sorted(BT_RESULTS.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise RuntimeError("no backtest result produced")
    z = _zip.ZipFile(zips[0])
    main = [n for n in z.namelist()
            if n.endswith(".json") and "config" not in n and "market_change" not in n][0]
    strat = _json.loads(z.read(main)).get("strategy", {})
    if name not in strat:
        raise RuntimeError("strategy missing from backtest result")
    m = strat[name]
    out = {
        "trades":        m.get("total_trades"),
        "profit_pct":    round((m.get("profit_total") or 0) * 100, 2),
        "win_pct":       round((m.get("winrate") or 0) * 100, 1),
        "sharpe":        round(m.get("sharpe") or 0, 2),
        "profit_factor": round(m.get("profit_factor") or 0, 3),
        "max_dd_pct":    round((m.get("max_drawdown_account") or 0) * 100, 2),
        "final_balance": round(m.get("final_balance") or 0, 2),
        "timerange":     tr,
    }
    out["passed"] = _bt_passed(out)
    return out


@router.post("/api/crypto/trading/strategy/{sid}/backtest")
def backtest_strategy(sid: int):
    """Prove a strategy against ~180 days of real Coinbase history — no money, no
    live bot impact. Stores the result; approval is gated on a passing backtest."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM crypto_strategy_drafts WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Draft not found")
    d = dict(row)
    name = d["name"]
    is_approved = d["status"] == "approved"
    # make sure the strategy file exists where we'll point freqtrade
    fp = (FT_STRATS if is_approved else FT_DRAFTS) / f"{name}.py"
    if not fp.is_file():
        FT_DRAFTS.mkdir(parents=True, exist_ok=True)
        (FT_DRAFTS / f"{name}.py").write_text(d.get("code") or "", encoding="utf-8")
        is_approved = False
    try:
        res = _run_backtest(name, is_approved)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Backtest timed out (data download or run too slow).")
    except Exception as e:
        raise HTTPException(400, f"Backtest failed: {str(e)[:220]}")
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO crypto_backtests "
                 "(strategy_id,metrics,profit_pct,profit_factor,sharpe,passed,created_at) "
                 "VALUES (?,?,?,?,?,?,datetime('now'))",
                 (sid, _json.dumps(res), res["profit_pct"], res["profit_factor"],
                  res["sharpe"], 1 if res["passed"] else 0))
    conn.commit()
    conn.close()
    return {"ok": True, "metrics": res, "passed": res["passed"]}


@router.post("/api/crypto/trading/strategy/{sid}/approve")
def approve_strategy(sid: int, body: dict = Body(default={})):
    """Human approval: move the draft file into the LIVE strategies dir. GATED —
    a strategy must have a PASSING backtest first (profitable, profit-factor > 1,
    ≥5 trades) unless you pass force=true. FreqTrade still only trades it once you
    set it in its own config, and it stays paper money until dry_run is flipped."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM crypto_strategy_drafts WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Draft not found")
    bt = conn.execute("SELECT passed, profit_pct FROM crypto_backtests WHERE strategy_id=?",
                      (sid,)).fetchone()
    if not (body or {}).get("force"):
        if not bt:
            conn.close()
            raise HTTPException(400, "No backtest yet — run a backtest first, or pass force=true.")
        if not bt["passed"]:
            conn.close()
            raise HTTPException(400, f"Backtest did NOT pass (profit {bt['profit_pct']}%) — "
                                     f"this strategy loses money on history. Pass force=true to override.")
    d = dict(row)
    FT_STRATS.mkdir(parents=True, exist_ok=True)
    src = FT_DRAFTS / f"{d['name']}.py"
    dst = FT_STRATS / f"{d['name']}.py"
    try:
        if src.is_file():
            shutil.move(str(src), str(dst))
        else:                                   # draft file lost — rebuild from DB code
            dst.write_text(d.get("code") or "", encoding="utf-8")
    except Exception as e:
        conn.close()
        raise HTTPException(500, f"Could not move draft into strategies/: {e}")
    conn.execute("UPDATE crypto_strategy_drafts SET status='approved', notes=? WHERE id=?",
                 (f"approved → {dst}", sid))
    conn.commit()
    conn.close()
    return {"ok": True, "id": sid, "file": str(dst)}


@router.post("/api/crypto/trading/strategy/{sid}/reject")
def reject_strategy(sid: int):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM crypto_strategy_drafts WHERE id=?", (sid,)).fetchone():
        conn.close()
        raise HTTPException(404, "Draft not found")
    conn.execute("UPDATE crypto_strategy_drafts SET status='rejected' WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return {"ok": True, "id": sid}


# ── 📈 stocks: robinhood portfolio ────────────────────────────────────────────
_rh_state = {"logged_in": False}


def _rh_login():
    """Lazy import + cached login. Import inside so a missing lib never breaks the app."""
    import robin_stocks.robinhood as rh
    if _rh_state["logged_in"]:
        return rh
    user = get_setting("rh_username", "") or ""
    pw   = get_setting("rh_password", "") or ""
    if not user or not pw:
        raise RuntimeError("Robinhood credentials not set")
    mfa_code = None
    secret = get_setting("rh_mfa_secret", "") or ""
    if secret:
        import pyotp
        mfa_code = pyotp.TOTP(secret).now()
    rh.login(user, pw, mfa_code=mfa_code, store_session=True)
    _rh_state["logged_in"] = True
    return rh


@router.get("/api/crypto/stocks")
def crypto_stocks():
    if not (get_setting("rh_username") and get_setting("rh_password")):
        return {"configured": False}
    try:
        rh = _rh_login()
        holdings = rh.build_holdings() or {}
        equity = None
        try:
            prof = rh.load_portfolio_profile() or {}
            equity = prof.get("equity")
        except Exception:
            pass
        return {"configured": True, "equity": equity, "holdings": holdings}
    except ImportError:
        return {"configured": False, "error": "robin_stocks not installed in the store venv"}
    except Exception as e:
        _rh_state["logged_in"] = False      # force fresh login next time
        return {"configured": False, "error": str(e)[:200]}


# ── 📈 stocks: watchlist quotes + news (yfinance, TTL 300s) ──────────────────
def _watch_symbols() -> list[str]:
    raw = get_setting("stocks_watchlist", "") or ""
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _yf_news(t, n=3) -> list[dict]:
    """Normalize yfinance news across its old (title/link) and new (content.*) shapes."""
    out = []
    try:
        for item in (t.news or [])[:n]:
            c = item.get("content") or item
            title = c.get("title") or ""
            link = (item.get("link")
                    or (c.get("canonicalUrl") or {}).get("url")
                    or (c.get("clickThroughUrl") or {}).get("url") or "")
            if title:
                out.append({"title": title, "link": link})
    except Exception:
        pass
    return out


@router.get("/api/crypto/stocks/watch")
def stocks_watch():
    syms = _watch_symbols()
    if not syms:
        return {"quotes": [], "note": "Add symbols to stocks_watchlist (comma-separated) first."}
    from cache import cached

    def _fetch():
        import yfinance as yf
        quotes = []
        for sym in syms[:25]:
            q = {"symbol": sym, "price": None, "news": []}
            try:
                t = yf.Ticker(sym)
                fi = t.fast_info
                q["price"] = getattr(fi, "last_price", None) or (fi["last_price"] if "last_price" in fi else None)
                q["news"] = _yf_news(t, 3)
            except Exception as e:
                q["error"] = str(e)[:120]
            quotes.append(q)
        return {"quotes": quotes, "fetched_at": datetime.now().isoformat(timespec="seconds")}

    try:
        return cached("crypto:watch:" + ",".join(syms), 300, _fetch)
    except ImportError:
        return {"quotes": [], "error": "yfinance not installed in the store venv"}
    except Exception as e:
        return {"quotes": [], "error": str(e)[:200]}


# ── 📈 stocks: LLM daily brief (signals computed pure-pandas) ─────────────────
BRIEF_SYS = """You are a cautious markets analyst writing a SHORT morning brief for a \
hobbyist investor. You are given per-symbol technical signals (price, SMA20 vs SMA50, \
14-day RSI, a rough stance) and recent news headlines. Write 2-3 tight paragraphs: \
1) overall read of the watchlist, 2) the 2-3 most notable symbols and why (crossovers, \
overbought/oversold RSI, big news), 3) anything to watch next. Plain language, no hype, \
no price targets, no buy/sell instructions. End with exactly this line: \
"This is automated technical commentary, NOT financial advice.\""""


def _signal_for(sym: str) -> Optional[dict]:
    import yfinance as yf
    h = yf.Ticker(sym).history(period="3mo", interval="1d")
    close = h.get("Close")
    if close is None:
        return None
    close = close.dropna()
    if len(close) < 20:
        return None
    price = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = None
    try:
        g, l = float(gain.iloc[-1]), float(loss.iloc[-1])
        rsi = 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)
    except Exception:
        pass
    if rsi is not None and rsi >= 70:
        stance = "overbought"
    elif rsi is not None and rsi <= 30:
        stance = "oversold"
    elif sma50 is not None and sma20 > sma50:
        stance = "bullish"
    elif sma50 is not None and sma20 < sma50:
        stance = "bearish"
    else:
        stance = "neutral"
    rnd = lambda v: round(v, 2) if isinstance(v, float) else v
    return {"symbol": sym, "price": rnd(price), "sma20": rnd(sma20),
            "sma50": rnd(sma50), "rsi": rnd(rsi), "stance": stance}


@router.get("/api/crypto/stocks/brief")
def stocks_brief():
    """Signals + ONE LLM brief for watchlist + holdings symbols. Heavy (yfinance
    history per symbol + an LLM call), so it runs as an orchestrator task — returns
    {task_id}; poll /api/task/{id} for {brief, signals}."""
    def _work():
        syms = list(_watch_symbols())
        try:                                     # add holdings symbols when configured
            if get_setting("rh_username") and get_setting("rh_password"):
                rh = _rh_login()
                for s in (rh.build_holdings() or {}):
                    if s.upper() not in syms:
                        syms.append(s.upper())
        except Exception:
            pass
        syms = syms[:15]
        if not syms:
            return {"brief": "No symbols — set a watchlist (or Robinhood creds) first.",
                    "signals": []}
        signals, headlines = [], []
        import yfinance as yf
        for sym in syms:
            try:
                sig = _signal_for(sym)
                if sig:
                    signals.append(sig)
                for n in _yf_news(yf.Ticker(sym), 2):
                    headlines.append(f"[{sym}] {n['title']}")
            except Exception:
                continue
        sig_lines = "\n".join(
            f"{s['symbol']}: price={s['price']} sma20={s['sma20']} sma50={s['sma50']} "
            f"rsi14={s['rsi']} stance={s['stance']}" for s in signals) or "(no signal data)"
        news_lines = "\n".join(headlines[:20]) or "(no recent headlines)"
        user_msg = f"Signals:\n{sig_lines}\n\nRecent headlines:\n{news_lines}"
        try:
            brief = _call_lmstudio(BRIEF_SYS, user_msg, max_tokens=900)
            brief = _re.sub(r"<think>.*?</think>", "", brief, flags=_re.DOTALL).strip()
        except Exception as e:
            brief = f"(LLM brief unavailable: {str(e)[:150]})"
        if "not financial advice" not in brief.lower():
            brief += "\n\nThis is automated technical commentary, NOT financial advice."
        return {"brief": brief, "signals": signals,
                "generated_at": datetime.now().isoformat(timespec="seconds")}

    tid = orch.submit_llm(_work, desc="Stocks daily brief", priority=0)
    return {"task_id": tid}


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
    invalidate_prefix("crypto:")
    _ft_jwt["token"] = None
    _rh_state["logged_in"] = False
    return {"ok": True, "saved": saved}
