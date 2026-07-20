"""JellyCoin (JLY) — the store's OWN token, mined by REAL GPU proof-of-work.

What this is (honest scope): a single-node chain where THIS Store is the
authority. Wallets are custodial ledger accounts (name → balance) kept in the
store DB; transfers are final the moment they're recorded. What makes it a
*coin* and not a points table is issuance: new JLY exists ONLY when a real GPU
solves a real sha256d proof-of-work block against a live difficulty target.
There is no CPU mining path anywhere — the shipped miner (miner/jellyminer.py)
refuses to run without an OpenCL GPU, and the server never mines at all.

  - Money: integer micro-JLY (1 JLY = 1_000_000 ujly) — no float drift.
  - PoW:   message = header76 + nonce(4B big-endian); sha256(sha256(msg)) read
           big-endian must be < target. header76 = prev(32) + merkle(32) +
           height(4 BE) + time(4 BE) + reserved(4). Retarget every
           RETARGET_INTERVAL blocks toward TARGET_BLOCK_SEC, clamped 4x.
  - Company tie-in: agent skilling (woodcutting/mining/fishing/…) records
    "boost tickets" (world_sim hook, gated by the God-Console toggle
    world_crypto_mining_enabled). Tickets pay out ONLY when a GPU actually
    mines a block — the block mints a small bonus split agent/company. No GPU
    online → tickets just expire. Skilling never mines by itself.
  - NFTs: mint a token from a real art file (sha256 of the bytes is the
    on-chain content hash); small JLY fee to the treasury; transferable.

Reused by routers/jellycoin.py (API), world_sim.py (skill_pulse) and tests.
"""
import hashlib
import json
import secrets
import struct
import threading
import time

from deps import get_conn, get_setting

# ── tokenomics / consensus constants ─────────────────────────────────────────
SYMBOL = "JLY"
UNIT = 1_000_000                      # ujly per JLY
BLOCK_REWARD = 50 * UNIT              # halves every HALVING_INTERVAL blocks
HALVING_INTERVAL = 50_000
PREMINE = 1_000_000 * UNIT            # genesis → treasury (store-side economy float)
TARGET_BLOCK_SEC = 60
RETARGET_INTERVAL = 20                # blocks between difficulty adjustments
MAX_TARGET = 1 << 240                 # easiest allowed target (~65k hashes/block avg)
WORK_TTL_SEC = 600                    # issued work expires
MINER_FRESH_SEC = 300                 # heartbeat window for "online" rigs

# ── the hard cap ─────────────────────────────────────────────────────────────
# 6,000,000 JLY, and nothing may ever mint past it.
#
# Why this number: it is what the schedule ALREADY implies, rounded to a clean
# figure. Summing the halving series exactly — Σ (50 JLY >> k) × 50_000 blocks
# for k = 0..25, after which the integer reward shifts to zero at height
# 1,300,000 — gives 4,999,999.4 JLY of mining subsidy. Plus the 1,000,000 JLY
# genesis premine that is 6,000,000 minus 0.6 JLY. Rounding up to 6,000,000
# rather than picking a new number means the cap does NOT change the emission
# any live holder was already promised: it ratifies the existing curve instead
# of rewriting it.
#
# The cap is a ceiling on TOTAL emission, not on the block subsidy alone. Boost
# payouts (below) mint inside real blocks and were previously unbounded, which
# is the hole this closes: they now draw from the same 6M pool. Because they do,
# the subsidy tail runs out slightly EARLIER than height 1,300,000 — boosts
# spend headroom that would otherwise have gone to the final coinbases. That is
# intended, and it is the only honest way to have one cap mean one number.
MAX_SUPPLY = 6_000_000 * UNIT

# Company skilling boosts — tickets only cash out inside a REAL mined block,
# and (since the cap) only to the extent the cap has headroom left over after
# that block's coinbase. The subsidy has priority; boosts take the remainder.
BOOST_PER_TICKET = UNIT // 20         # 0.05 JLY minted per ticket…
BOOST_MAX_PER_BLOCK = 20 * UNIT       # …capped per block
BOOST_MAX_PENDING = 500               # ticket queue cap (oldest kept)
BOOST_TTL_SEC = 86_400                # unpaid tickets expire after a day
BOOST_AGENT_SHARE = 0.5               # rest goes to the company wallet

# Unpaid tickets are never silently dropped. They are marked expired with a
# human-readable reason and kept as a row, so the ledger can always answer
# "what happened to the value I earned?".
BOOST_EXPIRY_TTL = "unpaid for 24h — no block was mined in time"
BOOST_EXPIRY_CAP = "supply cap reached — no headroom left to mint boosts"

# ── emergency difficulty adjustment (stall recovery) ─────────────────────────
# This chain has one node and no P2P, so difficulty only ever retargets when a
# block lands. If the rigs that set a hard target all vanish, nothing can pull
# the target back down — the chain simply stops, permanently. That is a real
# dead end, so work issued during a stall is progressively EASED: after
# EDA_AFTER_SEC of silence the target is multiplied by (idle / TARGET_BLOCK_SEC),
# growing the longer the silence lasts, until some rig can find a block again.
# It self-clears the instant a block lands (idle resets to ~0 ⇒ factor 1.0) and
# it can never mint more than the cap allows, so it changes liveness only.
EDA_ENABLED_KEY = "jelly_eda_enabled"   # settings toggle, default "1" (ON)
EDA_AFTER_SEC = TARGET_BLOCK_SEC * 20   # 20 min of no blocks before easing starts
EDA_MAX_EASE = 1 << 32                  # ceiling on a single easing step

NFT_MINT_FEE = 5 * UNIT

