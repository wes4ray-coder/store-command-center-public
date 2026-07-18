"""Mayor/Boss company-fund upgrades via the dev swarm — app/world_leader.py."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def _conn():
    from deps import get_conn
    return get_conn()


def _reset(c):
    from world_defs import mset
    c.execute("DELETE FROM swarm_jobs WHERE title LIKE 'Town upgrade:%' OR title LIKE 'Store upgrade:%'")
    mset(c, "leader_upgrade_t", 0)
    mset(c, "leader_upgrade_n", 0)


def test_leader_files_a_gated_swarm_job_and_charges_on_approval(client):
    import world_leader
    from world_defs import mget, mset
    conn = _conn(); c = conn.cursor()
    _reset(c)
    mset(c, "company_fund", 1000)
    conn.commit()
    assert world_leader.maybe_upgrade(conn) is True
    job = c.execute("SELECT * FROM swarm_jobs ORDER BY id DESC LIMIT 1").fetchone()
    assert job["status"] == "proposed"           # user-gated: swarm does nothing until approved
    assert "company fund" in job["spec"]
    cost = int(float(mget(c, f"leader_cost_{job['id']}")))
    assert cost > 0
    assert int(float(mget(c, "company_fund"))) == 1000   # NOT charged at proposal time
    # approving via the real endpoint charges the fund exactly once
    r = client.post(f"/api/github/jobs/{job['id']}/approve")
    assert r.status_code == 200
    assert int(float(mget(c, "company_fund"))) == 1000 - cost
    import world_leader as wl
    assert wl.charge_on_approval(conn, job["id"]) is False   # second charge is a no-op
    assert int(float(mget(c, "company_fund"))) == 1000 - cost
    _reset(c); conn.commit(); conn.close()


def test_leader_respects_toggle_cooldown_and_cushion(client):
    import world_leader
    import world_settings
    from world_defs import mset
    conn = _conn(); c = conn.cursor()
    _reset(c)
    mset(c, "company_fund", 1000)
    # toggle off → nothing
    world_settings.save({"world_leader_upgrades": "0"}, conn)
    assert world_leader.maybe_upgrade(conn) is False
    world_settings.save({"world_leader_upgrades": "1"}, conn)
    # broke fund → nothing (cushion protected), but the cadence stamp advances
    mset(c, "company_fund", 50)
    conn.commit()
    assert world_leader.maybe_upgrade(conn) is False
    # rich again but inside the cadence window → still nothing
    mset(c, "company_fund", 1000)
    conn.commit()
    assert world_leader.maybe_upgrade(conn) is False
    _reset(c); conn.commit(); conn.close()
