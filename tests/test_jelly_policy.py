"""Owner-controlled mining: live intensity, schedule windows, daily budget,
agent-decided mining inside the owner's envelope, and 51%-attack defence.

Nothing here touches a real GPU or real time: the AI queue's busy state is
mocked (routers.jellycoin._queue_busy) and every clock-dependent test passes an
explicit `now`, so the suite is deterministic on any box at any hour.

The load-bearing invariants, in priority order:
  1. AI work outranks routine mining — always, whatever the schedule says.
  2. …except while chain DEFENCE is engaged, which is the one documented
     inversion, and even then an in-flight AI job is allowed to finish.
  3. The owner's envelope is a hard boundary: agents may narrow it, never widen it.
  4. A schedule or intensity change must never cost a valid block.
"""
import hashlib
import json
import struct
import time

import pytest


@pytest.fixture
def pol(monkeypatch):
    """Fresh settings + module state around every test — the client fixture is
    session-scoped, so anything left behind would leak into the next test."""
    from routers import jellycoin as jr
    from deps import get_conn
    keys = (jr.YIELD_KEY, jr.SETTLE_KEY, jr.RETRY_KEY, jr.POLICY_KEY, jr.SCHED_ON_KEY,
            jr.SCHED_WIN_KEY, jr.SCHED_HOURS_KEY, jr.AGENT_ON_KEY, jr.AGENT_PLAN_KEY,
            jr.AGENT_MIN_THROTTLE_KEY, jr.AGENT_MAX_PAUSE_KEY, jr.AGENT_MAX_MINUTES_KEY,
            jr.DEF_ON_KEY, jr.DEF_PREEMPT_KEY, jr.DEF_WARN_KEY, jr.DEF_ACT_KEY,
            jr.DEF_CLEAR_KEY, jr.DEF_SETTLE_KEY, jr.DEF_WINDOW_KEY, jr.DEF_MY_RIGS_KEY,
            jr.DEF_MODE_KEY, jr.DEF_SAMPLE_MIN_KEY)

    def reset():
        conn = get_conn()
        conn.execute(f"DELETE FROM settings WHERE key IN ({','.join('?' * len(keys))})", keys)
        conn.execute("DELETE FROM jelly_rig_minutes") if _has(conn, "jelly_rig_minutes") else None
        conn.execute("DELETE FROM jelly_defense_log") if _has(conn, "jelly_defense_log") else None
        conn.commit()
        conn.close()
        jr._yield.update(held=False, idle_since=0.0, since=0.0)
        jr._def_cache.update(at=0.0, state=None)
        jr._def_gate.update(armed=False, engaged_at=0.0, ai_seconds=0.0, since=0.0)

    def _has(conn, t):
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (t,)).fetchone() is not None

    def snapshot():
        """The defence tests plant a synthetic block history. The DB is shared for
        the whole session, so that history MUST NOT outlive the test — a fake tip
        would break every real getwork/submit test that runs afterwards."""
        conn = get_conn()
        try:
            if not _has(conn, "jelly_blocks"):
                return None
            cur = conn.execute("SELECT * FROM jelly_blocks")
            cols = [d[0] for d in cur.description]
            return cols, [tuple(r[c] for c in cols) for r in cur.fetchall()]
        finally:
            conn.close()

    def restore(snap):
        if snap is None:
            return
        cols, rows = snap
        conn = get_conn()
        try:
            conn.execute("DELETE FROM jelly_blocks")
            conn.executemany(
                f"INSERT INTO jelly_blocks ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})", rows)
            conn.commit()
        finally:
            conn.close()

    snap = snapshot()
    reset()
    # defence off unless a test asks for it, so it can never silently override the
    # queue-yield or the schedule in the tests that are about those.
    jr._save(jr.DEF_ON_KEY, "0")
    yield jr
    reset()
    restore(snap)


def _busy(monkeypatch, value):
    monkeypatch.setattr("routers.jellycoin._queue_busy", lambda: value)


def _work(client, miner="polrig"):
    return client.get(f"/api/jelly/mining/work?miner={miner}&gpu=TestGPU&hashrate=1000000")


def _closed_window():
    """A window guaranteed NOT to contain the current local time — two hours from
    now, one hour wide. Lets the HTTP-level schedule tests use the real clock
    instead of monkeypatching time.time (which the chain's own timestamps use)."""
    h = time.localtime().tm_hour
    return f"{(h + 2) % 24:02d}:00-{(h + 3) % 24:02d}:00"


