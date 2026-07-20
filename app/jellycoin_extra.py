"""JellyCoin — NFTs + the buddy-share (peers federation) compute economy.

Extracted verbatim from jellycoin.py to keep that module under the size budget.
These are leaf concerns of the chain: nothing else in jellycoin.py calls them
(only routers/jellycoin.py, routers/peers/* and world_sim do). The core chain
primitives (transfer/_wallet/_ensure/_tip_height/_sha256_hex + constants) live
in jellycoin.py; each function lazy-imports it so there is no import cycle
(jellycoin.py re-exports these names).
"""
import hashlib
import json
import time

from deps import get_conn, get_setting


# ── NFTs ─────────────────────────────────────────────────────────────────────
def mint_nft(owner: str, file_path: str, title: str, meta: dict | None = None) -> dict:
    """Mint an NFT from a real art file. Fee goes to the treasury; content hash on-chain."""
    import os
    import jellycoin
    if not os.path.isfile(file_path):
        raise ValueError(f"file not found: {file_path}")
    with open(file_path, "rb") as f:
        content_hash = hashlib.sha256(f.read()).hexdigest()
    conn = get_conn()
    try:
        jellycoin._ensure(conn)
        if conn.execute("SELECT 1 FROM jelly_nfts WHERE sha256=?", (content_hash,)).fetchone():
            raise ValueError("this exact artwork is already minted")
    finally:
        conn.close()
    if owner != jellycoin.TREASURY:   # treasury mints its own store art fee-free
        jellycoin.transfer(owner, jellycoin.TREASURY, jellycoin.NFT_MINT_FEE,
                           memo=f"NFT mint fee: {title[:60]}", kind="nft_fee")
    conn = get_conn()
    try:
        jellycoin._ensure(conn)
        token_id = "jnft_" + jellycoin._sha256_hex(f"{content_hash}:{owner}:{time.time()}".encode())[:24]
        conn.execute("INSERT INTO jelly_nfts (token_id,title,file_path,sha256,meta,owner,minted_height)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (token_id, title[:120], file_path, content_hash,
                      json.dumps(meta or {}), owner, jellycoin._tip_height(conn)))
        conn.commit()
        return {"ok": True, "token_id": token_id, "sha256": content_hash,
                "fee": jellycoin.NFT_MINT_FEE / jellycoin.UNIT}
    finally:
        conn.close()


def transfer_nft(token_id: str, frm: str, dst: str) -> dict:
    import jellycoin
    conn = get_conn()
    try:
        jellycoin._ensure(conn)
        row = conn.execute("SELECT * FROM jelly_nfts WHERE token_id=?", (token_id,)).fetchone()
        if not row:
            raise ValueError("unknown NFT")
        if row["owner"] != frm:
            raise ValueError(f"{frm} does not own this NFT")
        jellycoin._wallet(conn, dst)
        conn.execute("UPDATE jelly_nfts SET owner=? WHERE token_id=?", (dst, token_id))
        conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,?,?,0,?,?)",
                     (jellycoin._tip_height(conn), int(time.time()), frm, dst, "nft_transfer", token_id))
        conn.commit()
        return {"ok": True, "token_id": token_id, "owner": dst}
    finally:
        conn.close()


# ── buddy-share compute economy (peers federation) ───────────────────────────
# JLY is the working coin of the peer network: when a buddy's box does AI work
# for us (client.delegate_llm), our treasury PAYS their peer:<name> wallet; when
# a buddy runs a job on OUR AI helper (rpc_job), their wallet is CHARGED into the
# company wallet. Code reviews bill the same way (rpc_review charges, the
# requester's refresh credits) — a review is our LLM's time spent on their diff.
# A broke buddy is never blocked — the job runs comped (amount-0
# tx keeps the tab) because compute sharing must not break over play money.
PEER_BILLING_KEY = "jelly_peer_billing"            # settings toggle, default on
PEER_PRICE_KEY = "jelly_peer_job_price_jly"        # JLY per llm job, default 1
PEER_PRICE_DEFAULT = 1.0


def peer_billing_enabled() -> bool:
    # A JOINED node runs no chain of its own, so it has no ledger to bill on — the
    # economy it takes part in is the home node's, and that node does the billing.
    # Without this the transfers would just fail into "comped"/"treasury empty" on
    # every job, which reads like a broken wallet rather than a deliberate mode.
    import jellycoin
    if jellycoin.jelly_mode() == "joined":
        return False
    return str(get_setting(PEER_BILLING_KEY) or "1") in ("1", "true", "on")


def peer_job_price(kind: str = "llm") -> int:
    """Price in ujly. Embeddings are 1/10th of an llm job (they borrow, never swap);
    a code review ("review") bills like a full llm job — their diff, our model's time."""
    import jellycoin
    try:
        jly = float(get_setting(PEER_PRICE_KEY) or PEER_PRICE_DEFAULT)
    except Exception:
        jly = PEER_PRICE_DEFAULT
    price = int(max(0.0, jly) * jellycoin.UNIT)
    return price // 10 if kind == "embedding" else price


def peer_job_charge(peer_name: str, kind: str = "llm") -> dict:
    """Inbound: a buddy used OUR AI helper. Charge their wallet → company (or comp)."""
    import jellycoin
    if not peer_billing_enabled():
        return {"billed": False, "reason": "billing off"}
    price = peer_job_price(kind)
    wname = f"peer:{peer_name}"
    if price <= 0:
        return {"billed": False, "reason": "free"}
    try:
        jellycoin.transfer(wname, jellycoin.COMPANY, price, memo=f"{kind} job on our node", kind="compute")
        return {"billed": True, "amount": price}
    except ValueError:                      # broke buddy → job still runs, tab recorded
        conn = get_conn()
        try:
            jellycoin._ensure(conn)
            jellycoin._wallet(conn, wname, kind="peer")
            conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,?,?,0,?,?)",
                         (jellycoin._tip_height(conn), int(time.time()), wname, jellycoin.COMPANY,
                          "compute_comped", f"{kind} job comped (insufficient JLY)"))
            conn.commit()
        finally:
            conn.close()
        return {"billed": False, "reason": "comped"}


