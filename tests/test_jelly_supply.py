"""JellyCoin hard cap, boost-inside-the-cap accounting, and difficulty retargeting.

Every test here runs on a SCRATCH chain in its own sqlite file (get_conn is patched
for the duration), never the session DB and never the live store.db — the point is
to drive the chain right up to MAX_SUPPLY, which would be destructive anywhere real.
Nonces are ground in Python purely to satisfy the server's validator, exactly as
tests/test_jellycoin.py does; no GPU and no real block is ever mined.
"""
import hashlib
import sqlite3
import struct
import time

import pytest

import jellycoin


# ── scratch chain harness ────────────────────────────────────────────────────
@pytest.fixture
def chain(tmp_path, monkeypatch):
    """A private JellyCoin chain: fresh DB, genesis + premine written, nothing else."""
    path = tmp_path / "scratch.db"

    def _conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(jellycoin, "get_conn", _conn)
    monkeypatch.setattr(jellycoin, "_schema_done", False)
    monkeypatch.setattr(jellycoin, "_works", {})
    jellycoin.ensure_schema()
    yield _conn
    jellycoin._schema_done = False


def _mine(miner="rig1"):
    """Solve and submit one block on the scratch chain (genesis difficulty is trivial)."""
    w = jellycoin.get_work(miner, "TestGPU", 1000.0)
    header, target = bytes.fromhex(w["header76"]), int(w["target"], 16)
    for nonce in range(5_000_000):
        h = hashlib.sha256(hashlib.sha256(header + struct.pack(">I", nonce)).digest()).digest()
        if int.from_bytes(h, "big") < target:
            break
    else:
        pytest.fail("no nonce found at scratch difficulty")
    r = jellycoin.submit_work(w["work_id"], nonce, miner)
    assert r.get("ok"), r
    return r


def _ticket(conn, n=1, key="agent_x"):
    c = conn()
    try:
        jellycoin.skill_pulse(c, key, "Agent X", "mining", n)
        c.commit()
    finally:
        c.close()


def _sum(conn, sql):
    c = conn()
    try:
        return int(c.execute(sql).fetchone()[0] or 0)
    finally:
        c.close()


U = jellycoin.UNIT


# ── the cap itself ───────────────────────────────────────────────────────────
def test_cap_matches_the_schedule_it_ratifies():
    """6M is not an arbitrary number: it is the halving series + premine, rounded.
    If someone retunes BLOCK_REWARD or HALVING_INTERVAL, this catches the drift."""
    total, k = 0, 0
    while jellycoin.BLOCK_REWARD >> k:
        total += (jellycoin.BLOCK_REWARD >> k) * jellycoin.HALVING_INTERVAL
        k += 1
    assert total + jellycoin.PREMINE <= jellycoin.MAX_SUPPLY, "schedule can outrun the cap"
    # …and the rounding slack is small, i.e. the cap really is this curve's ceiling.
    assert jellycoin.MAX_SUPPLY - (total + jellycoin.PREMINE) < U


def test_genesis_supply_is_the_premine_and_reconciles(chain):
    rep = jellycoin.supply_report()
    assert rep["circulating"] == jellycoin.PREMINE / U
    assert rep["max_supply"] == jellycoin.MAX_SUPPLY / U
    assert rep["remaining"] == (jellycoin.MAX_SUPPLY - jellycoin.PREMINE) / U
    assert rep["reconciled"] and rep["discrepancy"] == 0


def test_reward_is_trimmed_to_headroom_never_overshot(chain, monkeypatch):
    """The block that reaches the cap pays exactly the remainder — the whole point."""
    monkeypatch.setattr(jellycoin, "MAX_SUPPLY", jellycoin.PREMINE + 30 * U)
    r = _mine()
    assert r["reward"] == 30.0, "scheduled 50 JLY must be trimmed to the 30 JLY headroom"
    assert _sum(chain, "SELECT SUM(reward)+SUM(boost) FROM jelly_blocks") == jellycoin.MAX_SUPPLY
    assert jellycoin.remaining_headroom(chain()) == 0