def _at(hhmm, day=15):
    """A real epoch for a given LOCAL wall-clock time — the schedule reads the
    box's local clock, so the test has to speak the same one."""
    return time.mktime((2026, 7, day, hhmm // 100, hhmm % 100, 0, 0, 0, -1))


# ══ live intensity policy ════════════════════════════════════════════════════
def test_getwork_carries_a_policy(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    w = _work(client, "introrig").json()
    assert w["work_id"] and w["header76"], "policy must not disturb the work itself"
    p = w["policy"]
    assert 0 <= p["throttle"] <= pol.THROTTLE_MAX
    assert pol.BATCH_MIN <= p["batch"] <= pol.BATCH_MAX
    assert p["source"] == "owner"


def test_per_rig_intensity_is_delivered_per_rig(client, pol, monkeypatch):
    """The 3060 and the 1060 must be able to run at different intensities."""
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy", json={"rigs": {
        "node3060": {"throttle": 50, "batch": 1 << 22, "cost": "ai"},
        "server1060": {"throttle": 90, "batch": 1 << 20, "cost": "free"}}})
    a = _work(client, "node3060").json()["policy"]
    b = _work(client, "server1060").json()["policy"]
    assert (a["throttle"], a["batch"], a["cost"]) == (50, 1 << 22, "ai")
    assert (b["throttle"], b["batch"], b["cost"]) == (90, 1 << 20, "free")


def test_intensity_change_needs_no_restart(client, pol, monkeypatch):
    """The whole point: retune a RUNNING rig. Same rig, two getworks, new value."""
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy", json={"rigs": {"livrig": {"throttle": 10}}})
    assert _work(client, "livrig").json()["policy"]["throttle"] == 10
    client.post("/api/jelly/miner-policy", json={"rigs": {"livrig": {"throttle": 85}}})
    assert _work(client, "livrig").json()["policy"]["throttle"] == 85


def test_policy_values_are_clamped(client, pol):
    r = client.post("/api/jelly/miner-policy", json={"rigs": {
        "wild": {"throttle": 999, "batch": 1}}}).json()
    got = [x for x in r["rigs"] if x["name"] == "wild"]
    stored = r["policy"]["wild"]
    assert stored["throttle"] == pol.THROTTLE_MAX and stored["batch"] == pol.BATCH_MIN
    assert not got or got[0]["throttle"] <= pol.THROTTLE_MAX


def test_old_miner_ignoring_the_policy_still_mines(client, pol, monkeypatch):
    """Backward compatibility is the contract: `policy` is additive. A miner built
    before it existed reads only the keys it knows and mines exactly as before —
    simulated here by consuming the response the way the old loop did."""
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy", json={"rigs": {"oldrig": {"throttle": 90}}})
    r = _work(client, "oldrig")
    assert r.status_code == 200
    w = r.json()
    header76, target = bytes.fromhex(w["header76"]), int(w["target"], 16)   # old fields only
    for nonce in range(5_000_000):
        h = hashlib.sha256(hashlib.sha256(header76 + struct.pack(">I", nonce)).digest()).digest()
        if int.from_bytes(h, "big") < target:
            break
    else:
        pytest.fail("no nonce at genesis difficulty")
    res = client.post("/api/jelly/mining/submit",
                      json={"work_id": w["work_id"], "nonce": nonce, "miner": "oldrig"}).json()
    assert res.get("ok"), f"an old miner must keep mining unchanged: {res}"


