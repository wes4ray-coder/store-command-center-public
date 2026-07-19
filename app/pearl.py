"""Pearl (PRL) — the real, external proof-of-useful-work L1 the user asked about
("Purl" by ear). NOT related to JellyCoin: JLY is our own in-house chain; Pearl is a
public network by Pearl Research Labs (pearlresearch.ai, github.com/pearl-research-labs/pearl).

Verified facts (researched 2026-07-18, multiple independent sources — HashrateIndex,
Tom's Hardware, MiningBoard, Kryptex pool, the official repo):
  - Own Layer-1 forked from btcd (Bitcoin's Go implementation). Mainnet 2026-04-27.
  - Consensus: proof-of-USEFUL-work ("NoisyGEMM") — miners run noisy matrix
    multiplications (the same math as AI inference) on GPUs and wrap the result in
    ZK proofs. Based on a peer-reviewed 2025 cryptography paper; CEO Omri Weinstein
    (Princeton PhD, Hebrew University). Fair launch, no premine/VC.
  - Mining is NVIDIA-ONLY (tensor cores; CUDA/vLLM — NOT OpenCL). Community pools
    support RTX 30-series and up. Our GPU node's RTX 3060 12GB qualifies (barely —
    expect small returns; a 5090 was ~$17/day and falling as of June 2026).
  - Official software: `pearld` (node), `oyster` (HD wallet daemon, JSON-RPC/gRPC),
    `oystercli`, `prlctl`, and the two-part miner `pearl-gateway` + `vllm-miner`.
  - Trades only on minor exchanges with THIN liquidity; ~$146M mcap in June 2026.

Red flags to keep in mind (why everything real-money here stays manual + gated):
  - The name is heavily squatted: "PRL" on big aggregators is often the DEAD 2018
    Oyster Pearl exit-scam token; pearlfortune.org / PearlBridgeXYZ etc. are
    unofficial lookalikes. ONLY trust github.com/pearl-research-labs/pearl.
  - 2.5 months old, thin books, profitability already compressed ~50% in weeks.
  - "Useful work" demand is mostly speculative so far (one Together AI endpoint).

Scope of this module (deliberately conservative):
  - Talks JSON-RPC to a pearld node / oyster wallet the USER installs themselves
    (we never download or run third-party binaries automatically).
  - Miner control = start/stop of a user-named systemd *user* unit on the GPU node
    over the existing BOX_SSH channel — gated behind the `pearl_mining_enabled`
    toggle (default OFF), never auto-started, and refuses without the toggle.
  - pearl_* settings ride the existing gated crypto key-backup zip; pearl_rpc_pass
    is Fernet-encrypted at rest (app/crypto.py SECRET_KEYS).

Used by routers/pearl.py (API) and tests/test_pearl.py.
"""
import re
import subprocess

import httpx

from deps import get_conn, get_setting, logger
from config import BOX_SSH, GPU_HOST

SYMBOL, NAME = "PRL", "Pearl"

# ── settings contract ────────────────────────────────────────────────────────
SETTING_KEYS = [
    "pearl_node_url",        # pearld JSON-RPC, e.g. http://127.0.0.1:8334
    "pearl_wallet_url",      # oyster wallet JSON-RPC, e.g. http://127.0.0.1:8332
    "pearl_rpc_user",
    "pearl_rpc_pass",        # secret (encrypted at rest)
    "pearl_payout_address",  # PRL address mining rewards / pool payouts go to
    "pearl_pool_url",        # stratum pool, e.g. pool.kryptex.com / pearl.luckypool.io
    "pearl_miner_host",      # box running the miner (default: the GPU node)
    "pearl_miner_unit",      # systemd --user unit name for the miner (user-installed)
    "pearl_mining_enabled",  # master toggle — nothing starts while this is off
    "pearl_agent_access",    # agent/automation gate — OFF = only the human can start/stop
]
SECRET_SETTINGS = {"pearl_rpc_pass"}
MINING_TOGGLE_KEY = "pearl_mining_enabled"
AGENT_ACCESS_KEY = "pearl_agent_access"
BOOL_KEYS = {MINING_TOGGLE_KEY, AGENT_ACCESS_KEY}    # normalized to "1"/"0" on save
_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")   # systemd unit-name allowlist


def _set(key: str, value: str):
    conn = get_conn()
    try:
        v = value
        if key in SECRET_SETTINGS and value:
            import crypto as _secrets_at_rest      # app/crypto.py — Fernet at rest
            v = _secrets_at_rest.enc(value)
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, v))
        conn.commit()
    finally:
        conn.close()