def test_mining_past_the_cap_pays_zero_but_still_accepts_blocks(chain, monkeypatch):
    monkeypatch.setattr(jellycoin, "MAX_SUPPLY", jellycoin.PREMINE + 30 * U)
    _mine()
    before = _sum(chain, "SELECT SUM(reward)+SUM(boost) FROM jelly_blocks")
    r = _mine()
    assert r["reward"] == 0.0
    # the block exists and extends the chain; it simply mints nothing
    assert _sum(chain, "SELECT MAX(height) FROM jelly_blocks") == 2
    assert _sum(chain, "SELECT SUM(reward)+SUM(boost) FROM jelly_blocks") == before
    assert _sum(chain, "SELECT COUNT(*) FROM jelly_txs WHERE kind='coinbase' AND height=2") == 0


def test_supply_never_exceeds_cap_across_many_blocks(chain, monkeypatch):
    monkeypatch.setattr(jellycoin, "MAX_SUPPLY", jellycoin.PREMINE + 120 * U)
    for _ in range(5):                                   # 5 × 50 JLY scheduled = 250
        _mine()
        assert _sum(chain, "SELECT SUM(reward)+SUM(boost) FROM jelly_blocks") <= jellycoin.MAX_SUPPLY
    assert _sum(chain, "SELECT SUM(reward)+SUM(boost) FROM jelly_blocks") == jellycoin.MAX_SUPPLY


# ── boosts inside the cap ────────────────────────────────────────────────────
def test_boosts_count_against_the_cap(chain):
    _ticket(chain, 4)
    _mine()
    boosted = _sum(chain, "SELECT SUM(boost) FROM jelly_blocks")
    assert boosted == 4 * jellycoin.BOOST_PER_TICKET
    rep = jellycoin.supply_report()
    assert rep["boost_minted"] == boosted / U
    # headroom shrank by reward AND boost, not by reward alone
    assert rep["remaining"] == (jellycoin.MAX_SUPPLY - jellycoin.PREMINE - 50 * U - boosted) / U


def test_boosts_trimmed_to_partial_headroom_remainder_stays_pending(chain, monkeypatch):
    """Half the tickets fit under the cap. The rest are NOT dropped — they wait."""
    monkeypatch.setattr(jellycoin, "MAX_SUPPLY",
                        jellycoin.PREMINE + 50 * U + 5 * jellycoin.BOOST_PER_TICKET)
    _ticket(chain, 10)
    _mine()
    assert _sum(chain, "SELECT SUM(boost) FROM jelly_blocks") == 5 * jellycoin.BOOST_PER_TICKET
    assert _sum(chain, "SELECT COUNT(*) FROM jelly_boosts WHERE height IS NOT NULL") == 5
    assert _sum(chain, "SELECT COUNT(*) FROM jelly_boosts "
                       "WHERE height IS NULL AND expired IS NULL") == 5
    assert _sum(chain, "SELECT COUNT(*) FROM jelly_boosts WHERE expired IS NOT NULL") == 0


def test_unpayable_tickets_expire_with_a_visible_reason(chain, monkeypatch):
    """With the cap exhausted, owed tickets are closed out explicitly — marked,
    with a reason, still queryable — rather than silently deleted."""
    monkeypatch.setattr(jellycoin, "MAX_SUPPLY", jellycoin.PREMINE + 50 * U)
    _ticket(chain, 6)
    _mine()                                              # reward eats all headroom
    _mine()                                              # next block closes the queue
    c = chain()
    try:
        rows = c.execute("SELECT expired, expired_reason FROM jelly_boosts").fetchall()
        assert len(rows) == 6
        assert all(r["expired"] and r["expired_reason"] == jellycoin.BOOST_EXPIRY_CAP
                   for r in rows), "tickets must carry the reason they were never paid"
    finally:
        c.close()
    assert jellycoin.supply_report()["boosts_expired"] == 6


