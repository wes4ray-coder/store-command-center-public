"""Buddy-share mining pool (M1) — proportional share-based reward splitting.

The pool is gated behind a toggle that DEFAULTS OFF: with it off, mining is the
exact winner-take-all path (asserted here + by test_jellycoin.py). With it on,
rigs submit frequent SHARES against an easier target, and the block reward is
split pro-rata by each owner's shares. Like the core mining test, these grind a
nonce in Python only to drive the server's validator (never CPU-*mine*)."""
import hashlib
import struct

import pytest

UNIT = 1_000_000


def _sha256d(header: bytes, nonce: int) -> int:
    return int.from_bytes(
        hashlib.sha256(hashlib.sha256(header + struct.pack(">I", nonce)).digest()).digest(), "big")


def _share_only_nonce(header_hex: str, target_hex: str, share_hex: str) -> int:
    """A nonce that meets the SHARE target but NOT the block target (a pure share)."""
    header = bytes.fromhex(header_hex)
    btarget, starget = int(target_hex, 16), int(share_hex, 16)
    for nonce in range(200_000):
        h = _sha256d(header, nonce)
        if h < starget and h >= btarget:
            return nonce
    pytest.fail("no share-only nonce found — share target unexpectedly tight")


def _block_nonce(header_hex: str, target_hex: str) -> int:
    header, btarget = bytes.fromhex(header_hex), int(target_hex, 16)
    for nonce in range(5_000_000):
        if _sha256d(header, nonce) < btarget:
            return nonce
    pytest.fail("no block nonce found — target unexpectedly hard for genesis difficulty")


def _balance(client, name):
    for w in client.get("/api/jelly/wallets").json()["wallets"]:
        if w["name"] == name:
            return w["balance"]
    return 0


def _submit_share(client, rig):
    w = client.get(f"/api/jelly/mining/work?miner={rig}&gpu=T&hashrate=1").json()
    assert "share_target" in w, "pool ON must advertise share_target"
    nonce = _share_only_nonce(w["header76"], w["target"], w["share_target"])
    r = client.post("/api/jelly/mining/submit",
                    json={"work_id": w["work_id"], "nonce": nonce, "miner": rig}).json()
    assert r["ok"] and r["share"] and not r["block"], r
    return r


def _submit_block(client, rig):
    w = client.get(f"/api/jelly/mining/work?miner={rig}&gpu=T&hashrate=1").json()
    nonce = _block_nonce(w["header76"], w["target"])
    r = client.post("/api/jelly/mining/submit",
                    json={"work_id": w["work_id"], "nonce": nonce, "miner": rig}).json()
    assert r["ok"] and r["share"] and r["block"], r
    return r


def test_pool_off_is_winner_take_all(client):
    """The safety net: OFF ⇒ getwork has no share_target and the whole reward
    goes to the single solver (byte-for-byte today's behavior)."""
    client.post("/api/jelly/pool", json={"enabled": False})
    w = client.get("/api/jelly/mining/work?miner=solo1&gpu=T&hashrate=1").json()
    assert "share_target" not in w
    nonce = _block_nonce(w["header76"], w["target"])
    r = client.post("/api/jelly/mining/submit",
                    json={"work_id": w["work_id"], "nonce": nonce, "miner": "solo1"}).json()
    assert r["ok"] and "share" not in r          # winner-take-all response shape
    assert _balance(client, "miner:solo1") == 50 * UNIT


def test_pool_on_splits_reward_pro_rata(client):
    """Two rigs submit shares, one finds the block; the 50 JLY reward splits
    pro-rata by shares with integer accounting (dust → the solver)."""
    client.post("/api/jelly/pool", json={"enabled": True})
    try:
        a0, b0 = _balance(client, "miner:rigA"), _balance(client, "miner:rigB")
        _submit_share(client, "rigB")               # rigB: 1 share
        _submit_share(client, "rigA")               # rigA: 1 share …
        res = _submit_block(client, "rigA")         # … + block (records a 2nd share for A)
        assert res["block"]
        reward = 50 * UNIT
        # round shares: rigA=2, rigB=1, total=3
        cut_b = reward * 1 // 3
        cut_a = reward * 2 // 3
        remainder = reward - cut_a - cut_b          # rounding dust → solver (rigA)
        got_a = _balance(client, "miner:rigA") - a0
        got_b = _balance(client, "miner:rigB") - b0
        assert got_b == cut_b
        assert got_a == cut_a + remainder
        assert got_a + got_b == reward              # no coins lost or created
    finally:
        client.post("/api/jelly/pool", json={"enabled": False})


def test_pool_endpoint_roundtrip(client):
    r = client.post("/api/jelly/pool",
                    json={"enabled": True, "owners": {"maprig": "peer:MapBuddy"}}).json()
    try:
        assert r["enabled"] is True and r["share_factor"] == 65536
        for k in ("round_id", "projected_split", "shares_by_rig", "recent_payouts"):
            assert k in r
        g = client.get("/api/jelly/pool").json()
        assert g["enabled"] is True and g["share_factor"] == 65536
        from deps import get_conn
        conn = get_conn()
        row = conn.execute("SELECT owner FROM jelly_miners WHERE name='maprig'").fetchone()
        conn.close()
        assert row["owner"] == "peer:MapBuddy"      # rig→wallet mapping persisted
    finally:
        client.post("/api/jelly/pool", json={"enabled": False})
    assert client.get("/api/jelly/pool").json()["enabled"] is False


def test_pool_pays_buddy_peer_wallet(client):
    """A buddy rig mapped to its peer:<name> custodial wallet is paid there."""
    client.post("/api/jelly/pool",
                json={"enabled": True, "owners": {"buddyrig": "peer:PoolBuddy"}})
    try:
        p0 = _balance(client, "peer:PoolBuddy")
        _submit_share(client, "buddyrig")           # sole contributor this round
        res = _submit_block(client, "buddyrig")
        assert res["block"] and res["owner"] == "peer:PoolBuddy"
        assert _balance(client, "peer:PoolBuddy") - p0 == 50 * UNIT
    finally:
        client.post("/api/jelly/pool", json={"enabled": False})