def _miner_bits():
    """Load apply_policy + its bounds STRAIGHT FROM the shipped miner, without
    importing it — jellyminer.py sys.exit()s when pyopencl is missing, and the
    store's venv has no OpenCL stack (nor should it: the server never mines)."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "miner" / "jellyminer.py").read_text()
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "apply_policy")
            or (isinstance(n, ast.Assign)
                and any(getattr(t, "id", "").startswith(("THROTTLE_", "BATCH_"))
                        for t in n.targets if isinstance(t, ast.Name))
                or (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Tuple)
                    and any(getattr(e, "id", "").startswith("BATCH_") for e in n.targets[0].elts)))]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "jellyminer.py", "exec"), ns)
    assert "apply_policy" in ns, "apply_policy vanished from the miner"
    return type("M", (), ns)


def test_miner_apply_policy_is_defensive():
    """The miner-side half. It parses network input, so junk must never change a
    running rig's settings, and a partial policy must only move what it names."""
    jm = _miner_bits()

    assert jm.apply_policy({"throttle": 90, "batch": 1 << 20}, 0, 1 << 22) == (90, 1 << 20, True)
    assert jm.apply_policy({"throttle": 90}, 0, 1 << 22)[1] == 1 << 22, "unnamed keys keep their value"
    assert jm.apply_policy(None, 50, 1 << 22) == (50, 1 << 22, False), "no policy ⇒ CLI values stand"
    assert jm.apply_policy({}, 50, 1 << 22)[2] is False
    assert jm.apply_policy({"throttle": "nonsense"}, 50, 1 << 22) == (50, 1 << 22, False)
    assert jm.apply_policy({"throttle": 999}, 0, 1 << 22)[0] == jm.THROTTLE_MAX
    assert jm.apply_policy({"batch": 1}, 0, 1 << 22)[1] == jm.BATCH_MIN
    assert jm.apply_policy({"throttle": 50}, 50, 1 << 22)[2] is False, "same value ⇒ not a change"


def test_miner_and_server_agree_on_bounds():
    """Two files clamp to the same range; a drift would silently truncate policy."""
    from routers import jellycoin as jr
    jm = _miner_bits()
    assert (jm.THROTTLE_MAX, jm.BATCH_MIN, jm.BATCH_MAX) == (jr.THROTTLE_MAX, jr.BATCH_MIN, jr.BATCH_MAX)


# ══ schedule windows ═════════════════════════════════════════════════════════
def test_window_parsing_handles_wrap_and_junk(pol):
    assert pol.parse_windows("22:00-06:00") == [(1320, 360)]
    assert pol.parse_windows("22:00-06:00, 12:00-13:30") == [(1320, 360), (720, 810)]
    assert pol.parse_windows("") == []
    with pytest.raises(ValueError):
        pol.parse_windows("25:00-26:00")
    with pytest.raises(ValueError):
        pol.parse_windows("nonsense")


def test_schedule_off_by_default_changes_nothing(client, pol, monkeypatch):
    """House rule: the gate ships with a toggle, and the toggle ships off."""
    _busy(monkeypatch, False)
    assert client.get("/api/jelly/miner-policy").json()["schedule"]["enabled"] is False
    assert _work(client).status_code == 200


def test_inside_the_window_mines_outside_holds(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy",
                json={"sched_enabled": True, "windows": "22:00-06:00"})
    assert pol.schedule_hold("r", _at(2300)) == {}, "23:00 is inside 22:00-06:00"
    assert pol.schedule_hold("r", _at(200)) == {}, "02:00 is inside the wrapped window"
    hold = pol.schedule_hold("r", _at(1200))
    assert hold and hold["pause"] is True and hold["sched"] is True
    assert "outside the mining hours" in hold["reason"]
    for k in ("work_id", "header76", "target"):
        assert k not in hold, "a hold must never look like a job"


def test_schedule_hold_reaches_getwork_as_a_503(client, pol, monkeypatch):
    """Enforcement is server-side precisely so an un-updated rig obeys: it sees
    the same 503 it already knows how to sleep on."""
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy",
                json={"sched_enabled": True, "windows": _closed_window()})
    r = _work(client, "schedrig")
    assert r.status_code == 503
    assert r.json()["pause"] is True
    assert r.headers.get("Retry-After") == str(r.json()["retry_after"])


def test_a_held_rig_still_shows_as_online(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy",
                json={"sched_enabled": True, "windows": _closed_window()})
    assert _work(client, "sleepyrig").status_code == 503
    st = client.get("/api/jelly/status").json()
    assert any(m["name"] == "sleepyrig" and m["online"] for m in st["miners"])


def test_malformed_windows_never_wedge_mining(client, pol, monkeypatch):
    """A bad setting must fail open, not brick the rigs."""
    _busy(monkeypatch, False)
    assert client.post("/api/jelly/miner-policy", json={"windows": "garbage"}).status_code == 400
    pol._save(pol.SCHED_WIN_KEY, "garbage")          # or arrive some other way
    pol._save(pol.SCHED_ON_KEY, "1")
    assert pol.schedule_hold("r", _at(1200)) == {}


def test_timezone_is_reported(client, pol):
    s = client.get("/api/jelly/miner-policy").json()["schedule"]
    assert s["tz"], "the UI must be able to say WHICH 22:00 this is"


