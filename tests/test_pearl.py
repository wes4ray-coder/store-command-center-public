"""Pearl (PRL) tab — status stays graceful unconfigured, settings contract,
secrets-at-rest wiring, and the hard mining gate (start refused while the
toggle is off; no SSH is ever attempted with the toggle off)."""
import pytest


def test_status_unconfigured_is_graceful(client):
    r = client.get("/api/crypto/pearl/status")
    assert r.status_code == 200
    d = r.json()
    assert d["symbol"] == "PRL"
    assert d["node"] == {"configured": False}
    assert d["wallet"] == {"configured": False}
    # toggle off by default → miner state is reported WITHOUT any SSH probe
    assert d["mining_enabled"] is False
    assert d["miner"]["state"] == "toggle-off"


def test_research_card_has_verdict_and_red_flags(client):
    r = client.get("/api/crypto/pearl/research")
    assert r.status_code == 200
    d = r.json()
    assert d["actual_name"].startswith("Pearl")
    assert d["red_flags"] and d["sources"] and d["setup"]
    assert any("pearl-research-labs" in s for s in d["sources"])


def test_settings_roundtrip_and_masking(client):
    r = client.post("/api/crypto/pearl/settings", json={
        "pearl_node_url": "http://127.0.0.1:8334",
        "pearl_rpc_user": "prluser",
        "pearl_rpc_pass": "supersecret99",
    })
    assert r.status_code == 200 and set(r.json()["saved"]) == {
        "pearl_node_url", "pearl_rpc_user", "pearl_rpc_pass"}
    d = client.get("/api/crypto/pearl/settings").json()["settings"]
    assert d["pearl_node_url"] == "http://127.0.0.1:8334"
    # secret comes back masked, last 4 chars only
    assert d["pearl_rpc_pass"].endswith("et99") and "supersecret99" not in d["pearl_rpc_pass"]
    # blank secret = keep the saved one
    r = client.post("/api/crypto/pearl/settings", json={"pearl_rpc_pass": ""})
    assert r.status_code == 200 and r.json()["saved"] == []
    # stored encrypted at rest (Fernet marker), and registered as a secret key
    import crypto as secrets_at_rest
    import db
    assert "pearl_rpc_pass" in secrets_at_rest.SECRET_KEYS
    conn = db.get_conn()
    raw = conn.execute("SELECT value FROM settings WHERE key='pearl_rpc_pass'").fetchone()["value"]
    conn.close()
    assert secrets_at_rest.is_encrypted(raw)


def test_settings_rejects_unknown_keys_and_bad_unit(client):
    assert client.post("/api/crypto/pearl/settings",
                       json={"btc_rpc_user": "x"}).status_code == 400
    assert client.post("/api/crypto/pearl/settings",
                       json={"pearl_miner_unit": "bad unit; rm -rf"}).status_code == 400


def test_miner_start_is_gated_on_toggle(client):
    # toggle off (default) → start is REFUSED before any SSH happens
    r = client.post("/api/crypto/pearl/settings", json={"pearl_mining_enabled": "0"})
    assert r.status_code == 200 and r.json()["mining_enabled"] is False
    r = client.post("/api/crypto/pearl/miner/start")
    assert r.status_code == 403
    assert "toggle" in r.json()["detail"].lower()
    # bogus action → 400
    assert client.post("/api/crypto/pearl/miner/reboot").status_code == 400


def test_pearl_settings_ride_the_key_backup(client):
    from routers import crypto as crypto_router
    assert "pearl_" in crypto_router._BACKUP_PREFIXES


def test_agent_access_defaults_off_and_toggles(client):
    import pearl
    # default OFF, surfaced in the status rollup
    assert pearl.agent_access_enabled() is False
    assert client.get("/api/crypto/pearl/status").json()["agent_access"] is False
    # toggling it on/off round-trips
    r = client.post("/api/crypto/pearl/settings", json={"pearl_agent_access": "1"})
    assert r.status_code == 200 and "pearl_agent_access" in r.json()["saved"]
    assert client.get("/api/crypto/pearl/status").json()["agent_access"] is True
    client.post("/api/crypto/pearl/settings", json={"pearl_agent_access": "0"})
    assert pearl.agent_access_enabled() is False


def test_agent_caller_is_gated_even_with_mining_on(client):
    """A non-human (agent) caller is refused unless pearl_agent_access is on —
    exercised at the module level since the human TestClient session is always
    'human'. With mining ON but agent-access OFF, an agent start is a 403."""
    import pearl
    client.post("/api/crypto/pearl/settings",
                json={"pearl_mining_enabled": "1", "pearl_agent_access": "0"})
    try:
        with pytest.raises(PermissionError):
            pearl.miner_action("start", by_agent=True)
    finally:
        client.post("/api/crypto/pearl/settings", json={"pearl_mining_enabled": "0"})