# ── buddy-share mining pool (M1) — proportional share-based reward splitting ──
# OFF by default: when off, mining is byte-for-byte the winner-take-all path.
# When ON, rigs grind to a SHARE target (SHARE_FACTOR× easier than the block
# target) and submit frequent shares; the block reward is split pro-rata by the
# shares each owner contributed this round. POOL_FEE_PCT is 0 for M1 (no fee).
POOL_ENABLED_KEY = "jelly_pool_enabled"   # settings toggle, default "0" (OFF)
SHARE_FACTOR = 65536                       # share target = block target × this
POOL_FEE_PCT = 0                           # M1: no pool fee
_MAX_HASH = (1 << 256) - 1                 # keep share_target within 64-hex

# Well-known wallets (created on demand). 'assistant' is the AI friend's purse.
TREASURY, COMPANY, ASSISTANT = "treasury", "company", "assistant"
ASSISTANT_GRANT = 500 * UNIT          # one-time treasury grant so the friend can tip

# ── host vs joined: found your own chain, or join a buddy's network ──────────
# Every store used to write its own genesis on first touch, so ten friends
# installing the store made TEN unrelated coins — the opposite of a network.
# In "joined" mode this node founds NO chain at all: no genesis, no premine, no
# local mining. The buddy's node IS the ledger; we participate on it (our wallet
# there is read over the peer RPC, our rigs point at their URL). Default stays
# "host" so every existing install and its chain are untouched.
JELLY_MODE_KEY = "jelly_mode"          # "host" (default) | "joined"
JELLY_HOME_KEY = "jelly_home_peer"     # paired peer name whose network we joined


def jelly_mode() -> str:
    """'joined' only when explicitly set — anything else (or unreadable) is 'host'.
    Read defensively: this gates genesis, and it runs during schema bootstrap when
    the settings table may not be readable yet. Failing closed to 'host' preserves
    the historical behavior exactly."""
    try:
        return "joined" if str(get_setting(JELLY_MODE_KEY) or "host").strip().lower() == "joined" else "host"
    except Exception:
        return "host"


def jelly_home_peer() -> str:
    """Name of the paired peer whose chain we joined ('' when hosting)."""
    try:
        return str(get_setting(JELLY_HOME_KEY) or "").strip()
    except Exception:
        return ""


_GENESIS_PREV = "0" * 64
_lock = threading.Lock()
_works: dict = {}                     # work_id → dict (issued PoW jobs, in-memory)
_schema_done = False