def save_settings(body: dict) -> list:
    """Persist any of SETTING_KEYS (unknown keys rejected by the router). Blank
    secret values are ignored so the UI can leave saved secrets untouched."""
    saved = []
    for k in SETTING_KEYS:
        if k not in body or body[k] is None:
            continue
        v = str(body[k]).strip()
        if k in SECRET_SETTINGS and v == "":
            continue                                # blank = keep the saved secret
        if k in BOOL_KEYS:
            v = "1" if v in ("1", "true", "on", "True") else "0"
        if k == "pearl_miner_unit" and v and not _UNIT_RE.match(v):
            raise ValueError("miner unit name may only contain letters, digits, . _ @ -")
        _set(k, v)
        saved.append(k)
    return saved


def settings_masked() -> dict:
    out = {}
    for k in SETTING_KEYS:
        v = get_setting(k, "") or ""
        if k in SECRET_SETTINGS and v:
            v = ("•" * max(len(v) - 4, 4)) + v[-4:]
        out[k] = v
    return out


def mining_enabled() -> bool:
    return str(get_setting(MINING_TOGGLE_KEY, "0") or "0") in ("1", "true", "on")


def agent_access_enabled() -> bool:
    """Whether agents / automation (non-human callers) may drive the miner. OFF by
    default: even with mining enabled, only the human UI can start/stop until this
    is turned on. Mirrors the owner's 'every gate gets a toggle' preference."""
    return str(get_setting(AGENT_ACCESS_KEY, "0") or "0") in ("1", "true", "on")


# ── JSON-RPC (btcd-style — pearld is a btcd fork; oyster is btcwallet-style) ──
def _rpc(url: str, method: str, params: list | None = None, timeout: int = 8):
    """Basic-auth JSON-RPC 1.0 call. Raises RuntimeError with a short message."""
    user = get_setting("pearl_rpc_user", "") or ""
    pw = get_setting("pearl_rpc_pass", "") or ""
    try:
        r = httpx.post(url, json={"jsonrpc": "1.0", "id": "store", "method": method,
                                  "params": params or []},
                       auth=(user, pw) if user or pw else None, timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"{method}: unreachable ({str(e)[:80]})")
    if r.status_code in (401, 403):
        raise RuntimeError(f"{method}: RPC auth rejected — check pearl_rpc_user/pass")
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"{method}: non-JSON reply (HTTP {r.status_code})")
    if data.get("error"):
        err = data["error"]
        raise RuntimeError(f"{method}: {err.get('message', err)}")
    return data.get("result")


def _try_rpc(url: str, methods: list[tuple], what: str) -> dict:
    """Try (method, params) pairs in order; first success wins. Returns
    {ok, method, result} or {ok: False, error} — never raises."""
    last = ""
    for method, params in methods:
        try:
            return {"ok": True, "method": method, "result": _rpc(url, method, params)}
        except RuntimeError as e:
            last = str(e)
    return {"ok": False, "error": f"{what}: {last[:180]}"}


def node_status() -> dict:
    """pearld reachability + chain height. Graceful when unconfigured/down."""
    url = (get_setting("pearl_node_url", "") or "").strip()
    if not url:
        return {"configured": False}
    out = {"configured": True, "url": url, "reachable": False}
    r = _try_rpc(url, [("getblockchaininfo", []), ("getinfo", []), ("getblockcount", [])],
                 "node")
    if not r["ok"]:
        out["error"] = r["error"]
        return out
    out["reachable"] = True
    res = r["result"]
    if isinstance(res, dict):
        out["height"] = res.get("blocks") or res.get("headers")
        out["chain"] = res.get("chain") or res.get("net")
        if res.get("difficulty") is not None:
            out["difficulty"] = res.get("difficulty")
    elif isinstance(res, (int, float)):
        out["height"] = int(res)
    return out


def wallet_status() -> dict:
    """oyster wallet balance + a receive address. Best-effort across the
    btcwallet-style method names; graceful when unconfigured/down."""
    url = (get_setting("pearl_wallet_url", "") or "").strip()
    if not url:
        return {"configured": False}
    out = {"configured": True, "url": url, "reachable": False}
    bal = _try_rpc(url, [("getbalance", []), ("getbalances", [])], "wallet balance")
    if not bal["ok"]:
        out["error"] = bal["error"]
        return out
    out["reachable"] = True
    res = bal["result"]
    if isinstance(res, dict):        # getbalances shape
        mine = res.get("mine") or res
        out["balance"] = mine.get("trusted") if isinstance(mine, dict) else None
    else:
        out["balance"] = res
    addr = _try_rpc(url, [("listreceivedbyaddress", [0, True]), ("getaccountaddress", [""])],
                    "wallet address")
    if addr["ok"]:
        res = addr["result"]
        if isinstance(res, list) and res:
            out["addresses"] = [a.get("address") for a in res[:5]
                                if isinstance(a, dict) and a.get("address")]
        elif isinstance(res, str):
            out["addresses"] = [res]
    return out