def peer_job_credit(peer_name: str, kind: str = "llm") -> dict:
    """Outbound: a buddy's box did AI work FOR us. Treasury pays their peer wallet."""
    import jellycoin
    if not peer_billing_enabled():
        return {"billed": False, "reason": "billing off"}
    price = peer_job_price(kind)
    if price <= 0:
        return {"billed": False, "reason": "free"}
    try:
        jellycoin.transfer(jellycoin.TREASURY, f"peer:{peer_name}", price,
                           memo=f"{kind} job lent to us — thanks!", kind="compute")
        return {"billed": True, "amount": price}
    except ValueError:
        return {"billed": False, "reason": "treasury empty"}


# ── per-TOKEN peer compute pricing ("you only pay for the answers") ──────────
# The owner's rule: when a buddy borrows our LLM they pay per COMPLETION token —
# the answer — and prompt/input tokens are free. Prompt tokens still have their
# own rate field (default 0) so the price can change later with no schema change.
#
# Units. Rates are quoted per 1,000 tokens, in JLY, and stored in settings as
# JLY; internally everything is ujly (1 JLY = 1_000_000 ujly), so a rate is
# "ujly per 1k tokens" and a cost is a whole number of ujly. Per-1k keeps the
# number human ("0.5 JLY per 1k answer tokens") instead of 0.0005-per-token.
#
# Modes. `job` (legacy, the default) = the old flat per-job fee; `token` = this
# meter. The mode is ADVERTISED (peer_price_quote) so a paired peer on an older
# build keeps working on the flat fee and nobody is silently re-priced.
#
# Rounding. Never in the counterparty's favour: an inbound charge (we EARN) is
# rounded UP to the next ujly, an outbound credit (we SPEND) is rounded DOWN.
# The bias is at most 1 ujly = 0.000001 JLY per job, always toward this node.
PEER_MODE_KEY = "jelly_peer_billing_mode"                  # "job" | "token"
PEER_TOKEN_BILLING_KEY = "jelly_peer_token_billing"        # extra gate for token mode, default OFF
PEER_COMPLETION_PRICE_KEY = "jelly_peer_price_completion_1k"   # JLY per 1k completion tokens
PEER_PROMPT_PRICE_KEY = "jelly_peer_price_prompt_1k"           # JLY per 1k prompt tokens
PEER_TOLERANCE_KEY = "jelly_peer_count_tolerance"          # 1.25 = accept 25% over our own count
PEER_CAP_JOB_KEY = "jelly_peer_cap_job_jly"                # max JLY on a single job
PEER_CAP_PEER_DAY_KEY = "jelly_peer_cap_peer_day_jly"      # max JLY per peer per day
PEER_CAP_DAY_KEY = "jelly_peer_cap_day_jly"                # global daily ceiling
PEER_FIAT_REF_KEY = "jelly_peer_fiat_ref_usd"              # OWNER'S OWN assumption, never a quote

PEER_COMPLETION_PRICE_DEFAULT = 1.0     # JLY per 1k answer tokens
PEER_PROMPT_PRICE_DEFAULT = 0.0         # the answers are what you pay for
PEER_TOLERANCE_DEFAULT = 1.25
PEER_CAP_JOB_DEFAULT = 25.0
PEER_CAP_PEER_DAY_DEFAULT = 250.0
PEER_CAP_DAY_DEFAULT = 1000.0
PEER_FLAG_THRESHOLD = 3                 # this many over-reports → flag the peer in the UI

# Approximation used when a provider path reports no usage block. ~4 chars per
# token is the well-known rough ratio for English BPE vocabularies; it is a
# DOCUMENTED ESTIMATE, and every row it produces is stored with reported=0 so
# the UI can say "estimated" instead of pretending it is exact.
CHARS_PER_TOKEN = 4


def _fsetting(key: str, default: float) -> float:
    try:
        v = get_setting(key)
        return float(v) if v not in (None, "") else float(default)
    except Exception:
        return float(default)