# ══ daily hour budget ════════════════════════════════════════════════════════
def test_budget_counts_only_issued_work(client, pol, monkeypatch):
    """Real accounting: a rig that is held keeps polling, and those polls must not
    burn the allowance while the card sits idle."""
    _busy(monkeypatch, False)
    now = _at(1000)
    pol.credit_mining("budgetrig", now)              # first poll seeds the clock, credits 0
    assert pol.hours_today("budgetrig", now) == 0.0
    pol.credit_mining("budgetrig", now + 60)
    assert pol.hours_today("budgetrig", now + 60) == pytest.approx(60 / 3600, abs=1e-3)


def test_budget_gap_is_capped(pol):
    """A rig off for six hours must credit one poll interval on return, not six
    hours — otherwise a reboot would eat the whole day's budget."""
    now = _at(900)
    pol.credit_mining("gaprig", now)
    pol.credit_mining("gaprig", now + 6 * 3600)
    assert pol.hours_today("gaprig", now) <= pol.CREDIT_CAP_SEC / 3600 + 1e-6


def test_daily_budget_stops_the_rig_and_is_per_rig(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy", json={"sched_enabled": True, "daily_hours": 1})
    now = _at(1000)
    pol.credit_mining("hungry", now)
    for i in range(1, 80):                           # 79 × 60s capped credits ⇒ >1h
        pol.credit_mining("hungry", now + i * 60)
    assert pol.hours_today("hungry", now) > 1
    hold = pol.schedule_hold("hungry", now)
    assert hold and "used its 1h" in hold["reason"]
    assert pol.schedule_hold("wellrested", now) == {}, "the budget is per rig"


def test_budget_of_zero_is_unlimited(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy", json={"sched_enabled": True, "daily_hours": 0})
    now = _at(1000)
    pol.credit_mining("marathon", now)
    for i in range(1, 200):
        pol.credit_mining("marathon", now + i * 60)
    assert pol.schedule_hold("marathon", now) == {}


def test_hours_today_appears_in_the_ui_payload(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    _work(client, "shownrig")
    rigs = client.get("/api/jelly/miner-policy").json()["rigs"]
    assert any(r["name"] == "shownrig" and "hours_today" in r for r in rigs)


# ══ priority: AI work always outranks routine mining ═════════════════════════
def test_queue_yield_beats_the_schedule(client, pol, monkeypatch):
    """Even in the middle of the owner's mining window, a busy AI queue wins."""
    _busy(monkeypatch, True)
    client.post("/api/jelly/miner-policy", json={"sched_enabled": True, "windows": "00:00-23:59"})
    hold = pol.mining_hold(_at(1200), "anyrig")
    assert hold["busy"] is True, "the AI queue must be the reason, not the schedule"
    assert not hold.get("sched")


def test_queue_yield_beats_an_agent_plan(client, pol, monkeypatch):
    client.post("/api/jelly/miner-policy", json={"agent_enabled": True})
    client.post("/api/jelly/agent-plan", json={"rig": "*", "throttle": 25, "minutes": 60})
    _busy(monkeypatch, True)
    assert pol.mining_hold(time.time(), "anyrig")["busy"] is True


def test_in_flight_submit_survives_a_schedule_stop(client, pol, monkeypatch):
    """A nonce found just before the window closed must still bank. Submits are
    never gated, and a hold returns BEFORE jellycoin.get_work(), so the WORK_TTL
    sweep cannot expire the work out from under a valid submit either."""
    _busy(monkeypatch, False)
    w = _work(client, "lastminute").json()
    header, target = bytes.fromhex(w["header76"]), int(w["target"], 16)
    for nonce in range(5_000_000):
        h = hashlib.sha256(hashlib.sha256(header + struct.pack(">I", nonce)).digest()).digest()
        if int.from_bytes(h, "big") < target:
            break
    else:
        pytest.fail("no nonce at genesis difficulty")

    client.post("/api/jelly/miner-policy",              # window slams shut mid-grind
                json={"sched_enabled": True, "windows": _closed_window()})
    assert _work(client, "lastminute").status_code == 503
    res = client.post("/api/jelly/mining/submit",
                      json={"work_id": w["work_id"], "nonce": nonce, "miner": "lastminute"}).json()
    assert res.get("ok"), f"a schedule change must never cost a block: {res}"
    assert res["height"] == w["height"]


# ══ agent-decided mining, bounded by the owner ═══════════════════════════════
def test_agent_control_is_off_by_default_and_refuses(client, pol):
    assert client.get("/api/jelly/miner-policy").json()["agent"]["enabled"] is False
    r = client.post("/api/jelly/agent-plan", json={"rig": "*", "throttle": 0})
    assert r.status_code == 403, "agents may not touch mining while the toggle is off"


def test_agent_plan_applies_within_the_envelope(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy",
                json={"agent_enabled": True, "agent_min_throttle": 25,
                      "rigs": {"agentrig": {"throttle": 80}}})
    r = client.post("/api/jelly/agent-plan", json={
        "agent": "Mayor Vex", "rig": "agentrig", "throttle": 40,
        "minutes": 30, "reason": "quiet night, cheap power"}).json()
    assert r["ok"] and r["clamped"] == {}
    p = _work(client, "agentrig").json()["policy"]
    assert p["throttle"] == 40 and p["source"] == "agent"


def test_agent_cannot_out_run_the_owners_floor(client, pol, monkeypatch):
    """The clamp is the whole safety story: an agent asking for full blast gets
    the owner's floor instead, and is TOLD it was clamped."""
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy",
                json={"agent_enabled": True, "agent_min_throttle": 60})
    r = client.post("/api/jelly/agent-plan",
                    json={"rig": "greedy", "throttle": 0, "minutes": 30}).json()
    assert r["clamped"]["throttle"] == 0
    assert r["plan"]["throttle"] == 60
    assert _work(client, "greedy").json()["policy"]["throttle"] == 60


def test_agent_plan_lengths_are_clamped(client, pol):
    client.post("/api/jelly/miner-policy", json={
        "agent_enabled": True, "agent_max_minutes": 60, "agent_max_pause_min": 30})
    r = client.post("/api/jelly/agent-plan",
                    json={"rig": "*", "minutes": 99999, "pause_min": 9999}).json()
    assert r["minutes"] == 60 and r["pause_min"] == 30
    assert r["clamped"]["minutes"] == 99999 and r["clamped"]["pause_min"] == 9999


def test_agent_cannot_mine_outside_the_owners_hours(client, pol, monkeypatch):
    """The envelope is not advice. An agent plan asking to mine hard is powerless
    outside the window, because the window is enforced in a different layer."""
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy", json={
        "agent_enabled": True, "sched_enabled": True, "windows": "22:00-06:00"})
    client.post("/api/jelly/agent-plan",
                json={"rig": "eager", "throttle": 25, "minutes": 240,
                      "reason": "let me mine all day"})
    assert pol.mining_hold(_at(1200), "eager")["sched"] is True
    assert pol.mining_hold(_at(2300), "eager") == {}, "inside the owner's hours it may run"