def new_address() -> dict:
    """Ask the oyster wallet for a fresh receive address."""
    url = (get_setting("pearl_wallet_url", "") or "").strip()
    if not url:
        raise RuntimeError("pearl_wallet_url not set — install and start the oyster "
                           "wallet daemon first (see the setup notes in this tab).")
    return {"address": _rpc(url, "getnewaddress", [])}


# ── miner control (SSH to the GPU node; user-installed systemd --user unit) ───
def _miner_ssh_prefix() -> list:
    host = (get_setting("pearl_miner_host", "") or "").strip() or GPU_HOST
    if host == GPU_HOST:
        return BOX_SSH                      # the standard node channel (keys set up)
    user_host = host if "@" in host else f"{BOX_SSH[-1].split('@')[0]}@{host}"
    return BOX_SSH[:-1] + [user_host]


def _miner_unit() -> str:
    unit = (get_setting("pearl_miner_unit", "") or "pearl-miner").strip()
    if not _UNIT_RE.match(unit):
        raise RuntimeError("invalid pearl_miner_unit name")
    return unit


def miner_status(probe: bool = False) -> dict:
    """State of the miner unit on the GPU node. SSH is only attempted when the
    mining toggle is on (or probe=True) so the status endpoint stays fast and
    the test suite never opens network connections."""
    out = {"enabled": mining_enabled(),
           "host": (get_setting("pearl_miner_host", "") or "").strip() or GPU_HOST,
           "unit": (get_setting("pearl_miner_unit", "") or "pearl-miner").strip(),
           "pool": get_setting("pearl_pool_url", "") or "",
           "payout_address": get_setting("pearl_payout_address", "") or "",
           "state": "unknown"}
    if not (out["enabled"] or probe):
        out["state"] = "toggle-off"
        return out
    try:
        unit = _miner_unit()
        r = subprocess.run(
            _miner_ssh_prefix()
            + [f"systemctl --user is-active {unit} 2>/dev/null; "
               # bracket trick ([v]…) stops pgrep matching this command line itself
               f"pgrep -af '[v]llm-miner|[p]earl-gateway' 2>/dev/null | head -3"],
            capture_output=True, text=True, timeout=12)
        lines = (r.stdout or "").strip().splitlines()
        out["state"] = (lines[0].strip() if lines else "unknown") or "unknown"
        out["processes"] = lines[1:4]
        if out["state"] not in ("active", "activating") and not out["processes"]:
            out["installed_hint"] = (
                f"No '{unit}' unit / pearl processes found on {out['host']} — "
                "install the official miner first (see setup notes).")
    except Exception as e:
        out["state"] = "ssh-error"
        out["error"] = str(e)[:160]
    return out


def miner_action(action: str, by_agent: bool = False) -> dict:
    """start|stop the miner unit. HARD-GATED on the pearl_mining_enabled toggle;
    never called automatically by anything — only the UI button reaches this.

    ``by_agent`` marks a non-human caller (MCP tool / automation / localhost
    bypass). Such callers ALSO need pearl_agent_access on — otherwise only the
    human, from an authenticated session, may start/stop the miner."""
    if action not in ("start", "stop"):
        raise ValueError("action must be start or stop")
    if by_agent and not agent_access_enabled():
        raise PermissionError("Agent access to Pearl mining is OFF — turn on the "
                              "'Allow agents to control mining' toggle for automation "
                              "to start/stop the miner. (A human can still use the buttons.)")
    if action == "start" and not mining_enabled():
        raise PermissionError("Pearl mining is toggled OFF — enable the "
                              "'Allow Pearl mining' toggle first. Nothing auto-starts.")
    unit = _miner_unit()
    try:
        r = subprocess.run(_miner_ssh_prefix() + [f"systemctl --user {action} {unit}"],
                           capture_output=True, text=True, timeout=20)
    except Exception as e:
        raise RuntimeError(f"SSH to miner host failed: {str(e)[:120]}")
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()[:200]
        raise RuntimeError(f"systemctl --user {action} {unit} failed: {msg or 'unknown'} "
                           "(is the official Pearl miner installed as this unit?)")
    logger.info("[pearl] miner %s (unit %s)", action, unit)
    return {"ok": True, "action": action, "unit": unit, **miner_status(probe=True)}


