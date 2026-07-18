"""The RimWorld-style Work-Priority scheduler — app/world_work.py.

Covers the policy surface the Work tab drives: default priorities, set/get
round-trip + clamping, priority-0 disable, and the Colony-Manager stock
gating (below floor → urgent, at ceiling → skip)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def _conn():
    from deps import get_conn
    return get_conn()


def _agent(key="test_scheduler"):
    return {"id": 7, "key": key, "name": "Sched Tester", "dept": "image"}


def test_default_priorities_cover_every_work_type(client):
    import world_work as ww
    import world_skills as ws
    conn = _conn(); c = conn.cursor()
    a = _agent()
    prio = ww.get_priorities(c, a)
    assert set(prio) == set(ww.WORK_TYPES)
    assert prio["operate"] == 1 and prio["relax"] == 4
    primary = ws.primary_skill(a)
    for wt, meta in ww.WT_META.items():
        if wt in ww.GATHER_WT:
            assert prio[wt] == (2 if meta["skill"] == primary else 3)
    conn.close()


def test_set_priority_roundtrip_clamps_and_ignores_unknown(client):
    import world_work as ww
    conn = _conn(); c = conn.cursor()
    a = _agent("test_setprio")
    ww.set_priority(c, a["key"], "mine", 9)      # clamps to 4
    ww.set_priority(c, a["key"], "fish", -3)     # clamps to 0
    ww.set_priority(c, a["key"], "not_a_type", 1)  # silently ignored
    conn.commit()
    prio = ww.get_priorities(c, a)
    assert prio["mine"] == 4 and prio["fish"] == 0
    assert "not_a_type" not in prio
    conn.close()


def test_operate_wins_when_real_work_exists(client):
    import world_work as ww
    conn = _conn(); c = conn.cursor()
    job = ww.choose_work(c, _agent("test_operate"), {"has_work": True, "t": 0})
    assert job["work_type"] == "operate" and job["state"] == "working"
    conn.close()


def test_stock_below_floor_makes_gather_urgent(client):
    import world_work as ww
    import world_skills as ws
    from world_defs import mset
    conn = _conn(); c = conn.cursor()
    a = _agent("test_stock_low")
    ww.set_priority(c, a["key"], "mine", 3)          # not naturally first
    ws.set_stock_target(c, "ore", 5, 10)
    mset(c, "stockpile", json.dumps({"ore": 0}))     # empty → below floor
    conn.commit()
    job = ww.choose_work(c, a, {"has_work": False, "t": 0})
    assert job["work_type"] == "mine", f"expected urgent mine, got {job['work_type']}"
    # cleanup so other tests see no ore target
    c.execute("DELETE FROM world_stock_targets WHERE resource='ore'")
    conn.commit(); conn.close()


def test_stock_at_ceiling_skips_that_gather(client):
    import world_work as ww
    import world_skills as ws
    from world_defs import mset
    conn = _conn(); c = conn.cursor()
    a = _agent("test_stock_full")
    ws.set_stock_target(c, "ore", 5, 10)
    mset(c, "stockpile", json.dumps({"ore": 10}))    # at ceiling → stop hoarding
    conn.commit()
    job = ww.choose_work(c, a, {"has_work": False, "t": 0})
    assert job["work_type"] != "mine"
    c.execute("DELETE FROM world_stock_targets WHERE resource='ore'")
    conn.commit(); conn.close()


def test_priority_zero_disables_even_when_stock_is_low(client):
    import world_work as ww
    import world_skills as ws
    from world_defs import mset
    conn = _conn(); c = conn.cursor()
    a = _agent("test_disabled")
    ww.set_priority(c, a["key"], "mine", 0)          # user said NEVER mine
    ws.set_stock_target(c, "ore", 5, 10)
    mset(c, "stockpile", json.dumps({"ore": 0}))
    conn.commit()
    job = ww.choose_work(c, a, {"has_work": False, "t": 0})
    assert job["work_type"] != "mine", "priority 0 must not be resurrected by stock urgency"
    c.execute("DELETE FROM world_stock_targets WHERE resource='ore'")
    conn.commit(); conn.close()


def test_everything_disabled_falls_back_to_relax(client):
    import world_work as ww
    conn = _conn(); c = conn.cursor()
    a = _agent("test_all_off")
    for wt in ww.WORK_TYPES:
        ww.set_priority(c, a["key"], wt, 0)
    conn.commit()
    job = ww.choose_work(c, a, {"has_work": True, "t": 0})
    assert job["state"] == "leisure"                 # never returns None/no-job
    conn.close()
