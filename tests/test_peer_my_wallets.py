"""My wallets on buddies' chains — the cross-node earnings view.

JellyCoin is per-node: what we earn on a buddy's network lives in our peer:<name>
wallet on THEIR ledger. /api/peers/my-wallets fans out to each approved buddy's
rpc/wallet and totals it. The property that matters operationally: one unreachable
buddy degrades to a per-row note, it never sinks the whole panel.
"""
import pytest

from test_peers import _raw, _pair


def _approved(client, name):
    raw = _raw()
    pid, key = _pair(client, raw, name=name)
    client.post(f"/api/peers/{pid}/approve")
    return pid, key


def test_my_wallets_totals_reachable_buddies(client, monkeypatch):
    _approved(client, "rich-pal")
    _approved(client, "poor-pal")
    import routers.peers.api as papi
    balances = {"rich-pal": 12.5, "poor-pal": 0.25}
    monkeypatch.setattr(papi, "_call_peer", lambda peer, *a, **k: {
        "ok": True, "symbol": "JLY", "wallet": "peer:me", "address": "jly1me",
        "balance_jly": balances[peer["name"]], "billing": True,
        "price_per_llm_job_jly": 1.0, "price_per_review_jly": 1.0, "recent_txs": []})

    r = client.get("/api/peers/my-wallets")
    assert r.status_code == 200, r.text
    data = r.json()
    # the client fixture is session-scoped, so earlier tests' peers linger — scope
    # the assertions to the two this test paired.
    mine = {w["peer"]: w for w in data["wallets"] if w["peer"] in balances}
    assert len(mine) == 2
    assert {n: w["balance_jly"] for n, w in mine.items()} == balances
    assert all(w["ok"] and w["wallet"] == "peer:me" for w in mine.values())
    assert data["total_jly"] >= 12.75 - 1e-9        # our two are included in the total
    assert data["peers"] >= 2 and data["reachable"] >= 2


def test_one_offline_buddy_does_not_sink_the_panel(client, monkeypatch):
    _approved(client, "up-pal")
    _approved(client, "down-pal")
    from fastapi import HTTPException
    import routers.peers.api as papi

    def flaky(peer, *a, **k):
        if peer["name"] == "down-pal":
            raise HTTPException(502, "Could not reach peer 'down-pal': timed out")
        return {"balance_jly": 4.0, "symbol": "JLY", "wallet": "peer:me", "recent_txs": []}

    monkeypatch.setattr(papi, "_call_peer", flaky)
    r = client.get("/api/peers/my-wallets")
    assert r.status_code == 200, "an offline buddy must not 502 the whole view"
    data = r.json()
    rows = {w["peer"]: w for w in data["wallets"]}
    assert rows["up-pal"]["ok"] is True
    assert rows["up-pal"]["balance_jly"] == pytest.approx(4.0)
    assert rows["down-pal"]["ok"] is False
    assert "reach" in rows["down-pal"]["error"]
    assert "balance_jly" not in rows["down-pal"]      # no fake zero for an unknown balance
    assert data["reachable"] < data["peers"]          # the outage is reported, not hidden


def test_my_wallets_is_not_shadowed_by_the_pid_routes(client, monkeypatch):
    """'my-wallets' must resolve as a literal path, never as peers/{pid}."""
    import routers.peers.api as papi
    monkeypatch.setattr(papi, "_call_peer", lambda *a, **k: {"balance_jly": 0})
    r = client.get("/api/peers/my-wallets")
    assert r.status_code == 200
    assert "wallets" in r.json() and "total_jly" in r.json()


def test_my_wallets_needs_a_session(client):
    raw = _raw()
    assert raw.get("/api/peers/my-wallets").status_code == 401