def test_agent_stand_down_is_narrowing_only(client, pol, monkeypatch):
    """An agent may PAUSE a rig — that only ever reduces mining, so it needs no
    further guard."""
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy", json={"agent_enabled": True})
    now = time.time()
    client.post("/api/jelly/agent-plan",
                json={"rig": "napper", "pause_min": 10, "minutes": 60, "reason": "peak power price"})
    hold = pol.mining_hold(now + 1, "napper")
    assert hold and hold.get("agent") is True and "peak power price" in hold["reason"]
    assert pol.mining_hold(now + 1, "otherrig") == {}, "a plan binds only its own rig"
    assert pol.mining_hold(now + 700, "napper") == {}, "and it expires"


def test_turning_the_toggle_off_defangs_a_live_plan(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    client.post("/api/jelly/miner-policy", json={"agent_enabled": True})
    client.post("/api/jelly/agent-plan", json={"rig": "bound", "throttle": 30, "minutes": 240})
    assert _work(client, "bound").json()["policy"]["source"] == "agent"
    client.post("/api/jelly/miner-policy", json={"agent_enabled": False})
    assert _work(client, "bound").json()["policy"]["source"] == "owner", \
        "flipping the switch must instantly return control, not wait for expiry"


def test_agent_plans_are_recorded(client, pol):
    client.post("/api/jelly/miner-policy", json={"agent_enabled": True})
    client.post("/api/jelly/agent-plan",
                json={"agent": "Boss Kane", "rig": "logged", "throttle": 45, "reason": "why not"})
    plans = client.get("/api/jelly/agent-plans").json()["plans"]
    assert any(p["agent"] == "Boss Kane" and p["rig"] == "logged" for p in plans), \
        "every agent decision must be visible after the fact"


# ══ 51%-attack defence ═══════════════════════════════════════════════════════
def _blocks(conn, spec, t0=1_760_000_000, target="0" * 8 + "f" * 56):
    """Plant a block history: `spec` is a list of miner names, oldest first."""
    import jellycoin as jc
    jc.ensure_schema(conn)
    conn.execute("DELETE FROM jelly_blocks WHERE height>0")
    for i, m in enumerate(spec, start=1):
        conn.execute("INSERT OR REPLACE INTO jelly_blocks "
                     "(height,hash,prev,merkle,target,nonce,time,miner,reward) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (i, f"h{i:064x}", f"h{i-1:064x}", f"m{i:064x}", target, i, t0 + i * 60, m, 0))
    conn.commit()


def _plant(pol, mine_n, theirs_n, my_rigs="myrig"):
    """Give the chain a block history with a known ownership ratio.

    The blocks are INTERLEAVED rather than stacked, because the measurement only
    looks at the last `window_blocks` — a run of ours followed by a run of theirs
    would make the answer depend on where the window happens to cut. The window
    is pinned to the planted total so the share the test asks for is the share the
    measurement sees."""
    from deps import get_conn
    total = mine_n + theirs_n
    spec = ["myrig" if ((i + 1) * mine_n // total) > (i * mine_n // total) else "attacker"
            for i in range(total)]              # exact integer spread — no float drift
    assert spec.count("myrig") == mine_n
    conn = get_conn()
    try:
        _blocks(conn, spec)
    finally:
        conn.close()
    pol._save(pol.DEF_MY_RIGS_KEY, my_rigs)
    pol._save(pol.DEF_WINDOW_KEY, total)
    pol._def_cache.update(at=0.0, state=None)


def test_defence_ships_on(client, pol):
    """The chain protects itself by default — but the house rule still holds, so
    it has a toggle."""
    pol._save(pol.DEF_ON_KEY, "")                    # unset ⇒ shipped default
    from deps import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE key=?", (pol.DEF_ON_KEY,))
    conn.commit()
    conn.close()
    assert pol.defense_enabled() is True
    assert pol._sflag(pol.DEF_PREEMPT_KEY, "1") is True
    client.post("/api/jelly/miner-defense", json={"enabled": False})
    assert pol.defense_enabled() is False


def test_share_is_measured_from_solved_blocks(client, pol):
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 30, 30)
    st = pol.defense_state(fresh=True)
    assert st["share_pct"] == 50.0
    assert st["blocks"] == 60 and st["confident"] is True
    assert st["net_hashrate"] > 0 and st["my_hashrate"] == pytest.approx(st["net_hashrate"] / 2)
    assert {r["rig"] for r in st["per_rig"]} == {"myrig", "attacker"}


def test_self_reported_hashrate_is_never_trusted(client, pol, monkeypatch):
    """A hostile rig can put any number in its getwork hashrate. It must not move
    the share measurement one bit."""
    _busy(monkeypatch, False)
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 30, 30)
    before = pol.defense_state(fresh=True)["share_pct"]
    client.get("/api/jelly/mining/work?miner=attacker&gpu=Liar&hashrate=999999999999")
    pol._def_cache.update(at=0.0, state=None)
    assert pol.defense_state(fresh=True)["share_pct"] == before


def test_small_samples_are_not_acted_on(client, pol):
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 1, 4)
    st = pol.defense_state(fresh=True)
    assert st["confident"] is False and st["level"] == "unknown"
    assert st["engaged"] is False, "a 5-block sample must never trigger the whole box"