def estimate_tokens(text: str | None) -> int:
    """Local, documented token approximation: ceil(chars / 4), min 1 for non-empty
    text. Deliberately simple so both sides can reproduce it by hand when a bill
    is disputed — it is never presented as an exact count."""
    s = text or ""
    if not s.strip():
        return 0
    return max(1, -(-len(s) // CHARS_PER_TOKEN))


def peer_billing_mode() -> str:
    """`token` only when BOTH the mode is set to token AND the token-billing gate is
    on (house rule: every gate ships with a toggle, and this one defaults OFF so an
    upgrade never starts metering anybody by surprise)."""
    mode = str(get_setting(PEER_MODE_KEY) or "job").strip().lower()
    if mode != "token":
        return "job"
    return "token" if str(get_setting(PEER_TOKEN_BILLING_KEY) or "0") in ("1", "true", "on") else "job"


def peer_token_rates() -> dict:
    """Rates in ujly per 1,000 tokens.

    An UNCONFIGURED node does not fall back to a placeholder: it falls back to the
    price DERIVED from its own hardware and its own chain (see compute_cost_basis
    at the bottom of this module). Once the owner saves a price, that price wins —
    this is a better default, not a hardcoded rate."""
    import jellycoin
    return {
        "completion": int(max(0.0, _fsetting(PEER_COMPLETION_PRICE_KEY,
                                             derived_default_completion_price())) * jellycoin.UNIT),
        "prompt": int(max(0.0, _fsetting(PEER_PROMPT_PRICE_KEY,
                                         PEER_PROMPT_PRICE_DEFAULT)) * jellycoin.UNIT),
    }


def peer_tolerance() -> float:
    """How far above OUR OWN count of the answer we will still pay. 1.0 = pay only
    what we counted ourselves; clamped to >= 1.0 so it can never be a discount."""
    return max(1.0, _fsetting(PEER_TOLERANCE_KEY, PEER_TOLERANCE_DEFAULT))


def peer_caps() -> dict:
    """Owner-controlled hard ceilings, in ujly."""
    import jellycoin
    u = jellycoin.UNIT
    return {"job": int(max(0.0, _fsetting(PEER_CAP_JOB_KEY, PEER_CAP_JOB_DEFAULT)) * u),
            "peer_day": int(max(0.0, _fsetting(PEER_CAP_PEER_DAY_KEY, PEER_CAP_PEER_DAY_DEFAULT)) * u),
            "day": int(max(0.0, _fsetting(PEER_CAP_DAY_KEY, PEER_CAP_DAY_DEFAULT)) * u)}


def token_cost(prompt_tokens: int, completion_tokens: int, rates: dict,
               direction: str = "earned") -> int:
    """ujly owed for one answer. See the rounding note at the top of this block."""
    import math
    raw = (max(0, int(completion_tokens)) * float(rates.get("completion") or 0)
           + max(0, int(prompt_tokens)) * float(rates.get("prompt") or 0)) / 1000.0
    if direction == "earned":                       # they pay us → round up
        return int(math.ceil(raw - 1e-9))
    return int(math.floor(raw + 1e-9))              # we pay them → round down


def peer_price_quote() -> dict:
    """What this node ADVERTISES. A consumer fetches this BEFORE submitting a job
    and settles against the copy it fetched, so a provider that raises its price
    mid-flight cannot bill the new rate for work already quoted."""
    import jellycoin
    u = jellycoin.UNIT
    rates = peer_token_rates()
    return {"billing": peer_billing_enabled(), "mode": peer_billing_mode(),
            "symbol": jellycoin.SYMBOL,
            "price_per_1k_completion_jly": rates["completion"] / u,
            "price_per_1k_prompt_jly": rates["prompt"] / u,
            "price_per_llm_job_jly": peer_job_price("llm") / u,
            "price_per_review_jly": peer_job_price("review") / u,
            "quoted_at": int(time.time())}


# ── the metered ledger ───────────────────────────────────────────────────────
def _ensure_ledger(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS peer_token_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        peer TEXT NOT NULL,
        direction TEXT NOT NULL,           -- earned (they paid us) | spent (we paid them)
        kind TEXT DEFAULT 'llm',
        model TEXT,
        mode TEXT DEFAULT 'token',         -- token | job
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,   -- what we BILLED on (post-tolerance)
        reported_completion INTEGER DEFAULT 0, -- what the counterparty claimed
        own_estimate INTEGER,                  -- our independent local count
        discrepancy_ratio REAL,                -- reported / own_estimate when > 1
        reported INTEGER DEFAULT 1,            -- 1 = real usage block, 0 = estimated
        rate_completion_ujly_1k INTEGER DEFAULT 0,
        rate_prompt_ujly_1k INTEGER DEFAULT 0,
        amount_ujly INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',     -- pending | settled | comped | blocked | failed
        reason TEXT,
        flagged INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ptl_peer_time ON peer_token_ledger (peer, created_at)")


def _ledger_insert(conn, **f) -> int:
    _ensure_ledger(conn)
    cols = ",".join(f)
    marks = ",".join("?" for _ in f)
    cur = conn.execute(f"INSERT INTO peer_token_ledger ({cols}) VALUES ({marks})", tuple(f.values()))
    conn.commit()
    return cur.lastrowid


def _ledger_set(rid: int, **f):
    conn = get_conn()
    try:
        _ensure_ledger(conn)
        sets = ",".join(f"{k}=?" for k in f)
        conn.execute(f"UPDATE peer_token_ledger SET {sets} WHERE id=?", (*f.values(), rid))
        conn.commit()
    finally:
        conn.close()


def _spent_today(conn, peer: str | None) -> int:
    """ujly actually SETTLED today (pending rows count too — they may yet land)."""
    _ensure_ledger(conn)
    q = ("SELECT COALESCE(SUM(amount_ujly),0) s FROM peer_token_ledger "
         "WHERE status IN ('settled','pending') AND created_at >= date('now')")
    args: tuple = ()
    if peer:
        q += " AND peer=?"
        args = (peer,)
    return int(conn.execute(q, args).fetchone()["s"] or 0)


def peer_cap_check(peer_name: str, amount_ujly: int) -> dict:
    """Owner's hard ceilings. A breach is a CLEAN refusal — the caller never charges
    a partial amount; there is no 'charge up to the cap' path anywhere."""
    caps = peer_caps()
    conn = get_conn()
    try:
        if caps["job"] and amount_ujly > caps["job"]:
            return {"ok": False, "cap": "job",
                    "reason": f"job cost {amount_ujly} ujly exceeds the per-job cap {caps['job']} ujly"}
        if caps["peer_day"] and _spent_today(conn, f"peer:{peer_name}") + amount_ujly > caps["peer_day"]:
            return {"ok": False, "cap": "peer_day",
                    "reason": f"per-peer daily cap ({caps['peer_day']} ujly) reached for {peer_name}"}
        if caps["day"] and _spent_today(conn, None) + amount_ujly > caps["day"]:
            return {"ok": False, "cap": "day",
                    "reason": f"global daily cap ({caps['day']} ujly) reached"}
        return {"ok": True}
    finally:
        conn.close()


def _flag_count(peer_wallet: str) -> int:
    conn = get_conn()
    try:
        _ensure_ledger(conn)
        return int(conn.execute(
            "SELECT COUNT(*) c FROM peer_token_ledger WHERE peer=? AND discrepancy_ratio > 1.0",
            (peer_wallet,)).fetchone()["c"] or 0)
    finally:
        conn.close()


def peer_settle_tokens(peer_name: str, direction: str, *, kind: str = "llm",
                       model: str | None = None, prompt_tokens: int = 0,
                       completion_tokens: int = 0, reported: bool = True,
                       own_estimate: int | None = None,
                       quoted_rates: dict | None = None) -> dict:
    """Settle ONE metered job.

    direction 'earned' = a buddy used our LLM  → peer:<name> pays COMPANY.
    direction 'spent'  = their box answered us → TREASURY pays peer:<name>.

    Anti-cheat (consumer side, direction='spent'): we count the answer we actually
    received ourselves and pay min(reported, own_estimate * tolerance). Over-reports
    are billed down, recorded with their ratio, and counted toward flagging.

    Atomicity: the ledger row is INSERTed and COMMITTED as 'pending' BEFORE any
    coin moves, and is only marked 'settled' after jellycoin.transfer() returned ok
    (transfer is itself a single locked sqlite transaction). So: no transfer can
    happen without a row, and no row says 'settled' unless the transfer succeeded.
    A crash in between leaves a visible 'pending' row — never a silent payment.
    """
    import jellycoin
    if direction not in ("earned", "spent"):
        raise ValueError("direction must be earned or spent")
    wallet = f"peer:{peer_name}"
    if not peer_billing_enabled():
        return {"billed": False, "reason": "billing off", "amount": 0}
    rates = dict(quoted_rates or peer_token_rates())
    prompt_tokens = max(0, int(prompt_tokens or 0))
    reported_completion = max(0, int(completion_tokens or 0))
    billed_completion, ratio, flagged = reported_completion, None, 0

    if direction == "spent" and own_estimate is not None:
        allowed = int(max(0, own_estimate) * peer_tolerance())
        if reported_completion > allowed:
            ratio = round(reported_completion / max(1, int(own_estimate)), 4)
            billed_completion = allowed
            flagged = 1 if _flag_count(wallet) + 1 >= PEER_FLAG_THRESHOLD else 0

    amount = token_cost(prompt_tokens, billed_completion, rates, direction)
    row = dict(peer=wallet, direction=direction, kind=kind, model=(model or "")[:80],
               mode="token", prompt_tokens=prompt_tokens,
               completion_tokens=billed_completion, reported_completion=reported_completion,
               own_estimate=own_estimate, discrepancy_ratio=ratio,
               reported=1 if reported else 0,
               rate_completion_ujly_1k=int(rates.get("completion") or 0),
               rate_prompt_ujly_1k=int(rates.get("prompt") or 0),
               amount_ujly=amount, flagged=flagged)

    if amount <= 0:
        conn = get_conn()
        try:
            rid = _ledger_insert(conn, **row, status="settled", reason="free (rate 0)")
        finally:
            conn.close()
        return {"billed": False, "reason": "free", "amount": 0, "ledger_id": rid,
                "discrepancy_ratio": ratio}

    cap = peer_cap_check(peer_name, amount)
    if not cap["ok"]:
        conn = get_conn()
        try:
            rid = _ledger_insert(conn, **{**row, "amount_ujly": 0}, status="blocked",
                                 reason=cap["reason"])
        finally:
            conn.close()
        return {"billed": False, "blocked": True, "cap": cap["cap"], "reason": cap["reason"],
                "amount": 0, "would_have_been": amount, "ledger_id": rid,
                "discrepancy_ratio": ratio}

    conn = get_conn()                       # 1) row first, committed
    try:
        rid = _ledger_insert(conn, **row, status="pending")
    finally:
        conn.close()

    frm, dst, memo = ((wallet, jellycoin.COMPANY, f"{kind}: {billed_completion} answer tokens on our node")
                      if direction == "earned" else
                      (jellycoin.TREASURY, wallet, f"{kind}: {billed_completion} answer tokens lent to us"))
    try:                                    # 2) money
        jellycoin.transfer(frm, dst, amount, memo=memo, kind="compute")
    except ValueError as e:                 # 3a) no money moved → row must not say paid
        if direction == "earned":
            _ledger_set(rid, status="comped", amount_ujly=0, reason=f"comped: {e}"[:200])
            conn = get_conn()               # keep the 0-amount tab like the flat path does
            try:
                jellycoin._ensure(conn)
                jellycoin._wallet(conn, wallet, kind="peer")
                conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) "
                             "VALUES (?,?,?,?,0,?,?)",
                             (jellycoin._tip_height(conn), int(time.time()), wallet, jellycoin.COMPANY,
                              "compute_comped", f"{kind} job comped ({billed_completion} tokens)"))
                conn.commit()
            finally:
                conn.close()
            return {"billed": False, "reason": "comped", "amount": 0, "ledger_id": rid,
                    "discrepancy_ratio": ratio}
        _ledger_set(rid, status="failed", amount_ujly=0, reason=str(e)[:200])
        return {"billed": False, "reason": f"treasury: {e}", "amount": 0, "ledger_id": rid,
                "discrepancy_ratio": ratio}
    _ledger_set(rid, status="settled")      # 3b) paid, and only now
    return {"billed": True, "amount": amount, "ledger_id": rid, "completion_tokens": billed_completion,
            "reported": reported, "discrepancy_ratio": ratio, "flagged": bool(flagged)}


# ── read models for the UI (ledger + the observed "market") ──────────────────
def peer_ledger(limit: int = 60, peer: str | None = None) -> dict:
    import jellycoin
    u = jellycoin.UNIT
    conn = get_conn()
    try:
        _ensure_ledger(conn)
        q = "SELECT * FROM peer_token_ledger"
        args: tuple = ()
        if peer:
            q += " WHERE peer=?"
            args = (f"peer:{peer}",)
        rows = [dict(r) for r in conn.execute(q + " ORDER BY id DESC LIMIT ?",
                                              (*args, max(1, min(int(limit), 500)))).fetchall()]
        tot = {d: dict(conn.execute(
            "SELECT COALESCE(SUM(amount_ujly),0) amt, COALESCE(SUM(completion_tokens),0) ct, "
            "COALESCE(SUM(prompt_tokens),0) pt, COUNT(*) n FROM peer_token_ledger "
            "WHERE direction=? AND status='settled'", (d,)).fetchone()) for d in ("earned", "spent")}
        per_peer = [dict(r) for r in conn.execute(
            "SELECT peer, direction, COALESCE(SUM(amount_ujly),0) amt, "
            "COALESCE(SUM(completion_tokens),0) ct, COUNT(*) n, "
            "SUM(CASE WHEN discrepancy_ratio > 1.0 THEN 1 ELSE 0 END) bad, MAX(discrepancy_ratio) worst "
            "FROM peer_token_ledger WHERE status='settled' GROUP BY peer, direction").fetchall()]
        pend = int(conn.execute("SELECT COUNT(*) c FROM peer_token_ledger "
                                "WHERE status='pending'").fetchone()["c"] or 0)
    finally:
        conn.close()
    for r in rows:
        r["amount_jly"] = (r.get("amount_ujly") or 0) / u
    balances: dict = {}
    for r in per_peer:
        b = balances.setdefault(r["peer"], {"peer": r["peer"], "earned_jly": 0.0, "spent_jly": 0.0,
                                            "tokens_served": 0, "tokens_consumed": 0,
                                            "discrepancies": 0, "worst_ratio": None, "flagged": False})
        if r["direction"] == "earned":
            b["earned_jly"] += r["amt"] / u
            b["tokens_served"] += r["ct"]
        else:
            b["spent_jly"] += r["amt"] / u
            b["tokens_consumed"] += r["ct"]
        b["discrepancies"] += int(r["bad"] or 0)
        if r["worst"]:
            b["worst_ratio"] = max(b["worst_ratio"] or 0, r["worst"])
    for b in balances.values():
        b["net_jly"] = round(b["earned_jly"] - b["spent_jly"], 6)
        b["flagged"] = b["discrepancies"] >= PEER_FLAG_THRESHOLD
    return {"rows": rows, "balances": sorted(balances.values(), key=lambda x: x["peer"]),
            "totals": {"earned_jly": tot["earned"]["amt"] / u, "spent_jly": tot["spent"]["amt"] / u,
                       "net_jly": round((tot["earned"]["amt"] - tot["spent"]["amt"]) / u, 6),
                       "tokens_served": tot["earned"]["ct"], "tokens_consumed": tot["spent"]["ct"],
                       "trades": tot["earned"]["n"] + tot["spent"]["n"]},
            "pending": pend, "flag_threshold": PEER_FLAG_THRESHOLD}


# How many settlements before we are willing to draw a trend line. Fewer than this
# and the UI says "not enough trades" rather than drawing a slope through 2 points.
MARKET_MIN_TRADES = 5


def peer_market(limit: int = 40) -> dict:
    """The ONLY honest 'market value' JLY has: what it has actually traded for
    between this node and its buddies, in JLY per 1,000 completion tokens, derived
    from settled rows. JLY has no exchange listing — nothing here is a quote, and
    the fiat reference (if set) is the OWNER'S OWN assumption, labelled as such."""
    import jellycoin
    u = jellycoin.UNIT
    conn = get_conn()
    try:
        _ensure_ledger(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM peer_token_ledger WHERE status='settled' AND amount_ujly > 0 "
            "AND completion_tokens > 0 ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),)).fetchall()]
    finally:
        conn.close()
    trades = [{"id": r["id"], "peer": (r["peer"] or "").replace("peer:", ""),
               "direction": r["direction"], "kind": r["kind"], "model": r["model"],
               "completion_tokens": r["completion_tokens"], "prompt_tokens": r["prompt_tokens"],
               "reported": bool(r["reported"]), "mode": r["mode"],
               "amount_jly": r["amount_ujly"] / u,
               "rate_jly_per_1k": round(r["amount_ujly"] / u / (r["completion_tokens"] / 1000.0), 6),
               "when": r["created_at"]} for r in rows]
    # Fiat is gated on monetary mode (default OFF) and always carries its provenance.
    fiat, fiat_rate = None, None
    if monetary_mode_on():
        fiat_rate = current_fiat_rate()
        if fiat_rate:
            fiat = fiat_rate["usd_per_jly"]
        else:                                   # legacy free-text reference, if any
            try:
                raw = get_setting(PEER_FIAT_REF_KEY)
                fiat = float(raw) if raw not in (None, "") else None
                if fiat is not None:
                    fiat_rate = {"usd_per_jly": fiat, "basis": "owner_assumed", "ref": None,
                                 "as_of": None, "chip": "assumed", "note": "legacy reference"}
            except Exception:
                fiat = None
    obs = [t["rate_jly_per_1k"] for t in trades]
    stats = None
    if obs:
        stats = {"last": obs[0], "avg": round(sum(obs) / len(obs), 6),
                 "min": min(obs), "max": max(obs), "n": len(obs)}
    return {"symbol": jellycoin.SYMBOL, "unit": "JLY per 1,000 completion tokens",
            "trades": trades, "last_trade": trades[0] if trades else None,
            "observed": stats, "enough_data": len(trades) >= MARKET_MIN_TRADES,
            "min_trades": MARKET_MIN_TRADES,
            "monetary_mode": monetary_mode_on(),
            "fiat_ref_usd_per_jly": fiat,       # None unless monetary mode is ON
            "fiat_rate": fiat_rate,             # carries basis + chip whenever fiat is shown
            "warning_hidden": fiat_warning_hidden(),
            "note": ("JLY is not listed on any exchange. These rates are what JLY has "
                     "ACTUALLY traded for between this node and its peers — observed "
                     "settlements, not a market quote."),
            "totals": peer_ledger(1)["totals"]}


# ── monetary mode: when (and only when) JLY may be shown in real money ───────
# JLY is a SEPARATE ASSET CLASS. It is not dollars, and a number the owner typed
# in is not evidence that it is worth dollars. So:
#
#   jelly_monetary_mode      (default OFF) — off, no fiat figure is produced
#                            ANYWHERE; every surface shows JLY only.
#   jelly_fiat_warning_hidden(default OFF) — hides the long banner. The compact
#                            provenance chip is NOT hideable: hiding the essay is
#                            a preference, erasing where a number came from is how
#                            an invented figure gets trusted six months later.
#   jelly_count_in_net_worth (default OFF) — the owner's explicit opt-in to let an
#                            ASSUMED valuation appear inside a net-worth total.
#
# Every rate carries a BASIS, stored with it:
#   owner_assumed   — he typed it. No external validation. chip: "assumed".
#   peer_settlement — a real settlement where real currency actually changed
#                     hands for JLY; carries a ref to that trade. chip: "evidenced".
#   exchange        — a real external quote, if JLY ever gets listed. chip: "evidenced".
#
# HARD RULE — the one that matters: an `owner_assumed` rate may never post to the
# real-money ledger, treasury, safe-to-spend or budget income. Only a settlement
# or exchange basis with an ACTUAL transaction posts, via record_fiat_settlement()
# below, which is the ONLY writer from JLY into the money ledger and is idempotent
# on its reference. The budget decides whether groceries are affordable; a
# self-declared token price must never move that number.
MONETARY_MODE_KEY = "jelly_monetary_mode"
FIAT_WARNING_HIDDEN_KEY = "jelly_fiat_warning_hidden"
COUNT_IN_NET_WORTH_KEY = "jelly_count_in_net_worth"
FIAT_BASES = ("owner_assumed", "peer_settlement", "exchange")
EVIDENCED_BASES = ("peer_settlement", "exchange")


def _flag(key: str, default: str = "0") -> bool:
    return str(get_setting(key) or default).strip().lower() in ("1", "true", "on", "yes")


def monetary_mode_on() -> bool:
    return _flag(MONETARY_MODE_KEY)


def fiat_warning_hidden() -> bool:
    return _flag(FIAT_WARNING_HIDDEN_KEY)


def count_in_net_worth() -> bool:
    return _flag(COUNT_IN_NET_WORTH_KEY)


def _ensure_fiat(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS jelly_fiat_rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usd_per_jly REAL NOT NULL,
        basis TEXT NOT NULL,               -- owner_assumed | peer_settlement | exchange
        ref TEXT,                          -- the trade/quote that evidences it
        note TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()


def set_fiat_rate(usd_per_jly: float, basis: str, ref: str | None = None,
                  note: str | None = None) -> dict:
    """Record a rate WITH its provenance. An evidenced basis must name the thing
    that evidences it — otherwise it is just an assumption wearing a better label."""
    if basis not in FIAT_BASES:
        raise ValueError(f"basis must be one of {', '.join(FIAT_BASES)}")
    rate = float(usd_per_jly)
    if rate < 0:
        raise ValueError("rate cannot be negative")
    if basis in EVIDENCED_BASES and not (ref or "").strip():
        raise ValueError(f"basis '{basis}' requires a ref (the settlement or quote it came from)")
    conn = get_conn()
    try:
        _ensure_fiat(conn)
        cur = conn.execute("INSERT INTO jelly_fiat_rates (usd_per_jly,basis,ref,note) "
                           "VALUES (?,?,?,?)",
                           (rate, basis, (ref or "").strip()[:120] or None, (note or "")[:300]))
        conn.commit()
        return {"ok": True, "id": cur.lastrowid, "usd_per_jly": rate, "basis": basis, "ref": ref}
    finally:
        conn.close()


def current_fiat_rate() -> dict | None:
    conn = get_conn()
    try:
        _ensure_fiat(conn)
        r = conn.execute("SELECT * FROM jelly_fiat_rates ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if not r:
        return None
    return {"usd_per_jly": r["usd_per_jly"], "basis": r["basis"], "ref": r["ref"],
            "note": r["note"], "as_of": r["created_at"],
            "chip": "evidenced" if r["basis"] in EVIDENCED_BASES else "assumed"}


def fiat_rate_history(limit: int = 20) -> list:
    conn = get_conn()
    try:
        _ensure_fiat(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM jelly_fiat_rates ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),)).fetchall()]
    finally:
        conn.close()
    for r in rows:
        r["chip"] = "evidenced" if r["basis"] in EVIDENCED_BASES else "assumed"
    return rows


def jelly_valuation(wallets: list[str] | None = None) -> dict:
    """The JLY holdings line: always its own asset class, never merged into dollars.

    With monetary mode OFF there is NO usd figure in the payload at all — not a
    zero, not a null-with-a-number-next-to-it: the field is absent, so nothing
    downstream can accidentally render or sum it.
    """
    import jellycoin
    names = wallets or [jellycoin.TREASURY, jellycoin.COMPANY]
    conn = get_conn()
    try:
        jellycoin._ensure(conn)
        held = 0
        for n in names:
            row = conn.execute("SELECT balance FROM jelly_wallets WHERE name=?", (n,)).fetchone()
            held += int(row["balance"]) if row else 0
    finally:
        conn.close()
    out = {"symbol": jellycoin.SYMBOL, "wallets": names, "holdings_jly": held / jellycoin.UNIT,
           "monetary_mode": monetary_mode_on(),
           "warning_hidden": fiat_warning_hidden(),
           "counts_in_net_worth": False,
           "note": ("JellyCoin is its own asset class. It is not listed on any exchange, "
                    "so it has no market price — only what peers have actually paid for "
                    "compute in JLY.")}
    rate = current_fiat_rate()
    if not monetary_mode_on():
        out["rate"] = None
        out["fiat_note"] = ("Monetary mode is OFF — JLY is shown in JLY only. "
                            "No dollar figure is produced anywhere.")
        return out
    out["rate"] = rate
    if rate and rate["usd_per_jly"] > 0:
        out["usd_value"] = round(out["holdings_jly"] * rate["usd_per_jly"], 2)
        out["chip"] = rate["chip"]          # ALWAYS present next to a fiat figure
        out["counts_in_net_worth"] = count_in_net_worth()
        out["fiat_note"] = ("Valued at an OWNER-ASSUMED rate — this is his own number, "
                            "not a quote." if rate["chip"] == "assumed" else
                            f"Valued at an evidenced rate ({rate['basis']}, ref {rate['ref']}).")
    else:
        out["fiat_note"] = "Monetary mode is on, but no rate has been recorded yet."
    # The hard boundary, stated in the payload so no caller has to guess.
    out["posts_to_real_money"] = False
    return out


def record_fiat_settlement(amount_jly: float, usd_cents: int, ref: str,
                           basis: str = "peer_settlement", source: str = "JellyCoin settlement",
                           received_at: str | None = None, note: str = "") -> dict:
    """The ONLY path from JLY into the real-money ledger.

    Requires that real currency ACTUALLY changed hands (basis peer_settlement or
    exchange) and a unique `ref` for that transaction. Idempotent: re-posting the
    same ref is a no-op, so a retry or a double-click can never book the income
    twice. An owner_assumed rate is rejected outright — that is the whole point.
    """
    import json as _json
    if basis not in EVIDENCED_BASES:
        raise ValueError("only an evidenced basis (peer_settlement/exchange) may post to the "
                         "money ledger — an assumed rate never touches real money")
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("a settlement needs a unique ref (the real-world transaction id)")
    usd_cents = int(usd_cents)
    if usd_cents <= 0:
        raise ValueError("settlement amount must be positive")
    amount_jly = float(amount_jly)
    if amount_jly <= 0:
        raise ValueError("JLY amount must be positive")
    conn = get_conn()
    try:
        dup = conn.execute("SELECT id FROM paychecks WHERE extra LIKE ?",
                           (f'%"jly_ref": "{ref}"%',)).fetchone()
        if dup:
            return {"ok": True, "duplicate": True, "paycheck_id": dup["id"],
                    "note": "already posted — settlements are idempotent on their ref"}
        extra = _json.dumps({"jly_ref": ref, "jly_amount": str(amount_jly), "basis": basis})
        cur = conn.execute(
            "INSERT INTO paychecks (source,amount_cents,received_at,cycle,notes,extra) "
            "VALUES (?,?,COALESCE(?,date('now')),'irregular',?,?)",
            (source[:120], usd_cents, received_at, (note or f"{amount_jly} JLY settled")[:300], extra))
        conn.commit()
        pid = cur.lastrowid
    finally:
        conn.close()
    set_fiat_rate(usd_cents / 100.0 / amount_jly, basis, ref=ref,
                  note=f"implied by settlement #{pid}")
    return {"ok": True, "duplicate": False, "paycheck_id": pid,
            "usd_per_jly": usd_cents / 100.0 / amount_jly, "basis": basis}


# ── what compute actually costs THIS node (the grounded default price) ───────
# The shipped default used to be "1 JLY per 1k tokens", which was a placeholder
# with nothing behind it. It is now DERIVED from two anchors, both of which can
# be re-measured on this hardware rather than taken on faith:
#
# ANCHOR 1 — energy floor (fiat). Measured 2026-07-19 on the real stack:
#   • throughput: 31.2 completion tok/s, warm, google/gemma-4-12b-qat on the
#     node's RTX 3060 — two back-to-back 400-word generations through the
#     store's own LLM proxy (417 tok/13.4 s and 430 tok/13.8 s). The first,
#     cold-start call measured 12.0 tok/s; that is model-load time, not
#     inference, so warm throughput is the honest figure for sustained work.
#   • power: 157-159 W GPU package draw at 84-88% utilisation during those
#     generations (nvidia-smi on the node, sampled through the run). Note this
#     is HIGHER than the ~94 W seen under mining load — LLM decode pushes this
#     card harder than the miner does, and 94 W turned out to be the between-
#     generations/idle-ish state (22-50% util), not the inference state.
#   • electricity price: NOT measured — there is no utility rate anywhere in
#     this repo and inventing one would poison the whole derivation. It is a
#     setting with a clearly-labelled PLACEHOLDER default.
#   GPU package power only: CPU, RAM, PSU losses and host idle are excluded
#   because nothing here can measure them (no wall meter). That makes the
#   energy figure a genuine FLOOR — the true cost is higher, never lower.
#   Hardware amortisation is EXCLUDED too: the repo holds no purchase price,
#   purchase date or expected service life for either card, and a depreciation
#   schedule made up to fill the gap would be precisely the fake number this
#   whole feature exists to avoid.
#
# ANCHOR 2 — mining opportunity cost (JLY-native, and the one that sets the
#   default). The same RTX 3060 either mines JellyCoin or serves peer tokens;
#   the store's GPU guard literally pauses the miner for queue work. So the
#   JLY-denominated cost of an answer is the JLY the miner would have earned in
#   the time it took to produce it. This needs NO exchange rate, no fiat peg and
#   no assumption — it is read live off this node's own chain (recent block
#   spacing × the current block reward, so it tracks halvings/emission changes
#   automatically). Pricing below it means he would rather have been mining.
#
# Default price = opportunity cost × margin, margin 1.0 = break-even.
COMPUTE_TOKS_KEY = "jelly_compute_tok_per_s"     # MEASURED
COMPUTE_WATTS_KEY = "jelly_compute_gpu_watts"    # MEASURED
COMPUTE_KWH_KEY = "jelly_compute_kwh_cost"       # PLACEHOLDER — owner must set
COMPUTE_MARGIN_KEY = "jelly_compute_margin"      # 1.0 = price at break-even

COMPUTE_TOKS_DEFAULT = 31.2      # completion tok/s, warm, gemma-4-12b-qat @ RTX 3060
COMPUTE_WATTS_DEFAULT = 158.0    # W, GPU package, measured under that load
COMPUTE_KWH_DEFAULT = 0.15       # USD/kWh — PLACEHOLDER, not measured, not researched
COMPUTE_MARGIN_DEFAULT = 1.0
COMPUTE_MEASURED_ON = "2026-07-19"
COMPUTE_MEASURED_MODEL = "google/gemma-4-12b-qat"
COMPUTE_MEASURED_GPU = "NVIDIA GeForce RTX 3060 (170 W limit)"
# Fallback when the chain is too young to read a mining rate from. Deliberately
# the OLD placeholder value, so an unconfigured brand-new install behaves exactly
# as it did before rather than inheriting a number derived from someone's chain.
COMPUTE_FALLBACK_PRICE = PEER_COMPLETION_PRICE_DEFAULT
MINING_SAMPLE_BLOCKS = 200       # recent blocks used for the spacing average
MINING_MIN_BLOCKS = 20           # below this we refuse to derive anything

_derived_cache: dict = {"at": 0.0, "value": None}


def mining_rate() -> dict:
    """JLY per second this node's miner earns, from its OWN chain. Returns
    enough_data=False (and no rate) rather than a guess on a young chain."""
    import statistics
    import jellycoin
    conn = get_conn()
    try:
        jellycoin._ensure(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT height,time FROM jelly_blocks ORDER BY height DESC LIMIT ?",
            (MINING_SAMPLE_BLOCKS + 1,)).fetchall()]
    except Exception:
        rows = []
    finally:
        conn.close()
    gaps = [rows[i]["time"] - rows[i + 1]["time"] for i in range(len(rows) - 1)]
    gaps = [g for g in gaps if g > 0]
    if len(gaps) < MINING_MIN_BLOCKS:
        return {"enough_data": False, "blocks": len(gaps), "min_blocks": MINING_MIN_BLOCKS,
                "why": "this chain has not produced enough blocks to read a mining rate from yet"}
    mean_gap = statistics.mean(gaps)
    reward = jellycoin.block_reward(rows[0]["height"])      # tracks halvings/emission changes
    return {"enough_data": True, "blocks": len(gaps),
            "mean_block_seconds": round(mean_gap, 2),
            "median_block_seconds": round(statistics.median(gaps), 2),
            "block_reward_jly": reward / jellycoin.UNIT,
            "jly_per_second": (reward / jellycoin.UNIT) / mean_gap}


