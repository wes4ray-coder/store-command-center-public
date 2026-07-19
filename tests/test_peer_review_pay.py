"""Buddy economy — code reviews are PAID AI work, both directions.

Incoming (their diff, our LLM): rpc_review charges the requesting peer's wallet
into the company wallet like any llm job — billed only on a delivered verdict,
comped (never blocked) if the buddy is broke. Outgoing (our diff, their LLM):
refresh_review_request pays the buddy's peer:<name> wallet from the treasury
exactly once, when the verdict first lands — a later human vote on the same
review is not billed again. A review prices like a full llm job."""

from test_peers import _raw, _pair

UNIT = 1_000_000


def _balance(client, name):
    for w in client.get("/api/jelly/wallets").json()["wallets"]:
        if w["name"] == name:
            return w["balance"]
    return 0


def _inline_orch(monkeypatch):
    """Run the review worker synchronously so the verdict (and billing) lands
    before the rpc_review response is even returned."""
    import routers.peers.rpc as rpc
    monkeypatch.setattr(rpc, "_call_lmstudio",
                        lambda *a, **k: '{"vote": "approve", "comments": "ship it"}')
    monkeypatch.setattr(rpc.orch, "submit_llm",
                        lambda fn, **k: (fn(), 0)[1])


def test_review_prices_like_a_full_llm_job():
    import jellycoin
    assert jellycoin.peer_job_price("review") == jellycoin.peer_job_price("llm") > 0
    assert jellycoin.peer_job_price("embedding") == jellycoin.peer_job_price("llm") // 10


def test_incoming_review_charges_the_peer_wallet(client, monkeypatch):
    _inline_orch(monkeypatch)
    raw = _raw()
    pid, key = _pair(client, raw, name="paying-pal")
    client.post(f"/api/peers/{pid}/approve")
    import jellycoin
    price = jellycoin.peer_job_price("review")
    jellycoin.transfer(jellycoin.TREASURY, "peer:paying-pal", 3 * price, memo="fund for test")
    before, company_before = _balance(client, "peer:paying-pal"), _balance(client, "company")

    r = raw.post("/api/peers/rpc/review", headers={"X-Peer-Key": key},
                 json={"title": "paid review", "diff": "diff --git a/x b/x\n+paid"})
    assert r.status_code == 200, r.text
    st = raw.get(f"/api/peers/rpc/review/{r.json()['review_id']}",
                 headers={"X-Peer-Key": key}).json()
    assert st["status"] == "done" and st["llm_vote"] == "approve"
    assert _balance(client, "peer:paying-pal") == before - price
    assert _balance(client, "company") == company_before + price


def test_incoming_review_comps_a_broke_buddy(client, monkeypatch):
    _inline_orch(monkeypatch)
    raw = _raw()
    pid, key = _pair(client, raw, name="broke-pal")
    client.post(f"/api/peers/{pid}/approve")

    r = raw.post("/api/peers/rpc/review", headers={"X-Peer-Key": key},
                 json={"title": "comped review", "diff": "diff --git a/y b/y\n+free"})
    assert r.status_code == 200, r.text
    st = raw.get(f"/api/peers/rpc/review/{r.json()['review_id']}",
                 headers={"X-Peer-Key": key}).json()
    assert st["status"] == "done"           # broke → still reviewed, never blocked
    assert _balance(client, "peer:broke-pal") == 0
    # the tab is recorded: an amount-0 comped tx from their wallet
    from deps import get_conn
    conn = get_conn()
    comped = conn.execute(
        "SELECT COUNT(*) FROM jelly_txs WHERE frm=? AND kind='compute_comped'",
        ("peer:broke-pal",)).fetchone()[0]
    conn.close()
    assert comped == 1


def test_outgoing_review_credit_pays_once_on_first_verdict(client, monkeypatch):
    raw = _raw()
    pid, key = _pair(client, raw, name="reviewer-pal")
    client.post(f"/api/peers/{pid}/approve")
    jid = client.post("/api/github/jobs", json={"title": "job under review"}).json()["id"]
    from deps import get_conn
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO peer_review_requests (peer_id,job_id,remote_review_id) VALUES (?,?,?)",
        (pid, jid, 777))
    conn.commit()
    rrid = cur.lastrowid
    conn.close()

    verdict = {"status": "done", "llm_vote": "approve", "llm_comments": "solid",
               "llm_model": "test-model", "human_vote": None, "human_comments": None}
    import routers.peers.api as papi
    monkeypatch.setattr(papi, "_call_peer", lambda *a, **k: dict(verdict))

    import jellycoin
    price = jellycoin.peer_job_price("review")
    before, treasury_before = _balance(client, "peer:reviewer-pal"), _balance(client, "treasury")
    r = client.post(f"/api/peers/review-requests/{rrid}/refresh")
    assert r.status_code == 200, r.text
    assert _balance(client, "peer:reviewer-pal") == before + price
    assert _balance(client, "treasury") == treasury_before - price

    # their human vote lands later on the SAME review → recorded, but not paid again
    verdict["human_vote"], verdict["human_comments"] = "approve", "lgtm from me too"
    assert client.post(f"/api/peers/review-requests/{rrid}/refresh").status_code == 200
    assert _balance(client, "peer:reviewer-pal") == before + price