# ── schema ───────────────────────────────────────────────────────────────────
def ensure_schema(conn=None):
    global _schema_done
    own = conn is None
    if own:
        conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS jelly_blocks (
            height  INTEGER PRIMARY KEY,
            hash    TEXT NOT NULL,
            prev    TEXT NOT NULL,
            merkle  TEXT NOT NULL,
            target  TEXT NOT NULL,
            nonce   INTEGER NOT NULL,
            time    INTEGER NOT NULL,
            miner   TEXT NOT NULL,
            reward  INTEGER NOT NULL,
            boost   INTEGER NOT NULL DEFAULT 0,
            txs     TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS jelly_wallets (
            name       TEXT PRIMARY KEY,
            address    TEXT UNIQUE,
            balance    INTEGER NOT NULL DEFAULT 0,
            kind       TEXT NOT NULL DEFAULT 'user',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS jelly_txs (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            height INTEGER,
            time   INTEGER NOT NULL,
            frm    TEXT,
            dst    TEXT,
            amount INTEGER NOT NULL,
            kind   TEXT NOT NULL,
            memo   TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS jelly_miners (
            name      TEXT PRIMARY KEY,
            gpu       TEXT DEFAULT '',
            last_seen INTEGER NOT NULL DEFAULT 0,
            blocks    INTEGER NOT NULL DEFAULT 0,
            hashrate  REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS jelly_boosts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_key  TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            skill      TEXT NOT NULL,
            units      INTEGER NOT NULL DEFAULT 1,
            created    INTEGER NOT NULL,
            height     INTEGER              -- paid out in this block (NULL = pending)
        );
        CREATE TABLE IF NOT EXISTS jelly_nfts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id      TEXT UNIQUE NOT NULL,
            title         TEXT NOT NULL,
            file_path     TEXT NOT NULL,
            sha256        TEXT NOT NULL,
            meta          TEXT DEFAULT '{}',
            owner         TEXT NOT NULL,
            minted_height INTEGER NOT NULL,
            created_at    TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS jelly_missions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            kind       TEXT NOT NULL,
            title      TEXT NOT NULL,
            pitch      TEXT NOT NULL,
            agent      TEXT DEFAULT '',
            status     TEXT NOT NULL DEFAULT 'proposed',
            created_at TEXT DEFAULT (datetime('now')),
            decided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS jelly_shares (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            rig      TEXT,
            owner    TEXT,
            round_id INTEGER,
            weight   REAL DEFAULT 1,
            created  INTEGER
        );
        """)
        # buddy-share pool: a rig can be mapped to a peer:<name> payout wallet
        # (default owner is miner:<name>). Idempotent migration for old DBs.
        try:
            conn.execute("ALTER TABLE jelly_miners ADD COLUMN owner TEXT")
        except Exception:
            pass
        # Boost tickets that will never be paid used to be DELETEd outright, which
        # made owed value vanish with no trace. Keep the row and record WHY it was
        # dropped instead. Purely additive: two nullable columns, old rows read as
        # (NULL, NULL) = "not expired", which is exactly their historical meaning,
        # and dropping the columns again restores the previous schema.
        for ddl in ("ALTER TABLE jelly_boosts ADD COLUMN expired INTEGER",
                    "ALTER TABLE jelly_boosts ADD COLUMN expired_reason TEXT"):
            try:
                conn.execute(ddl)
            except Exception:
                pass
        # Found a chain ONLY when hosting. A joined node is a participant on a
        # buddy's ledger, so minting it a genesis + premine here would be exactly
        # the island-per-install problem. Tables still exist (peer wallets, txs).
        if (jelly_mode() == "host"
                and not conn.execute("SELECT 1 FROM jelly_blocks WHERE height=0").fetchone()):
            _write_genesis(conn)
        conn.commit()
        _schema_done = True
    finally:
        if own:
            conn.close()


def _ensure(conn):
    if not _schema_done:
        ensure_schema(conn)


def _write_genesis(conn):
    t = int(time.time())
    merkle = _sha256_hex(f"acme-genesis:{PREMINE}".encode())
    header = _header76(_GENESIS_PREV, merkle, 0, t)
    h = _pow_hash(header, 0)
    conn.execute(
        "INSERT INTO jelly_blocks (height,hash,prev,merkle,target,nonce,time,miner,reward,boost,txs)"
        " VALUES (0,?,?,?,?,0,?, 'genesis',?,0,?)",
        (h, _GENESIS_PREV, merkle, f"{MAX_TARGET:064x}", t, PREMINE,
         json.dumps([{"kind": "premine", "dst": TREASURY, "amount": PREMINE}])))
    _wallet(conn, TREASURY, kind="system")
    conn.execute("UPDATE jelly_wallets SET balance=balance+? WHERE name=?", (PREMINE, TREASURY))
    conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (0,?,NULL,?,?,?,?)",
                 (t, TREASURY, PREMINE, "premine", "JellyCoin genesis premine"))
    # fund the AI friend's tipping purse out of the premine
    _wallet(conn, ASSISTANT, kind="system")
    conn.execute("UPDATE jelly_wallets SET balance=balance-? WHERE name=?", (ASSISTANT_GRANT, TREASURY))
    conn.execute("UPDATE jelly_wallets SET balance=balance+? WHERE name=?", (ASSISTANT_GRANT, ASSISTANT))
    conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (0,?,?,?,?,?,?)",
                 (t, TREASURY, ASSISTANT, ASSISTANT_GRANT, "grant", "AI-friend tipping grant"))
    _wallet(conn, COMPANY, kind="system")


# ── hashing / PoW primitives (MUST match miner/jellyminer.py exactly) ────────
def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _header76(prev_hex: str, merkle_hex: str, height: int, t: int) -> bytes:
    return (bytes.fromhex(prev_hex) + bytes.fromhex(merkle_hex)
            + struct.pack(">I", height) + struct.pack(">I", t) + b"\x00\x00\x00\x00")


def _pow_hash(header76: bytes, nonce: int) -> str:
    msg = header76 + struct.pack(">I", nonce)
    return hashlib.sha256(hashlib.sha256(msg).digest()).hexdigest()


def meets_target(hash_hex: str, target: int) -> bool:
    return int(hash_hex, 16) < target


def difficulty(target: int) -> float:
    """Human-readable difficulty relative to the easiest target (1.0 = genesis)."""
    return MAX_TARGET / max(1, target)


# ── wallets & transfers ──────────────────────────────────────────────────────
_KIND_PREFIX = {"peer:": "peer", "miner:": "miner", "agent:": "agent"}


def _wallet(conn, name: str, kind: str = "user"):
    row = conn.execute("SELECT * FROM jelly_wallets WHERE name=?", (name,)).fetchone()
    if row:
        return row
    if kind == "user":      # auto-created wallets (e.g. a transfer target) keep their kind
        kind = next((k for pre, k in _KIND_PREFIX.items() if name.startswith(pre)), "user")
    addr = "jly1" + secrets.token_hex(18)
    conn.execute("INSERT INTO jelly_wallets (name,address,balance,kind) VALUES (?,?,0,?)",
                 (name, addr, kind))
    return conn.execute("SELECT * FROM jelly_wallets WHERE name=?", (name,)).fetchone()


def wallet(name: str, kind: str = "user", conn=None) -> dict:
    own = conn is None
    if own:
        conn = get_conn()
    try:
        _ensure(conn)
        row = _wallet(conn, name, kind)
        if own:
            conn.commit()
        return dict(row)
    finally:
        if own:
            conn.close()


def transfer(frm: str, dst: str, amount: int, memo: str = "", kind: str = "transfer") -> dict:
    """Move ujly between named wallets. Atomic; raises ValueError on bad input."""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    if frm == dst:
        raise ValueError("cannot send to self")
    conn = get_conn()
    try:
        _ensure(conn)
        with _lock:
            src = _wallet(conn, frm)
            _wallet(conn, dst)
            if src["balance"] < amount:
                raise ValueError(f"insufficient funds: {frm} has {src['balance']/UNIT:.2f} {SYMBOL}")
            conn.execute("UPDATE jelly_wallets SET balance=balance-? WHERE name=?", (amount, frm))
            conn.execute("UPDATE jelly_wallets SET balance=balance+? WHERE name=?", (amount, dst))
            tip_h = _tip_height(conn)
            conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,?,?,?,?,?)",
                         (tip_h, int(time.time()), frm, dst, amount, kind, memo[:300]))
            conn.commit()
        return {"ok": True, "from": frm, "to": dst, "amount": amount}
    finally:
        conn.close()


# ── chain state ──────────────────────────────────────────────────────────────
def _tip(conn):
    return conn.execute("SELECT * FROM jelly_blocks ORDER BY height DESC LIMIT 1").fetchone()


def _tip_height(conn) -> int:
    r = _tip(conn)
    return int(r["height"]) if r else 0


def block_reward(height: int) -> int:
    """The SCHEDULED subsidy at a height, ignoring the cap. Used for projections
    and display. What a block actually pays is effective_block_reward()."""
    return BLOCK_REWARD >> (height // HALVING_INTERVAL)


# ── supply accounting ────────────────────────────────────────────────────────
# The block table is the single authority. Every ujly that has ever existed was
# written into jelly_blocks as either `reward` (genesis premine + coinbases) or
# `boost` (skilling payouts), so summing those two columns IS the money supply —
# it does not depend on wallet balances being right, which is precisely what
# makes it usable to audit them.
def minted_total(conn) -> int:
    return int(conn.execute(
        "SELECT COALESCE(SUM(reward),0)+COALESCE(SUM(boost),0) s FROM jelly_blocks").fetchone()["s"])


def burned_total(conn) -> int:
    """Provably destroyed coin. No burn path exists today (this is always 0);
    it is computed rather than assumed so that adding one later cannot silently
    desynchronise the cap arithmetic."""
    try:
        return int(conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM jelly_txs WHERE kind='burn'").fetchone()["s"])
    except Exception:
        return 0


def circulating(conn) -> int:
    return max(0, minted_total(conn) - burned_total(conn))


def remaining_headroom(conn) -> int:
    """ujly that may still be minted before MAX_SUPPLY. Never negative."""
    return max(0, MAX_SUPPLY - circulating(conn))


def effective_block_reward(conn, height: int) -> int:
    """The subsidy this block may actually pay: the schedule, TRIMMED to whatever
    headroom is left under the cap. The block that reaches the cap pays exactly
    the remainder rather than overshooting it; every block after that pays 0."""
    return max(0, min(block_reward(height), remaining_headroom(conn)))


def eda_enabled() -> bool:
    """Stall-recovery easing. Default ON — without it a chain whose rigs all die
    is dead for good. Toggleable because it is a consensus-visible behaviour."""
    try:
        return str(get_setting(EDA_ENABLED_KEY) or "1") in ("1", "true", "on")
    except Exception:
        return True


def _eda_ease(tip_time: int, now: int) -> int:
    """Integer multiplier applied to the target when the chain has gone quiet: 1
    (no change) until EDA_AFTER_SEC of silence, then one step easier per missed
    block interval, so recovery is guaranteed rather than merely hoped for."""
    idle = now - int(tip_time)
    if idle < EDA_AFTER_SEC:
        return 1
    return max(1, min(EDA_MAX_EASE, idle // TARGET_BLOCK_SEC))


def current_target(conn, now: int = None) -> int:
    """Retarget every RETARGET_INTERVAL blocks toward TARGET_BLOCK_SEC, clamped 4x,
    then ease if the chain has stalled (see EDA notes at the top of this module)."""
    tip = _tip(conn)
    height = int(tip["height"])
    target = int(tip["target"], 16)
    nxt = height + 1
    if nxt >= RETARGET_INTERVAL and not nxt % RETARGET_INTERVAL:
        first = conn.execute("SELECT time FROM jelly_blocks WHERE height=?",
                             (height - RETARGET_INTERVAL + 1,)).fetchone()
        if first:
            actual = max(1, int(tip["time"]) - int(first["time"]))
            expected = TARGET_BLOCK_SEC * (RETARGET_INTERVAL - 1)
            # Clamp the RATIO to [1/4, 4] by clamping `actual`, then scale with exact
            # integer arithmetic. The old `int(target * ratio)` multiplied a 240-bit
            # target by a float, which loses ~53 bits of precision and could round the
            # result just PAST the 4x clamp it was supposed to enforce. The numeric
            # difference is negligible (~1e-16 relative, far below one difficulty step,
            # so the live chain's target is unchanged in any observable way) but the
            # clamp is now a real bound instead of an approximate one.
            actual = min(max(actual, expected // 4), expected * 4)
            target = min(MAX_TARGET, max(1, target * actual // expected))
    if eda_enabled():
        target *= _eda_ease(int(tip["time"]), int(time.time()) if now is None else now)
    return min(MAX_TARGET, max(1, target))


# ── mining: getwork / submit ─────────────────────────────────────────────────
def get_work(miner: str, gpu: str = "", hashrate: float = 0.0) -> dict:
    """Issue a PoW job to a GPU rig and record its heartbeat."""
    miner = (miner or "").strip()[:40]
    if not miner:
        raise ValueError("miner name required")
    if jelly_mode() == "joined":
        # Refuse rather than quietly founding an island chain under a rig that
        # thinks it is mining the network. Point it at the home node instead.
        home = jelly_home_peer()
        raise ValueError(
            "This node is a participant on " + (f"{home}'s network" if home else "another node's network")
            + ", not a chain of its own — point this rig at the home node's URL "
              "(Crypto → JellyCoin → Join a buddy's network).")
    conn = get_conn()
    try:
        _ensure(conn)
        now = int(time.time())
        conn.execute("INSERT INTO jelly_miners (name,gpu,last_seen,hashrate) VALUES (?,?,?,?) "
                     "ON CONFLICT(name) DO UPDATE SET gpu=excluded.gpu, last_seen=excluded.last_seen, "
                     "hashrate=excluded.hashrate", (miner, (gpu or "")[:120], now, float(hashrate or 0)))
        conn.commit()
        tip = _tip(conn)
        height = int(tip["height"]) + 1
        target = current_target(conn)
        share_target = min(_MAX_HASH, target * SHARE_FACTOR)   # easier → frequent shares
        merkle = _sha256_hex(f"{height}:{tip['hash']}:{now}:{miner}".encode())
        header = _header76(tip["hash"], merkle, height, now)
        work_id = secrets.token_hex(8)
        with _lock:
            for wid in [w for w, v in _works.items() if now - v["issued"] > WORK_TTL_SEC]:
                _works.pop(wid, None)
            _works[work_id] = {"header": header, "prev": tip["hash"], "merkle": merkle,
                               "height": height, "time": now, "target": target,
                               "share_target": share_target, "miner": miner, "issued": now}
        resp = {"work_id": work_id, "header76": header.hex(), "target": f"{target:064x}",
                "height": height, "difficulty": difficulty(target),
                "symbol": SYMBOL, "reward": effective_block_reward(conn, height) / UNIT}
        # Only advertise the share target when pooling is ON — with it absent the
        # getwork response is byte-for-byte today's, and the miner stays solo.
        if pool_enabled():
            resp["share_target"] = f"{share_target:064x}"
        return resp
    finally:
        conn.close()


def submit_work(work_id: str, nonce: int, miner: str) -> dict:
    """Validate a found nonce; on success append the block and pay coinbase + boosts."""
    with _lock:
        w = _works.get(work_id)
    if not w:
        return {"ok": False, "reason": "unknown or expired work"}
    nonce = int(nonce) & 0xFFFFFFFF
    h = _pow_hash(w["header"], nonce)
    if pool_enabled():
        return _submit_pool_work(work_id, w, nonce, h, miner)
    if not meets_target(h, w["target"]):
        return {"ok": False, "reason": "hash does not meet target"}
    conn = get_conn()
    try:
        _ensure(conn)
        with _lock:
            tip = _tip(conn)
            if tip["hash"] != w["prev"]:
                return {"ok": False, "reason": "stale: chain moved on"}
            height, now = w["height"], int(time.time())
            # THE CAP. Everything minted below draws from this one number, and
            # the subsidy is trimmed to it rather than allowed to overshoot.
            headroom = remaining_headroom(conn)
            reward = max(0, min(block_reward(height), headroom))
            miner = (miner or w["miner"]).strip()[:40]
            miner_wallet = f"miner:{miner}"
            _wallet(conn, miner_wallet, kind="miner")
            txs = []
            if reward:
                txs.append({"kind": "coinbase", "dst": miner_wallet, "amount": reward})
            # cash out pending Company skilling boosts INSIDE this real block, but
            # only from whatever the coinbase left under the cap
            boost_total = _payout_boosts(conn, height, now, txs, headroom - reward)
            conn.execute(
                "INSERT INTO jelly_blocks (height,hash,prev,merkle,target,nonce,time,miner,reward,boost,txs)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (height, h, w["prev"], w["merkle"], f"{w['target']:064x}", nonce, now,
                 miner, reward, boost_total, json.dumps(txs)))
            # A capped-out block is still a valid block — it orders and secures the
            # chain. It just pays nobody, so it writes no coinbase credit at all.
            if reward:
                conn.execute("UPDATE jelly_wallets SET balance=balance+? WHERE name=?", (reward, miner_wallet))
                conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,NULL,?,?,?,?)",
                             (height, now, miner_wallet, reward, "coinbase", f"block {height} reward"))
            conn.execute("UPDATE jelly_miners SET blocks=blocks+1, last_seen=? WHERE name=?", (now, miner))
            conn.commit()
            _works.pop(work_id, None)
        return {"ok": True, "height": height, "hash": h, "reward": reward / UNIT,
                "boost_paid": boost_total / UNIT, "wallet": miner_wallet}
    finally:
        conn.close()


def _expire_boosts(conn, when: int, reason: str, sql_where: str, params: tuple = ()):
    """Mark unpaid tickets dead WITH A REASON instead of deleting them. Nothing
    that was owed ever just disappears from the ledger — it becomes a row you
    can point at."""
    conn.execute(f"UPDATE jelly_boosts SET expired=?, expired_reason=? "
                 f"WHERE height IS NULL AND expired IS NULL AND {sql_where}",
                 (when, reason) + params)


def _payout_boosts(conn, height: int, now: int, txs: list, headroom: int) -> int:
    """Mint skilling boosts inside a real block, bounded by `headroom` — the ujly
    left under MAX_SUPPLY after this block's coinbase.

    Ticket policy, in order:
      • too old (BOOST_TTL_SEC)  → expired, reason recorded, never paid.
      • headroom is zero         → expired, reason recorded. The cap is permanent
                                   (there is no burn path, so headroom never comes
                                   back), so holding them pending forever would be
                                   a lie about value that can never be paid.
      • headroom is partial      → pay as many whole tickets as fit; the rest stay
                                   PENDING and are first in line next block.
    """
    _expire_boosts(conn, now, BOOST_EXPIRY_TTL, "created < ?", (now - BOOST_TTL_SEC,))
    if headroom < BOOST_PER_TICKET:
        # Not even one ticket fits. If the cap is genuinely exhausted, say so and
        # close the queue out; if it is merely a tight final block, leave them.
        if remaining_headroom(conn) <= 0:
            _expire_boosts(conn, now, BOOST_EXPIRY_CAP, "1=1")
        return 0
    limit = min(BOOST_MAX_PER_BLOCK // BOOST_PER_TICKET, headroom // BOOST_PER_TICKET)
    rows = conn.execute("SELECT * FROM jelly_boosts WHERE height IS NULL AND expired IS NULL "
                        "ORDER BY id LIMIT ?", (limit,)).fetchall()
    total = 0
    per_agent: dict = {}
    for r in rows:
        conn.execute("UPDATE jelly_boosts SET height=? WHERE id=?", (height, r["id"]))
        per_agent[r["agent_key"]] = per_agent.get(r["agent_key"], 0) + BOOST_PER_TICKET
        total += BOOST_PER_TICKET
    if not total:
        return 0
    _wallet(conn, COMPANY, kind="system")
    company_cut = 0
    for key, amt in per_agent.items():
        agent_amt = int(amt * BOOST_AGENT_SHARE)
        company_cut += amt - agent_amt
        wname = f"agent:{key}"
        _wallet(conn, wname, kind="agent")
        conn.execute("UPDATE jelly_wallets SET balance=balance+? WHERE name=?", (agent_amt, wname))
        conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,NULL,?,?,?,?)",
                     (height, now, wname, agent_amt, "boost", "skilling boost payout"))
        txs.append({"kind": "boost", "dst": wname, "amount": agent_amt})
    conn.execute("UPDATE jelly_wallets SET balance=balance+? WHERE name=?", (company_cut, COMPANY))
    conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,NULL,?,?,?,?)",
                 (height, now, COMPANY, company_cut, "boost", "company share of skilling boosts"))
    txs.append({"kind": "boost", "dst": COMPANY, "amount": company_cut})
    return total


# ── buddy-share mining pool (M1) ─────────────────────────────────────────────
def pool_enabled() -> bool:
    """Master toggle (default OFF). OFF ⇒ mining is exactly winner-take-all."""
    return str(get_setting(POOL_ENABLED_KEY) or "0") in ("1", "true", "on")


def _rig_owner(conn, name: str) -> str:
    """Payout wallet for a rig: its mapped owner (e.g. peer:<name>) or miner:<name>."""
    try:
        row = conn.execute("SELECT owner FROM jelly_miners WHERE name=?", (name,)).fetchone()
    except Exception:
        row = None
    if row is not None and row["owner"]:
        return row["owner"]
    return f"miner:{name}"


def _submit_pool_work(work_id: str, w: dict, nonce: int, h: str, miner: str) -> dict:
    """Pool path: every hash under the SHARE target records a share; a hash that
    ALSO meets the block target mints the block and splits its reward pro-rata."""
    share_tgt = w.get("share_target") or min(_MAX_HASH, w["target"] * SHARE_FACTOR)
    if not meets_target(h, share_tgt):
        return {"ok": False, "reason": "hash does not meet share target"}
    conn = get_conn()
    try:
        _ensure(conn)
        with _lock:
            height, now = w["height"], int(time.time())
            miner = (miner or w["miner"]).strip()[:40]
            owner = _rig_owner(conn, miner)
            conn.execute("INSERT INTO jelly_shares (rig,owner,round_id,weight,created) "
                         "VALUES (?,?,?,1,?)", (miner, owner, height, now))
            if not meets_target(h, w["target"]):          # share only, no block
                conn.commit()
                return {"ok": True, "share": True, "block": False,
                        "height": height, "owner": owner}
            tip = _tip(conn)
            if tip["hash"] != w["prev"]:                  # block is stale; keep the share
                conn.commit()
                return {"ok": True, "share": True, "block": False,
                        "reason": "stale: chain moved on", "height": height, "owner": owner}
            headroom = remaining_headroom(conn)            # same cap, same trim
            reward = max(0, min(block_reward(height), headroom))
            txs: list = []
            boost_total = _payout_boosts(conn, height, now, txs, headroom - reward)
            splits = _split_pool_reward(conn, height, reward, owner, now, txs) if reward else {}
            conn.execute(
                "INSERT INTO jelly_blocks (height,hash,prev,merkle,target,nonce,time,miner,reward,boost,txs)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (height, h, w["prev"], w["merkle"], f"{w['target']:064x}", nonce, now,
                 miner, reward, boost_total, json.dumps(txs)))
            conn.execute("UPDATE jelly_miners SET blocks=blocks+1, last_seen=? WHERE name=?", (now, miner))
            conn.execute("DELETE FROM jelly_shares WHERE round_id=?", (height,))
            conn.commit()
            _works.pop(work_id, None)
        return {"ok": True, "share": True, "block": True, "height": height, "hash": h,
                "reward": reward / UNIT, "boost_paid": boost_total / UNIT,
                "splits": {o: a / UNIT for o, a in splits.items()}, "owner": owner}
    finally:
        conn.close()


def _split_pool_reward(conn, height: int, reward: int, solver_owner: str,
                       now: int, txs: list) -> dict:
    """Mint `reward` ujly split pro-rata by this round's shares (grouped by owner).
    Integer accounting: each cut is floor(reward × weight / total); any rounding
    remainder goes to the block solver's owner, so sum(splits) == reward exactly.
    No shares recorded (edge case) → the solver takes the whole reward."""
    rows = conn.execute("SELECT owner, SUM(weight) w FROM jelly_shares WHERE round_id=? "
                        "GROUP BY owner", (height,)).fetchall()
    weighted = [(r["owner"], int(round(float(r["w"] or 0)))) for r in rows]
    total = sum(w for _, w in weighted)
    payouts: dict = {}
    if total <= 0:                                        # fallback: solver takes all
        payouts[solver_owner] = reward
    else:
        for own, wt in weighted:
            payouts[own] = payouts.get(own, 0) + reward * wt // total
        remainder = reward - sum(payouts.values())       # give rounding dust to solver
        if remainder:
            payouts[solver_owner] = payouts.get(solver_owner, 0) + remainder
    for own, amt in payouts.items():
        if amt <= 0:
            continue
        _wallet(conn, own, kind="peer" if own.startswith("peer:") else "miner")
        conn.execute("UPDATE jelly_wallets SET balance=balance+? WHERE name=?", (amt, own))
        conn.execute("INSERT INTO jelly_txs (height,time,frm,dst,amount,kind,memo) VALUES (?,?,NULL,?,?,?,?)",
                     (height, now, own, amt, "coinbase", f"pool block {height} share reward"))
        txs.append({"kind": "coinbase", "dst": own, "amount": amt})
    return payouts


def pool_state() -> dict:
    """Snapshot for the /api/jelly/pool endpoint: toggle, current round's shares,
    the reward split those shares project to, and recent pool payouts."""
    conn = get_conn()
    try:
        _ensure(conn)
        height = _tip_height(conn) + 1
        reward = effective_block_reward(conn, height)
        rows = conn.execute("SELECT rig, owner, COUNT(*) shares, SUM(weight) w FROM jelly_shares "
                            "WHERE round_id=? GROUP BY rig, owner ORDER BY w DESC", (height,)).fetchall()
        shares_by_rig = [dict(r) for r in rows]
        by_owner: dict = {}
        for r in rows:
            by_owner[r["owner"]] = by_owner.get(r["owner"], 0) + int(round(float(r["w"] or 0)))
        total = sum(by_owner.values())
        projected = {o: (reward * w // total) / UNIT for o, w in by_owner.items()} if total > 0 else {}
        recent = [dict(r) for r in conn.execute(
            "SELECT height,time,dst,amount,memo FROM jelly_txs "
            "WHERE kind='coinbase' AND memo LIKE 'pool block%' ORDER BY id DESC LIMIT 20")]
        return {"enabled": pool_enabled(), "share_factor": SHARE_FACTOR,
                "round_id": height, "block_reward_jly": reward / UNIT,
                "shares_by_rig": shares_by_rig, "projected_split": projected,
                "recent_payouts": recent}
    finally:
        conn.close()


def chain_is_used(conn=None) -> bool:
    """Has this node's own chain done anything beyond its genesis premine?

    Guards the switch to joined mode: leaving a chain that has mined blocks (or
    moved coins) behind would orphan real value — nobody else has that ledger."""
    own = conn is None
    conn = conn or get_conn()
    try:
        if _tip_height(conn) > 0:
            return True
        return bool(conn.execute(
            "SELECT 1 FROM jelly_txs WHERE kind NOT IN ('premine','grant') LIMIT 1").fetchone())
    except Exception:
        return True                       # unreadable → assume used, refuse to switch
    finally:
        if own:
            conn.close()


def set_jelly_mode(mode: str, home_peer: str = "") -> dict:
    """Found our own chain ('host') or join a buddy's network ('joined').

    Switching to joined is refused once our chain has been used — those coins
    exist only on this ledger. Switching back to host writes the genesis that
    joined mode skipped (via ensure_schema, whose cache we clear first)."""
    global _schema_done
    mode = (mode or "").strip().lower()
    if mode not in ("host", "joined"):
        raise ValueError("mode must be 'host' or 'joined'")
    if mode == "joined":
        if not (home_peer or "").strip():
            raise ValueError("joining a network needs the buddy's peer name")
        if chain_is_used():
            raise ValueError(
                "This node's own chain already has mined blocks or transfers — joining "
                "another network would strand them. Keep hosting, or start from a fresh "
                "store install to join.")
    conn = get_conn()
    try:
        _ensure(conn)
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (JELLY_MODE_KEY, mode))
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (JELLY_HOME_KEY, (home_peer or "").strip() if mode == "joined" else ""))
        if mode == "joined":
            # A fresh install founds its chain on first touch, so by the time the
            # user picks "join" a genesis + premine usually already exists. We
            # verified above that nothing has USED it, so clear it out — otherwise
            # a stale tip would keep reporting a local chain we no longer have.
            conn.execute("DELETE FROM jelly_blocks")
            conn.execute("DELETE FROM jelly_txs WHERE kind IN ('premine','grant')")
            conn.execute("UPDATE jelly_wallets SET balance=0")
        conn.commit()
    finally:
        conn.close()
    _schema_done = False                  # re-run bootstrap: host mode must get its genesis
    ensure_schema()
    return {"mode": jelly_mode(), "home_peer": jelly_home_peer()}


def set_pool_enabled(on: bool):
    conn = get_conn()
    try:
        _ensure(conn)
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (POOL_ENABLED_KEY, "1" if on else "0"))
        conn.commit()
    finally:
        conn.close()


def set_rig_owner(rig: str, owner: str):
    """Map a named rig to a payout wallet (e.g. a buddy's peer:<name> custodial wallet)."""
    rig = (rig or "").strip()[:40]
    owner = (owner or "").strip()[:60]
    if not rig or not owner:
        raise ValueError("rig and owner required")
    conn = get_conn()
    try:
        _ensure(conn)
        now = int(time.time())
        conn.execute("INSERT INTO jelly_miners (name,owner,last_seen) VALUES (?,?,?) "
                     "ON CONFLICT(name) DO UPDATE SET owner=excluded.owner", (rig, owner, now))
        conn.commit()
    finally:
        conn.close()


# ── Company skilling hook (called from world_sim; NEVER mines by itself) ─────
def skill_pulse(conn, agent_key: str, agent_name: str, skill: str, units: int):
    """Record boost tickets for real skilling work. Cheap, same world-sim connection.

    Refuses once the cap is exhausted: issuing tickets that provably can never be
    minted would be accruing a debt the chain has already promised not to pay."""
    _ensure(conn)
    if remaining_headroom(conn) < BOOST_PER_TICKET:
        return
    now = int(time.time())
    pending = conn.execute("SELECT COUNT(*) c FROM jelly_boosts "
                           "WHERE height IS NULL AND expired IS NULL").fetchone()["c"]
    room = BOOST_MAX_PENDING - int(pending)
    n = min(int(units), room)
    for _ in range(max(0, n)):
        conn.execute("INSERT INTO jelly_boosts (agent_key,agent_name,skill,units,created) VALUES (?,?,?,1,?)",
                     (agent_key, agent_name, skill, now))


# ── NFTs + buddy-share compute economy (extracted to jellycoin_extra.py) ─────
# Re-export keeps this module's surface identical; each function lazy-imports
# jellycoin, so there is no import cycle.
from jellycoin_extra import (  # noqa: E402,F401
    mint_nft, transfer_nft,
    PEER_BILLING_KEY, PEER_PRICE_KEY, PEER_PRICE_DEFAULT,
    peer_billing_enabled, peer_job_price, peer_job_charge, peer_job_credit,
)


# ── supply audit ─────────────────────────────────────────────────────────────
def _avg_block_sec(conn, window: int = 200) -> float:
    """Observed seconds per block over the last `window` blocks. Falls back to the
    target when there is not enough chain to measure."""
    rows = conn.execute("SELECT time FROM jelly_blocks WHERE height>0 "
                        "ORDER BY height DESC LIMIT ?", (max(2, window),)).fetchall()
    if len(rows) < 2:
        return float(TARGET_BLOCK_SEC)
    span = int(rows[0]["time"]) - int(rows[-1]["time"])
    return (span / (len(rows) - 1)) if span > 0 else float(TARGET_BLOCK_SEC)


def _blocks_to_cap(height: int, headroom: int, boost_per_block: int = 0) -> int:
    """How many more blocks until the cap is exhausted, walking the halving epochs
    rather than assuming today's reward lasts forever. Returns -1 if the subsidy
    decays to nothing before the cap is reached (i.e. the cap is never hit)."""
    blocks, h = 0, height
    while headroom > 0:
        nxt = h + 1
        per = block_reward(nxt) + boost_per_block
        if per <= 0:
            return -1                                  # subsidy is dead; cap unreachable
        epoch_end = ((nxt // HALVING_INTERVAL) + 1) * HALVING_INTERVAL
        n = epoch_end - nxt                            # blocks left at this reward
        if per * n >= headroom:
            return blocks + -(-headroom // per)        # ceil-divide into this epoch
        headroom -= per * n
        blocks += n
        h = epoch_end - 1
    return blocks


def supply_report(conn=None) -> dict:
    """Authoritative emission audit, computed from the block table and reconciled
    against the wallet ledger. The two are derived independently on purpose: if
    `discrepancy` is ever non-zero, coins were credited or debited outside a
    block and that is a bug, so it is reported rather than hidden."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        _ensure(conn)
        tip = _tip(conn)
        if tip is None:                                # joined mode: no local chain
            return {"chain": False, "circulating": 0, "max_supply": MAX_SUPPLY / UNIT,
                    "remaining": MAX_SUPPLY / UNIT, "pct_mined": 0.0}
        height = int(tip["height"])
        mined_sub = int(conn.execute("SELECT COALESCE(SUM(reward),0) s FROM jelly_blocks "
                                     "WHERE height>0").fetchone()["s"])
        boosted = int(conn.execute("SELECT COALESCE(SUM(boost),0) s FROM jelly_blocks").fetchone()["s"])
        burned = burned_total(conn)
        circ = circulating(conn)
        headroom = remaining_headroom(conn)
        wallet_sum = int(conn.execute(
            "SELECT COALESCE(SUM(balance),0) s FROM jelly_wallets").fetchone()["s"])
        pend = conn.execute("SELECT COUNT(*) c FROM jelly_boosts "
                            "WHERE height IS NULL AND expired IS NULL").fetchone()["c"]
        expd = conn.execute("SELECT COUNT(*) c FROM jelly_boosts "
                            "WHERE expired IS NOT NULL").fetchone()["c"]
        avg_sec = _avg_block_sec(conn)
        # Boosts mint alongside the subsidy, so a projection that ignores them
        # would place the cap later than it will really arrive.
        boost_rate = (boosted // height) if height else 0
        n_blocks = _blocks_to_cap(height, headroom, boost_rate)
        eta = (int(time.time()) + int(n_blocks * avg_sec)) if n_blocks >= 0 else None
        nxt_halving = ((height // HALVING_INTERVAL) + 1) * HALVING_INTERVAL
        return {
            "chain": True, "unit": UNIT, "height": height,
            "circulating": circ / UNIT,
            "max_supply": MAX_SUPPLY / UNIT,
            "remaining": headroom / UNIT,
            "pct_mined": round(100.0 * circ / MAX_SUPPLY, 4),
            "premine": PREMINE / UNIT,
            "mined_subsidy": mined_sub / UNIT,
            "boost_minted": boosted / UNIT,
            "burned": burned / UNIT,
            "block_reward": effective_block_reward(conn, height + 1) / UNIT,
            "scheduled_reward": block_reward(height + 1) / UNIT,
            "next_halving_height": nxt_halving,
            "blocks_to_halving": nxt_halving - height,
            "blocks_to_cap": n_blocks,
            "avg_block_sec": round(avg_sec, 1),
            "cap_eta_epoch": eta,
            "boosts_pending": int(pend), "boosts_expired": int(expd),
            # reconciliation: block-derived supply vs the sum of every balance
            "wallet_sum": wallet_sum / UNIT,
            "discrepancy": (circ - wallet_sum) / UNIT,
            "reconciled": circ == wallet_sum,
        }
    finally:
        if own:
            conn.close()


# ── status ───────────────────────────────────────────────────────────────────
def status() -> dict:
    conn = get_conn()
    try:
        _ensure(conn)
        tip = _tip(conn)
        if tip is None:
            # Joined mode: we founded no chain, so there is nothing local to report.
            # The caller (UI) switches to the participant view and reads our balance
            # on the home node over the peer RPC instead.
            return {"symbol": SYMBOL, "name": "JellyCoin", "unit": UNIT,
                    "mode": jelly_mode(), "home_peer": jelly_home_peer(),
                    "chain": False, "height": 0, "supply": 0, "miners": [],
                    "miners_online": 0, "boosts_pending": 0, "boosts_paid_jly": 0,
                    "nft_count": 0}
        now = int(time.time())
        supply = conn.execute("SELECT COALESCE(SUM(reward+boost),0) s FROM jelly_blocks").fetchone()["s"]
        miners = [dict(r) for r in conn.execute(
            "SELECT name,gpu,last_seen,blocks,hashrate FROM jelly_miners ORDER BY last_seen DESC LIMIT 20")]
        for m in miners:
            m["online"] = (now - m["last_seen"]) < MINER_FRESH_SEC
        pending = conn.execute("SELECT COUNT(*) c FROM jelly_boosts "
                               "WHERE height IS NULL AND expired IS NULL").fetchone()["c"]
        paid = conn.execute("SELECT COALESCE(SUM(boost),0) s FROM jelly_blocks").fetchone()["s"]
        nfts = conn.execute("SELECT COUNT(*) c FROM jelly_nfts").fetchone()["c"]
        target = current_target(conn)
        return {
            "symbol": SYMBOL, "name": "JellyCoin", "unit": UNIT,
            "mode": jelly_mode(), "home_peer": jelly_home_peer(), "chain": True,
            "height": int(tip["height"]), "tip_hash": tip["hash"], "tip_time": int(tip["time"]),
            "difficulty": round(difficulty(target), 3), "target": f"{target:064x}",
            "supply": supply / UNIT,
            "block_reward": effective_block_reward(conn, int(tip["height"]) + 1) / UNIT,
            "max_supply": MAX_SUPPLY / UNIT,
            "remaining": remaining_headroom(conn) / UNIT,
            "pct_mined": round(100.0 * circulating(conn) / MAX_SUPPLY, 4),
            "miners": miners, "miners_online": sum(1 for m in miners if m["online"]),
            "boosts_pending": int(pending), "boosts_paid_jly": paid / UNIT, "nft_count": int(nfts),
        }
    finally:
        conn.close()