def compute_cost_basis() -> dict:
    """The full derivation, with every input labelled by where it came from, so the
    owner can see WHY the default is what it is and correct any input he knows
    better than we do."""
    toks = max(0.1, _fsetting(COMPUTE_TOKS_KEY, COMPUTE_TOKS_DEFAULT))
    watts = max(0.0, _fsetting(COMPUTE_WATTS_KEY, COMPUTE_WATTS_DEFAULT))
    kwh_cost = max(0.0, _fsetting(COMPUTE_KWH_KEY, COMPUTE_KWH_DEFAULT))
    margin = max(0.0, _fsetting(COMPUTE_MARGIN_KEY, COMPUTE_MARGIN_DEFAULT))
    seconds_per_1k = 1000.0 / toks
    kwh_per_1k = watts * seconds_per_1k / 3_600_000.0        # W·s → kWh
    usd_per_1k = kwh_per_1k * kwh_cost
    mine = mining_rate()
    opp = (mine["jly_per_second"] * seconds_per_1k) if mine.get("enough_data") else None
    derived = round(opp * margin, 6) if opp is not None else None
    return {
        "measured_on": COMPUTE_MEASURED_ON, "model": COMPUTE_MEASURED_MODEL,
        "gpu": COMPUTE_MEASURED_GPU,
        "inputs": {
            "tok_per_s": {"value": toks, "provenance": "measured",
                          "note": "warm throughput, two back-to-back generations through the "
                                  "store's own LLM proxy (cold start measured 12.0 tok/s — "
                                  "that is model load, not inference)"},
            "gpu_watts": {"value": watts, "provenance": "measured",
                          "note": "GPU package draw at 84-88% utilisation during those "
                                  "generations; excludes CPU/RAM/PSU/host idle, so the "
                                  "energy figure is a floor, not a full cost"},
            "kwh_cost_usd": {"value": kwh_cost, "provenance": "placeholder",
                             "note": "NOT measured and NOT researched — set your actual "
                                     "utility rate; every fiat figure below moves with it"},
            "margin": {"value": margin, "provenance": "owner",
                       "note": "1.0 prices at break-even against mining the same card"},
        },
        "excluded": ["hardware amortisation (no purchase price, date or service life exists "
                     "anywhere in this repo — a made-up depreciation schedule would be a "
                     "fabricated number)",
                     "CPU / RAM / PSU / host idle draw (no wall meter available)"],
        "seconds_per_1k_tokens": round(seconds_per_1k, 2),
        "kwh_per_1k_tokens": kwh_per_1k,
        "energy_floor_usd_per_1k": usd_per_1k,
        "mining": mine,
        "opportunity_cost_jly_per_1k": (round(opp, 6) if opp is not None else None),
        "derived_default_jly_per_1k": derived,
        "fallback_jly_per_1k": COMPUTE_FALLBACK_PRICE,
        "note": ("The JLY figure is an opportunity cost against this node's OWN mining, so it "
                 "needs no exchange rate. JLY has no external market, so what a JLY price "
                 "means in dollars is only ever whatever you and a peer agree it means."),
    }


def derived_default_completion_price() -> float:
    """Default JLY per 1k completion tokens for a node that has never set one.
    Cached briefly — it reads the chain, and a rate is looked up per job."""
    now = time.time()
    if _derived_cache["value"] is not None and now - _derived_cache["at"] < 300:
        return _derived_cache["value"]
    try:
        basis = compute_cost_basis()
        val = basis["derived_default_jly_per_1k"]
    except Exception:
        val = None
    val = COMPUTE_FALLBACK_PRICE if val is None else val
    _derived_cache.update({"at": now, "value": val})
    return val


def invalidate_compute_cache():
    _derived_cache.update({"at": 0.0, "value": None})