def test_ttl_expiry_marks_rather_than_deletes(chain):
    """Pre-cap behaviour also stopped destroying evidence: a stale ticket is kept."""
    c = chain()
    try:
        old = int(time.time()) - jellycoin.BOOST_TTL_SEC - 10
        c.execute("INSERT INTO jelly_boosts (agent_key,agent_name,skill,units,created) "
                  "VALUES ('a','A','mining',1,?)", (old,))
        c.commit()
    finally:
        c.close()
    _mine()
    assert _sum(chain, "SELECT COUNT(*) FROM jelly_boosts") == 1, "row must survive"
    c = chain()
    try:
        r = c.execute("SELECT * FROM jelly_boosts").fetchone()
        assert r["height"] is None and r["expired_reason"] == jellycoin.BOOST_EXPIRY_TTL
    finally:
        c.close()


def test_skill_pulse_stops_issuing_tickets_once_the_cap_is_gone(chain, monkeypatch):
    monkeypatch.setattr(jellycoin, "MAX_SUPPLY", jellycoin.PREMINE + 50 * U)
    _mine()
    assert jellycoin.remaining_headroom(chain()) == 0
    _ticket(chain, 5)
    assert _sum(chain, "SELECT COUNT(*) FROM jelly_boosts") == 0, \
        "issuing tickets that can never be minted would accrue phantom debt"


# ── the audit ────────────────────────────────────────────────────────────────
def test_circulating_supply_matches_wallet_sum_after_activity(chain):
    _ticket(chain, 3)
    _mine()
    _ticket(chain, 2, key="agent_y")
    _mine("rig2")
    jellycoin.transfer(jellycoin.TREASURY, "someone", 1234 * U)   # moving ≠ minting
    rep = jellycoin.supply_report()
    assert rep["reconciled"], rep
    assert rep["discrepancy"] == 0
    assert rep["circulating"] == _sum(chain, "SELECT SUM(balance) FROM jelly_wallets") / U
    assert rep["circulating"] == (jellycoin.PREMINE + 100 * U
                                  + 5 * jellycoin.BOOST_PER_TICKET) / U


def test_supply_report_exposes_the_schedule(chain):
    rep = jellycoin.supply_report()
    assert rep["next_halving_height"] == jellycoin.HALVING_INTERVAL
    assert rep["blocks_to_halving"] == jellycoin.HALVING_INTERVAL
    assert rep["scheduled_reward"] == 50.0
    assert 0 < rep["pct_mined"] < 100


def test_subsidy_alone_never_quite_reaches_the_cap(chain):
    """Rounding 5,999,999.4 up to 6,000,000 leaves 0.6 JLY that the halving series
    can never pay out, so with zero boost emission the cap is genuinely unreachable
    and the projection says so (-1 / no ETA) instead of inventing a date."""
    rep = jellycoin.supply_report()
    assert rep["blocks_to_cap"] == -1
    assert rep["cap_eta_epoch"] is None


def test_boost_emission_makes_the_cap_reachable_and_dated(chain):
    """Boosts mint from the same pool, so once they are flowing the cap does arrive —
    and the projection accounts for them rather than only counting the subsidy."""
    _ticket(chain, 8)
    _mine()
    rep = jellycoin.supply_report()
    assert rep["blocks_to_cap"] > 0
    assert rep["cap_eta_epoch"] > time.time()


def test_supply_endpoint_is_served(client):
    r = client.get("/api/jelly/supply")
    assert r.status_code == 200
    d = r.json()
    assert d["max_supply"] == jellycoin.MAX_SUPPLY / U
    assert d["circulating"] + d["remaining"] == pytest.approx(d["max_supply"])


def test_migration_leaves_existing_blocks_and_balances_untouched(chain):
    """The additive columns must not disturb a chain that already has history —
    this is the property the live 2,400-block ledger depends on."""
    _ticket(chain, 3)
    _mine()
    _mine("rig2")
    before_blocks = [tuple(r) for r in chain().execute(
        "SELECT height,hash,reward,boost FROM jelly_blocks ORDER BY height")]
    before_wallets = [tuple(r) for r in chain().execute(
        "SELECT name,balance FROM jelly_wallets ORDER BY name")]
    jellycoin._schema_done = False
    jellycoin.ensure_schema()                            # re-run the migration
    assert [tuple(r) for r in chain().execute(
        "SELECT height,hash,reward,boost FROM jelly_blocks ORDER BY height")] == before_blocks
    assert [tuple(r) for r in chain().execute(
        "SELECT name,balance FROM jelly_wallets ORDER BY name")] == before_wallets