def test_warn_ramps_only_spare_capacity(client, pol):
    """Cheapest first: at the warning line the idle card answers and the AI box is
    left alone."""
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 65, 35)                              # 65% — under warn 70, over act 60
    st = pol.defense_state(fresh=True)
    assert st["level"] == "warn" and st["engaged"] is False
    assert pol.defense_ramp("server1060", "free") == 0
    assert pol.defense_ramp("node3060", "ai") is None


def test_attack_engages_automatically_with_no_approval(client, pol):
    """The correction that matters: an attack will not wait for anyone to wake up
    and click a button."""
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 40, 60)                              # 40% — below the 60% action line
    st = pol.defense_state(fresh=True)
    assert st["level"] == "act"
    assert st["engaged"] is True, "engagement must be automatic"
    assert st["engaged_since"] > 0
    assert "myrig" in st["ramped"]


def test_engagement_ramps_every_rig_including_the_ai_box(client, pol, monkeypatch):
    """Multi-rig, and no special-casing: whatever rigs exist all go to full."""
    _busy(monkeypatch, False)
    pol._save(pol.DEF_ON_KEY, "1")
    client.post("/api/jelly/miner-policy", json={"rigs": {
        "node3060": {"throttle": 50, "cost": "ai"},
        "server1060": {"throttle": 90, "cost": "free"},
        "thirdcard": {"throttle": 80, "cost": "ai"}}})
    _plant(pol, 40, 60)
    pol.defense_state(fresh=True)
    for rig in ("node3060", "server1060", "thirdcard"):
        p = pol.rig_policy(rig)
        assert p["throttle"] == 0, f"{rig} must go to full power"
        assert p["source"] == "defense"


