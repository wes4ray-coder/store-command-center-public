"""JellyCoin — chain genesis, GPU getwork/submit round-trip (CPU-*verified*, never
CPU-*mined*: the test grinds a nonce in Python only to prove the server's validator,
exactly what the real GPU rig does on hardware), transfers, boosts, NFTs, missions."""
import hashlib
import struct

import pytest


def _solve(header76_hex: str, target_hex: str, max_tries: int = 5_000_000) -> int:
    """Find a valid nonce the same way the GPU kernel does (sha256d < target)."""
    header = bytes.fromhex(header76_hex)
    target = int(target_hex, 16)
    for nonce in range(max_tries):
        msg = header + struct.pack(">I", nonce)
        h = hashlib.sha256(hashlib.sha256(msg).digest()).digest()
        if int.from_bytes(h, "big") < target:
            return nonce
    pytest.fail("no nonce found — target unexpectedly hard for genesis difficulty")


def _mine_one(client, miner="testrig"):
    w = client.get(f"/api/jelly/mining/work?miner={miner}&gpu=TestGPU&hashrate=1000000").json()
    nonce = _solve(w["header76"], w["target"])
    r = client.post("/api/jelly/mining/submit",
                    json={"work_id": w["work_id"], "nonce": nonce, "miner": miner}).json()
    assert r.get("ok"), r
    return r


def _balance(client, name):
    for w in client.get("/api/jelly/wallets").json()["wallets"]:
        if w["name"] == name:
            return w["balance"]
    return 0


def test_genesis_and_status(client):
    st = client.get("/api/jelly/status").json()
    assert st["symbol"] == "JLY"
    assert st["height"] >= 0
    assert st["supply"] >= 1_000_000          # premine
    # premine landed: treasury + the AI friend's grant
    assert _balance(client, "treasury") > 0
    assert _balance(client, "assistant") == 500 * 1_000_000


def test_gpu_work_submit_roundtrip(client):
    st0 = client.get("/api/jelly/status").json()
    res = _mine_one(client)
    assert res["height"] == st0["height"] + 1
    assert res["reward"] == 50.0
    assert _balance(client, "miner:testrig") >= 50 * 1_000_000
    st1 = client.get("/api/jelly/status").json()
    assert st1["height"] == st0["height"] + 1
    assert any(m["name"] == "testrig" and m["blocks"] >= 1 for m in st1["miners"])


def test_stale_and_bad_submits_rejected(client):
    w = client.get("/api/jelly/mining/work?miner=testrig").json()
    bad = client.post("/api/jelly/mining/submit",
                      json={"work_id": w["work_id"], "nonce": 0, "miner": "testrig"}).json()
    # nonce 0 is astronomically unlikely to be valid; if it is, mining still succeeded
    if not bad.get("ok"):
        assert "target" in bad["reason"]
    unknown = client.post("/api/jelly/mining/submit",
                          json={"work_id": "nope", "nonce": 1, "miner": "x"}).json()
    assert not unknown.get("ok")


def test_skilling_boosts_pay_only_inside_mined_block(client):
    import jellycoin
    from deps import get_conn
    conn = get_conn()
    jellycoin.skill_pulse(conn, "amber", "Amber", "woodcutting", 4)
    jellycoin.skill_pulse(conn, "amber", "Amber", "fishing", 2)
    conn.commit()
    conn.close()
    assert client.get("/api/jelly/status").json()["boosts_pending"] == 6
    res = _mine_one(client)
    assert res["boost_paid"] == pytest.approx(6 * 0.05)
    assert client.get("/api/jelly/status").json()["boosts_pending"] == 0
    assert _balance(client, "agent:amber") == int(6 * 0.05 * 1_000_000 * 0.5)
    assert _balance(client, "company") > 0


def test_transfer_and_ai_friend_tip(client):
    r = client.post("/api/jelly/transfer",
                    json={"from": "treasury", "to": "wes", "amount_jly": 10, "memo": "hi"})
    assert r.status_code == 200
    assert _balance(client, "wes") == 10 * 1_000_000
    # overdraft blocked
    r = client.post("/api/jelly/transfer", json={"from": "wes", "to": "treasury", "amount_jly": 999})
    assert r.status_code == 400
    # AI friend tips from its granted purse
    before = _balance(client, "assistant")
    r = client.post("/api/jelly/tip", json={"to": "wes", "amount_jly": 1})
    assert r.status_code == 200
    assert _balance(client, "assistant") == before - 1_000_000