# ── difficulty ───────────────────────────────────────────────────────────────
def _seed(conn, n, gap, target=None):
    """Write n synthetic blocks `gap` seconds apart so retargeting has real timing."""
    tgt = f"{(target if target is not None else jellycoin.MAX_TARGET):064x}"
    c = conn()
    try:
        t0 = int(time.time()) - n * gap
        # genesis is written at ensure_schema() time; drag it onto the same cadence
        # or the first retarget window measures against a wall-clock artefact.
        c.execute("UPDATE jelly_blocks SET time=? WHERE height=0", (t0,))
        for h in range(1, n + 1):
            c.execute("INSERT INTO jelly_blocks (height,hash,prev,merkle,target,nonce,time,"
                      "miner,reward,boost) VALUES (?,?,?,?,?,0,?,'rig',0,0)",
                      (h, f"{h:064x}", f"{h - 1:064x}", f"{h:064x}", tgt, t0 + h * gap))
        c.commit()
    finally:
        c.close()


def test_retarget_hardens_when_blocks_come_too_fast(chain):
    _seed(chain, jellycoin.RETARGET_INTERVAL - 1, gap=6, target=jellycoin.MAX_TARGET // 1000)
    c = chain()
    try:
        assert jellycoin.current_target(c) < jellycoin.MAX_TARGET // 1000
    finally:
        c.close()


def test_retarget_eases_when_blocks_come_too_slow(chain):
    _seed(chain, jellycoin.RETARGET_INTERVAL - 1, gap=240, target=jellycoin.MAX_TARGET // 1000)
    c = chain()
    try:
        assert jellycoin.current_target(c) > jellycoin.MAX_TARGET // 1000
    finally:
        c.close()


def test_retarget_is_clamped_to_4x_per_adjustment(chain):
    base = jellycoin.MAX_TARGET // 10_000
    _seed(chain, jellycoin.RETARGET_INTERVAL - 1, gap=100_000, target=base)   # absurdly slow
    c = chain()
    try:
        assert jellycoin.current_target(c) <= base * 4
    finally:
        c.close()


def test_stalled_chain_eases_until_it_can_recover(chain):
    """All rigs vanish at a hard target. Without easing the chain is dead forever;
    with it, the target loosens the longer the silence lasts."""
    base = jellycoin.MAX_TARGET // 1_000_000
    _seed(chain, 3, gap=60, target=base)
    c = chain()
    try:
        tip_t = int(c.execute("SELECT MAX(time) t FROM jelly_blocks").fetchone()["t"])
        assert jellycoin.current_target(c, now=tip_t + 60) == base          # healthy: no easing
        hour = jellycoin.current_target(c, now=tip_t + 3600)
        day = jellycoin.current_target(c, now=tip_t + 86_400)
        assert base < hour < day, "easing must grow with the length of the stall"
        assert day <= jellycoin.MAX_TARGET
    finally:
        c.close()


def test_stall_easing_is_toggleable(chain, monkeypatch):
    base = jellycoin.MAX_TARGET // 1_000_000
    _seed(chain, 3, gap=60, target=base)
    monkeypatch.setattr(jellycoin, "eda_enabled", lambda: False)
    c = chain()
    try:
        tip_t = int(c.execute("SELECT MAX(time) t FROM jelly_blocks").fetchone()["t"])
        assert jellycoin.current_target(c, now=tip_t + 86_400) == base
    finally:
        c.close()


def test_easing_clears_the_moment_a_block_lands(chain):
    base = jellycoin.MAX_TARGET // 1_000_000
    _seed(chain, 3, gap=60, target=base)
    c = chain()
    try:
        tip_t = int(c.execute("SELECT MAX(time) t FROM jelly_blocks").fetchone()["t"])
        assert jellycoin.current_target(c, now=tip_t + 7200) > base
        # …and a block landing resets the clock, so the easing is gone immediately
        # rather than persisting as a permanently softened chain.
        assert jellycoin._eda_ease(tip_t, tip_t) == 1.0
        assert jellycoin.current_target(c, now=tip_t) == base
    finally:
        c.close()