def test_a_new_rig_needs_no_code_change(client, pol):
    """Rigs are an arbitrary set — a fourth card is an install, not a patch."""
    pol._save(pol.DEF_ON_KEY, "1")
    client.post("/api/jelly/miner-policy",
                json={"rigs": {"buddys-card": {"throttle": 70, "cost": "free"}}})
    _plant(pol, 40, 60)
    pol.defense_state(fresh=True)
    assert pol.rig_policy("buddys-card")["throttle"] == 0


def test_defence_preempts_ai_but_lets_in_flight_work_finish(client, pol, monkeypatch):
    """Graceful, not brutal. While a generation is on the GPU we keep yielding;
    only once the queue reports idle does mining take the card. Nothing is ever
    cancelled — the worst an in-flight job sees is a busier GPU after it is done."""
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 40, 60)
    pol.defense_state(fresh=True)
    assert pol.defense_preempting() is True

    _busy(monkeypatch, True)                         # a render is mid-flight
    hold = pol.mining_hold(time.time(), "myrig")
    assert hold and hold["busy"] is True, "must not seize the GPU from a running job"
    assert pol._def_gate["armed"] is False

    _busy(monkeypatch, False)                        # it finished cleanly
    assert pol.mining_hold(time.time(), "myrig") == {}
    assert pol._def_gate["armed"] is True

    _busy(monkeypatch, True)                         # now the queue wants it again
    assert pol.mining_hold(time.time(), "myrig") == {}, \
        "once armed, defence outranks new AI work"


def test_defence_ignores_the_schedule_while_engaged(client, pol, monkeypatch):
    _busy(monkeypatch, False)
    pol._save(pol.DEF_ON_KEY, "1")
    client.post("/api/jelly/miner-policy",
                json={"sched_enabled": True, "windows": "22:00-06:00"})
    _plant(pol, 40, 60)
    pol.defense_state(fresh=True)
    pol.mining_hold(_at(1200), "myrig")               # arm the gate (queue idle)
    assert pol.mining_hold(_at(1200), "myrig") == {}, \
        "a chain under attack outranks the owner's quiet hours too"


def test_preempt_toggle_keeps_ai_first(client, pol, monkeypatch):
    """House rule: even this ships with an off switch. With it off, defence still
    ramps intensity but never takes the GPU from AI work."""
    pol._save(pol.DEF_ON_KEY, "1")
    client.post("/api/jelly/miner-defense", json={"preempt_ai": False})
    _plant(pol, 40, 60)
    pol.defense_state(fresh=True)
    _busy(monkeypatch, True)
    assert pol.defense_preempting() is False
    assert pol.mining_hold(time.time(), "myrig")["busy"] is True
    assert pol.rig_policy("myrig")["throttle"] == 0, "…but the ramp still happens"


def test_disengage_needs_sustained_recovery(client, pol):
    """Hysteresis: block attribution is a noisy binomial sample, so one good round
    must not flap every rig on the box out of defence."""
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 40, 60)
    t0 = time.time()
    assert pol.defense_state(now=t0, fresh=True)["engaged"] is True

    _plant(pol, 90, 10)                              # share recovers to 90%
    st = pol.defense_state(now=t0 + 10, fresh=True)
    assert st["engaged"] is True, "recovery must not disengage instantly"
    assert st["recovering_since"] > 0

    st = pol.defense_state(now=t0 + 10 * 60, fresh=True)
    assert st["engaged"] is True, "still inside the settle window"

    st = pol.defense_state(now=t0 + 31 * 60, fresh=True)   # settle_min default 30
    assert st["engaged"] is False, "sustained recovery stands defence down"


