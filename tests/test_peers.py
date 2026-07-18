"""Peer network — pairing flow, key auth scope, and host-controlled work sharing.

The security property under test: a peer key opens ONLY /api/peers/rpc/*, and each
rpc endpoint re-checks the key itself; the key must never work on any other API
path, a pending/revoked peer must be locked out, and one peer must never see
another peer's jobs or reviews.
"""


def _raw():
    """An UNauthenticated client (no session) — simulates the remote friend node."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app, base_url="https://testserver")


def _pair(client, raw, name="buddy"):
    """Full pairing dance; returns (peer_id_on_host, key_the_friend_uses)."""
    inv = client.post("/api/peers/invite", json={"note": name}).json()["invite_key"]
    r = raw.post("/api/peers/rpc/pair", json={
        "invite_key": inv, "name": name, "base_url": "http://friend.example/store",
        "key": "peer_friend_accepts_this"})
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    peers = client.get("/api/peers").json()["peers"]
    pid = [p["id"] for p in peers if p["name"] == name][-1]
    return pid, key


def test_pairing_requires_invite_and_approval(client):
    raw = _raw()
    # middleware lets rpc through without a session, but pair still needs a valid invite
    r = raw.post("/api/peers/rpc/pair", json={"invite_key": "pinv_bogus", "name": "x", "key": "k"})
    assert r.status_code == 401
    assert "detail" in r.json()          # HTTPException from the endpoint, not the auth guard

    pid, key = _pair(client, raw, name="pending-pal")
    # pending peer: key does not work yet
    r = raw.get("/api/peers/rpc/ping", headers={"X-Peer-Key": key})
    assert r.status_code == 401
    # approve → key works
    assert client.post(f"/api/peers/{pid}/approve").status_code == 200
    r = raw.get("/api/peers/rpc/ping", headers={"X-Peer-Key": key})
    assert r.status_code == 200
    assert "branch" in r.json() and "recently_promoted" in r.json()
    # invite key is one-time
    # (re-using the same invite must fail — it was consumed by the pair above)
    inv_reuse = raw.post("/api/peers/rpc/pair", json={"invite_key": "pinv_bogus", "name": "x", "key": "k"})
    assert inv_reuse.status_code == 401


def test_peer_key_opens_nothing_but_rpc(client):
    raw = _raw()
    pid, key = _pair(client, raw, name="scope-pal")
    client.post(f"/api/peers/{pid}/approve")
    # the peer key must NOT authenticate any normal API path — the session guard 401s
    for path in ("/api/settings", "/api/peers", "/api/prompts", "/api/github/status"):
        r = raw.get(path, headers={"X-Peer-Key": key})
        assert r.status_code == 401, f"{path} leaked to a peer key!"
        assert r.json().get("error") == "Unauthorized"   # blocked by the auth guard itself
    # no key at all on rpc → 401 from the endpoint
    assert raw.get("/api/peers/rpc/ping").status_code == 401
    # garbage key → 401
    assert raw.get("/api/peers/rpc/ping", headers={"X-Peer-Key": "peer_wrong"}).status_code == 401


def test_work_sharing_is_host_opt_in_and_peer_scoped(client):
    raw = _raw()
    pid, key = _pair(client, raw, name="worker-pal")
    client.post(f"/api/peers/{pid}/approve")
    hdr = {"X-Peer-Key": key}
    # accept_work defaults OFF → 403
    r = raw.post("/api/peers/rpc/job", headers=hdr,
                 json={"kind": "llm", "user": "say hi"})
    assert r.status_code == 403
    # host flips it on for this peer
    assert client.post(f"/api/peers/{pid}/config", json={"accept_work": True}).status_code == 200
    r = raw.post("/api/peers/rpc/job", headers=hdr, json={"kind": "llm", "user": "say hi"})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    st = raw.get(f"/api/peers/rpc/job/{jid}", headers=hdr)
    assert st.status_code == 200
    assert st.json()["status"] in ("queued", "done", "error")   # LM Studio is absent in tests
    # bad kinds / empty prompts rejected
    assert raw.post("/api/peers/rpc/job", headers=hdr, json={"kind": "video"}).status_code == 400
    assert raw.post("/api/peers/rpc/job", headers=hdr, json={"kind": "llm", "user": " "}).status_code == 400

    # a SECOND peer must not see the first peer's job
    pid2, key2 = _pair(client, raw, name="other-pal")
    client.post(f"/api/peers/{pid2}/approve")
    r = raw.get(f"/api/peers/rpc/job/{jid}", headers={"X-Peer-Key": key2})
    assert r.status_code == 404

    # per-kind gate: host allows ONLY embeddings → llm jobs are refused
    client.post(f"/api/peers/{pid}/config", json={"work_kinds": "embedding"})
    r = raw.post("/api/peers/rpc/job", headers=hdr, json={"kind": "llm", "user": "hi"})
    assert r.status_code == 403
    client.post(f"/api/peers/{pid}/config", json={"work_kinds": "llm,embedding"})
    assert raw.post("/api/peers/rpc/job", headers=hdr,
                    json={"kind": "llm", "user": "hi"}).status_code == 200

    # model capability listing: key-gated, and tolerant of LM Studio being down
    assert raw.get("/api/peers/rpc/models").status_code == 401
    r = raw.get("/api/peers/rpc/models", headers=hdr)
    assert r.status_code == 200 and "models" in r.json()


def test_connection_info(client):
    r = client.get("/api/peers/connection-info")
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j["port"], int) and "public_url" in j


def test_incoming_review_and_human_vote(client):
    raw = _raw()
    pid, key = _pair(client, raw, name="review-pal")
    client.post(f"/api/peers/{pid}/approve")
    hdr = {"X-Peer-Key": key}
    r = raw.post("/api/peers/rpc/review", headers=hdr,
                 json={"title": "add feature X", "diff": "diff --git a/x b/x\n+hello"})
    assert r.status_code == 200, r.text
    rid = r.json()["review_id"]
    st = raw.get(f"/api/peers/rpc/review/{rid}", headers=hdr)
    assert st.status_code == 200
    assert st.json()["status"] in ("reviewing", "done", "error")
    # the HOST human votes on it locally; the peer sees the vote on next poll
    v = client.post(f"/api/peers/reviews/{rid}/vote", json={"vote": "approve", "comments": "lgtm"})
    assert v.status_code == 200
    st = raw.get(f"/api/peers/rpc/review/{rid}", headers=hdr).json()
    assert st["human_vote"] == "approve"
    # votes are validated
    assert client.post(f"/api/peers/reviews/{rid}/vote", json={"vote": "maybe"}).status_code == 400
    # review scoping: another peer can't read it
    pid2, key2 = _pair(client, raw, name="nosy-pal")
    client.post(f"/api/peers/{pid2}/approve")
    assert raw.get(f"/api/peers/rpc/review/{rid}", headers={"X-Peer-Key": key2}).status_code == 404
    # host can turn review intake off per-peer
    client.post(f"/api/peers/{pid}/config", json={"accept_reviews": False})
    r = raw.post("/api/peers/rpc/review", headers=hdr, json={"title": "t", "diff": "+x"})
    assert r.status_code == 403


def test_revoke_kills_key_immediately(client):
    raw = _raw()
    pid, key = _pair(client, raw, name="revoked-pal")
    client.post(f"/api/peers/{pid}/approve")
    assert raw.get("/api/peers/rpc/ping", headers={"X-Peer-Key": key}).status_code == 200
    assert client.delete(f"/api/peers/{pid}").status_code == 200
    assert raw.get("/api/peers/rpc/ping", headers={"X-Peer-Key": key}).status_code == 401


def test_update_channels_match_real_branches(client):
    # regression: the channel list once offered "main", which doesn't exist (master does)
    from routers.system import _UPDATE_CHANNELS
    assert "main" not in _UPDATE_CHANNELS
    assert {"retail", "master", "dev"} == set(_UPDATE_CHANNELS)
    # installs that SAVED channel 'main' before the rename must be remapped, not wedged
    assert client.post("/api/system/update-config", json={"channel": "main"}).status_code == 200
    assert client.get("/api/system/update-status").json()["channel"] == "master"
    client.post("/api/system/update-config", json={"channel": "master"})