def status() -> dict:
    """One-call rollup for the UI pane. Never raises, never 5xx."""
    return {"symbol": SYMBOL, "name": NAME,
            "node": node_status(), "wallet": wallet_status(),
            "miner": miner_status(), "mining_enabled": mining_enabled(),
            "agent_access": agent_access_enabled()}


# ── the research card (Phase-1 findings, served verbatim to the UI) ──────────
RESEARCH = {
    "heard_as": "Purl",
    "actual_name": "Pearl (PRL)",
    "verdict": "REAL project, credible team — but very young (mainnet 2026-04-27), "
               "thinly traded, and its name is heavily squatted. Treat with care.",
    "what_it_is": [
        "Own Layer-1 blockchain forked from btcd (Bitcoin's Go implementation).",
        "Proof-of-USEFUL-work ('NoisyGEMM'): miners run noisy matrix multiplications "
        "— the same math as AI inference — on GPUs, verified on-chain with ZK proofs. "
        "Based on a peer-reviewed 2025 cryptography paper.",
        "Team: Pearl Research Labs; CEO Omri Weinstein (Princeton PhD in complexity "
        "theory, Hebrew University). Fair launch — no premine, no VC allocation.",
        "Supply 2.1B PRL, ~2-minute blocks, declining rewards (Bitcoin-like economics).",
        "Together AI runs a Pearl-powered discounted inference endpoint (since "
        "2026-05-15) — the first real paid demand for the mined compute.",
    ],
    "mining": [
        "GPU-minable — but NVIDIA-ONLY (tensor cores, CUDA/vLLM). It does NOT use "
        "OpenCL, so it's a different stack from our JellyCoin miner.",
        "Community pools support RTX 30-series and newer. Our GPU node's RTX 3060 "
        "12GB qualifies at the low end; the server's GTX 1060 does not.",
        "Official miner = pearl-gateway + vllm-miner (github.com/pearl-research-labs/"
        "pearl). Pools: pool.kryptex.com/prl, pearl.luckypool.io (official H100/H200 "
        "pool takes 20%).",
        "Profitability is compressing fast: RTX 5090 revenue halved (~$33→$17/day) "
        "within weeks of launch. A 3060 will earn a small fraction of that.",
    ],
    "red_flags": [
        "Name collision: 'PRL' on CoinGecko/CMC is often the DEAD Oyster Pearl token "
        "(2018 exit scam) — do NOT trust aggregator listings by ticker alone.",
        "Lookalike sites/repos exist (e.g. pearlfortune.org, third-party 'pearl "
        "wallets'). ONLY use github.com/pearl-research-labs/pearl and pearlresearch.ai.",
        "Thin liquidity on minor exchanges only — hard to exit size; price is volatile.",
        "Most mined compute is still speculative (inference nobody requested); the "
        "'useful work' thesis is unproven beyond one partner endpoint.",
    ],
    "sources": [
        "https://hashrateindex.com/blog/pearl-prl-ai-compute-cryptocurrency/",
        "https://www.tomshardware.com/tech-industry/cryptomining/new-ai-compute-cryptocurrency-pearl-sparks-a-gpu-mining-rush-but-profitability-is-sliding",
        "https://miningboard.com/guides/how-to-mine-pearl-coin",
        "https://pool.kryptex.com/prl/about-coin",
        "https://github.com/pearl-research-labs/pearl",
        "https://pearlresearch.ai/",
    ],
    "setup": [
        "1. On the GPU node (127.0.0.1, RTX 3060): download the official release "
        "from github.com/pearl-research-labs/pearl/releases — it bundles pearld "
        "(node), oyster (wallet daemon) and prlctl. Verify you are on the "
        "pearl-research-labs org before running anything.",
        "2. Run `oystercli` once — it walks through wallet creation (WRITE DOWN the "
        "seed phrase offline; this app never stores it) and starts the daemons.",
        "3. Build/install the miner (pearl-gateway + vllm-miner) per the repo README, "
        "then wrap it in a systemd --user unit (default name: pearl-miner), like the "
        "existing jellyminer.service on the node.",
        "4. Back here: set the node/wallet RPC URLs + credentials and your payout "
        "address, flip the mining toggle, and use Start/Stop. Mining never "
        "auto-starts, and the RTX 3060 must still share the GPU with LM Studio/ComfyUI "
        "— expect the AI queue to slow while mining.",
    ],
}
