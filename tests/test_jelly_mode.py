"""host vs joined — found your own chain, or join a buddy's network.

The island problem: every store used to write its own genesis on first touch, so
N friends installing the store made N unrelated coins. "joined" mode founds NO
chain — no genesis, no premine, and mining is refused so a rig can't quietly
start an island under a user who thinks they joined the network.

Default is "host", so every existing install is untouched (asserted here and by
the rest of the jellycoin suite, which never sets a mode).
"""
import pytest

import jellycoin


@pytest.fixture
def hosting(client):
    """Leave the shared session DB hosting its own chain, whatever a test did."""
    yield
    jellycoin.set_jelly_mode("host")
    assert jellycoin.jelly_mode() == "host"


def test_default_is_host_with_a_real_chain(client):
    assert jellycoin.jelly_mode() == "host"
    st = client.get("/api/jelly/status").json()
    assert st["mode"] == "host" and st["chain"] is True
    assert st["height"] >= 0 and st["supply"] >= 1_000_000     # genesis premine


def test_joining_founds_no_chain(client, hosting):
    r = client.post("/api/jelly/mode", json={"mode": "joined", "home_peer": "wes"})
    assert r.status_code == 200, r.text
    assert r.json() == {"mode": "joined", "home_peer": "wes"}

    st = client.get("/api/jelly/status").json()
    assert st["mode"] == "joined"
    assert st["chain"] is False, "a joined node must not have a chain of its own"
    assert st["height"] == 0 and st["supply"] == 0, "no genesis, no premine"

    # and the ledger really is empty — not just hidden by the status payload
    from deps import get_conn
    conn = get_conn()
    assert conn.execute("SELECT COUNT(*) FROM jelly_blocks").fetchone()[0] == 0
    assert conn.execute("SELECT COALESCE(SUM(balance),0) FROM jelly_wallets").fetchone()[0] == 0
    conn.close()


def test_joined_node_refuses_to_mine(client, hosting):
    client.post("/api/jelly/mode", json={"mode": "joined", "home_peer": "wes"})
    r = client.get("/api/jelly/mining/work?miner=rig1&gpu=T&hashrate=1")
    assert r.status_code == 400, "mining a joined node would found the island it just avoided"
    detail = str(r.json())
    assert "wes" in detail and "participant" in detail


def test_rejoining_home_restores_a_chain(client, hosting):
    client.post("/api/jelly/mode", json={"mode": "joined", "home_peer": "wes"})
    assert client.get("/api/jelly/status").json()["chain"] is False
    r = client.post("/api/jelly/mode", json={"mode": "host"})
    assert r.status_code == 200, r.text
    st = client.get("/api/jelly/status").json()
    assert st["mode"] == "host" and st["chain"] is True
    assert st["supply"] >= 1_000_000, "switching back must re-found the chain"


def test_joining_is_refused_once_the_chain_has_been_used(client, hosting):
    """The guard that matters: never strand coins that exist only on this ledger."""
    jellycoin.transfer(jellycoin.TREASURY, "somebody", 5 * jellycoin.UNIT, memo="real activity")
    assert jellycoin.chain_is_used() is True
    r = client.post("/api/jelly/mode", json={"mode": "joined", "home_peer": "wes"})
    assert r.status_code == 400
    assert "strand" in r.json()["detail"]
    assert jellycoin.jelly_mode() == "host", "a refused switch must not take effect"
    assert client.get("/api/jelly/status").json()["chain"] is True


def test_joined_node_runs_no_economy_of_its_own(client, hosting):
    """We have no ledger to bill on — the home node's chain is where value moves.

    Sets the mode setting directly rather than POSTing: the switch is refused once
    any earlier test has used the shared session chain, and what's under test here
    is billing behaviour in joined mode, not the guard (which has its own test).
    """
    from deps import get_conn
    assert jellycoin.peer_billing_enabled() is True          # hosting: normal
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('jelly_mode','joined')")
    conn.commit()
    conn.close()

    assert jellycoin.jelly_mode() == "joined"
    assert jellycoin.peer_billing_enabled() is False
    # and billing calls stay inert rather than erroring or racking up comped tabs
    assert jellycoin.peer_job_charge("wes", "llm")["billed"] is False
    assert jellycoin.peer_job_credit("wes", "review")["billed"] is False


def test_mode_is_validated(client, hosting):
    assert client.post("/api/jelly/mode", json={"mode": "sideways"}).status_code == 400
    # joining needs to know WHOSE network
    assert client.post("/api/jelly/mode", json={"mode": "joined"}).status_code == 400
    assert jellycoin.jelly_mode() == "host"