def test_a_dip_during_recovery_restarts_the_clock(client, pol):
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 40, 60)
    t0 = time.time()
    pol.defense_state(now=t0, fresh=True)
    _plant(pol, 90, 10)
    assert pol.defense_state(now=t0 + 60, fresh=True)["recovering_since"] > 0
    _plant(pol, 40, 60)                              # attacker comes back
    assert pol.defense_state(now=t0 + 120, fresh=True)["recovering_since"] == 0
    _plant(pol, 90, 10)
    assert pol.defense_state(now=t0 + 180, fresh=True)["engaged"] is True, \
        "the settle clock restarts — no early stand-down"


def test_engagement_is_logged_loudly(client, pol):
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 40, 60)
    pol.defense_state(fresh=True)
    d = client.get("/api/jelly/miner-defense").json()
    eng = [h for h in d["history"] if h["level"] == "engage"]
    assert eng, "engaging must leave a persisted, timestamped record"
    assert eng[0]["share_pct"] == 40.0
    log = [h for h in d["history"] if h["level"] == "engage"][0]
    assert log["at"] > 0 and log["blocks"] == 100


def test_manual_stand_down(client, pol):
    pol._save(pol.DEF_ON_KEY, "1")
    _plant(pol, 40, 60)
    assert pol.defense_state(fresh=True)["engaged"] is True
    r = client.post("/api/jelly/miner-defense", json={"stand_down": True}).json()
    assert r["engaged"] is False


def test_defence_off_does_nothing_at_all(client, pol, monkeypatch):
    pol._save(pol.DEF_ON_KEY, "0")
    _plant(pol, 10, 90)
    st = pol.defense_state(fresh=True)
    assert st["engaged"] is False
    assert pol.defense_ramp("myrig", "free") is None
    assert pol.defense_preempting() is False
    _busy(monkeypatch, True)
    assert pol.mining_hold(time.time(), "myrig")["busy"] is True


def test_auto_rig_detection_is_flagged_as_a_guess(client, pol):
    """The fallback would count a stranger's rig as ours — so it must announce
    itself rather than look authoritative."""
    pol._save(pol.DEF_MY_RIGS_KEY, "")
    pol._def_cache.update(at=0.0, state=None)
    assert pol.defense_state(fresh=True)["auto_rigs"] is True
    pol._save(pol.DEF_MY_RIGS_KEY, "myrig")
    pol._def_cache.update(at=0.0, state=None)
    assert pol.defense_state(fresh=True)["auto_rigs"] is False


def test_thresholds_round_trip_and_clamp(client, pol):
    r = client.post("/api/jelly/miner-defense", json={
        "warn_pct": 80, "act_pct": 55, "clear_pct": 85, "settle_min": 45,
        "window_blocks": 120}).json()
    assert (r["warn_pct"], r["act_pct"], r["clear_pct"]) == (80, 55, 85)
    assert r["settle_min"] == 45 and r["window_blocks"] == 120
    r = client.post("/api/jelly/miner-defense", json={"window_blocks": 99999}).json()
    assert r["window_blocks"] == 500


def test_clear_never_sits_below_act(client, pol):
    """A clear line under the action line would oscillate forever."""
    client.post("/api/jelly/miner-defense", json={"act_pct": 60, "clear_pct": 10})
    assert pol.defense_state(fresh=True)["clear_pct"] >= 60


# ══ nothing above broke the protocol ═════════════════════════════════════════
def test_token_guard_still_holds(client, pol):
    from types import SimpleNamespace
    from fastapi import HTTPException
    for headers in ({}, {"X-Jelly-Token": "nope"}):
        req = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"), headers=headers)
        with pytest.raises(HTTPException) as ex:
            pol._check_miner(req)
        assert ex.value.status_code == 403


def test_control_endpoints_are_not_in_the_lan_exemption(pol):
    """Rigs may fetch work and submit nonces. They may never read or rewrite the
    owner's schedule — so none of these may live under /api/jelly/mining/."""
    from routers import jellycoin as jr
    controls = [r.path for r in jr.router.routes
                if any(k in getattr(r, "path", "") for k in ("policy", "defense", "agent-plan"))]
    assert controls, "the control endpoints should exist"
    for path in controls:
        assert not path.startswith("/api/jelly/mining/"), \
            f"{path} would be reachable by any LAN rig without a session"