def test_nft_mint_and_transfer(client, tmp_path):
    art = tmp_path / "jelly-art.png"
    art.write_bytes(b"\x89PNG fake-art-bytes " * 40)
    r = client.post("/api/jelly/nft/mint",
                    json={"file_path": str(art), "title": "Jelly Sunrise", "owner": "treasury"})
    assert r.status_code == 200, r.text
    token = r.json()["token_id"]
    # same artwork can't be minted twice
    r2 = client.post("/api/jelly/nft/mint", json={"file_path": str(art), "owner": "treasury"})
    assert r2.status_code == 400
    lst = client.get("/api/jelly/nft/list").json()["nfts"]
    assert any(n["token_id"] == token for n in lst)
    r3 = client.post("/api/jelly/nft/transfer",
                     json={"token_id": token, "from": "treasury", "to": "wes"})
    assert r3.status_code == 200 and r3.json()["owner"] == "wes"


def test_missions_wait_for_god_approval(client):
    r = client.post("/api/jelly/missions/draft", json={"kind": "promo"})
    assert r.status_code == 200
    mid = r.json()["id"]
    assert r.json()["status"] == "proposed"          # never auto-acts
    ms = client.get("/api/jelly/missions").json()["missions"]
    assert any(m["id"] == mid and m["status"] == "proposed" for m in ms)
    r = client.post(f"/api/jelly/missions/{mid}/decide", json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # can't re-decide
    r = client.post(f"/api/jelly/missions/{mid}/decide", json={"approve": False})
    assert r.status_code == 400


def test_buddy_compute_economy(client):
    """JLY as the peer network's working coin: credit for lending, charge for using,
    comped (never blocked) when broke, and the god-side settings endpoint."""
    import jellycoin
    # buddy lends us compute → treasury pays their peer wallet
    r = jellycoin.peer_job_credit("Buddy", "llm")
    assert r["billed"] and r["amount"] == 1_000_000        # default 1 JLY/llm job
    assert _balance(client, "peer:Buddy") == 1_000_000
    # buddy uses our AI helper → charged back into the company wallet
    company0 = _balance(client, "company")
    r = jellycoin.peer_job_charge("Buddy", "llm")
    assert r["billed"]
    assert _balance(client, "peer:Buddy") == 0
    assert _balance(client, "company") == company0 + 1_000_000
    # broke buddy: job is comped, never blocked, and the tab is recorded
    r = jellycoin.peer_job_charge("Buddy", "llm")
    assert not r["billed"] and r["reason"] == "comped"
    pb = client.get("/api/jelly/peer-billing").json()
    assert pb["enabled"] and pb["comped_jobs"] >= 1
    assert any(w["name"] == "peer:Buddy" for w in pb["peer_wallets"])
    # embeddings are 1/10th price
    assert jellycoin.peer_job_price("embedding") == 100_000
    # god can change price and switch billing off entirely
    r = client.post("/api/jelly/peer-billing", json={"enabled": True, "price_jly": 2.5})
    assert r.json()["price_jly"] == 2.5
    r = client.post("/api/jelly/peer-billing", json={"enabled": False})
    assert not r.json()["enabled"]
    assert jellycoin.peer_job_charge("Buddy", "llm") == {"billed": False, "reason": "billing off"}
    client.post("/api/jelly/peer-billing", json={"enabled": True, "price_jly": 1})


def test_miner_token_exists_and_encrypted_at_rest(client):
    r = client.get("/api/jelly/miner-token").json()
    assert len(r["token"]) >= 32 and "jellyminer.py" in r["run"]
    # security protocol: the token row in settings must be ciphertext, not the raw token
    import crypto as store_crypto
    from deps import get_conn
    conn = get_conn()
    raw = conn.execute("SELECT value FROM settings WHERE key='jelly_miner_token'").fetchone()["value"]
    conn.close()
    assert store_crypto.is_encrypted(raw) and raw != r["token"]
    assert "jelly_miner_token" in store_crypto.SECRET_KEYS


def test_stats_series_and_docs(client):
    _mine_one(client)                       # ensure ≥2 blocks so series exist
    _mine_one(client)
    s = client.get("/api/jelly/stats").json()
    assert len(s["series"]) >= 3            # genesis + 2 mined
    last = s["series"][-1]
    assert last["difficulty"] >= 1.0 and last["supply"] > 1_000_000
    assert s["series"][0]["interval"] is None and last["interval"] is not None
    assert s["target_block_sec"] == 60
    assert any(r["miner"] == "testrig" for r in s["per_rig"])
    # white paper + security docs are served
    wp = client.get("/api/jelly/doc/whitepaper")
    assert wp.status_code == 200 and "Proof-of-work specification" in wp.text
    sec = client.get("/api/jelly/doc/security")
    assert sec.status_code == 200 and "Incident playbook" in sec.text
    assert client.get("/api/jelly/doc/nope").status_code == 404
