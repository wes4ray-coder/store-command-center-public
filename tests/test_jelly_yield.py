"""JellyCoin miner yield-to-queue — mining stands down while the AI queue owns the GPU.

The node runs LM Studio + ComfyUI AND the JLY miner on one RTX 3060; sharing it
produced real "could not load required model X" / "the GPU may be busy with
another model or ComfyUI" failures. getwork now HOLDS (503 + {"pause": true})
while the queue is working and resumes after a settle window.

Busy is always mocked here (routers.jellycoin._queue_busy) — never real GPU load.
"""
import hashlib
import struct

import pytest


@pytest.fixture
def yld(monkeypatch):
    """Fresh yield state + settings around every test (the client fixture is
    session-scoped, so state would otherwise leak between tests)."""
    from routers import jellycoin as jr
    from deps import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE key IN (?,?,?)",
                 (jr.YIELD_KEY, jr.SETTLE_KEY, jr.RETRY_KEY))
    conn.commit()
    conn.close()
    jr._yield.update(held=False, idle_since=0.0, since=0.0)
    yield jr
    jr._yield.update(held=False, idle_since=0.0, since=0.0)


def _busy(monkeypatch, value):
    monkeypatch.setattr("routers.jellycoin._queue_busy", lambda: value)


def _work(client, miner="yieldrig"):
    return client.get(f"/api/jelly/mining/work?miner={miner}&gpu=TestGPU&hashrate=1000000")


def test_default_is_on(client, yld):
    assert yld._yield_enabled() is True, "the fix ships ON — it addresses a live failure"
    assert yld._settle_sec() == yld.SETTLE_DEFAULT
    assert yld._retry_sec() == yld.RETRY_DEFAULT


def test_idle_queue_issues_normal_work(client, yld, monkeypatch):
    _busy(monkeypatch, False)
    r = _work(client)
    assert r.status_code == 200
    w = r.json()
    assert w["work_id"] and w["header76"] and "pause" not in w


def test_busy_queue_holds_and_issues_no_work(client, yld, monkeypatch):
    _busy(monkeypatch, True)
    r = _work(client)
    assert r.status_code == 503, "old miners must see a plain HTTP error, not a half-response"
    body = r.json()
    assert body["pause"] is True and body["busy"] is True
    assert body["retry_after"] >= 2
    assert r.headers.get("Retry-After") == str(body["retry_after"])
    # nothing that could be mistaken for a job
    for k in ("work_id", "header76", "target", "height"):
        assert k not in body


def test_hold_still_heartbeats_the_rig(client, yld, monkeypatch):
    """A held rig must look online-but-paused, not dead."""
    _busy(monkeypatch, True)
    assert _work(client, "heldrig").status_code == 503
    st = client.get("/api/jelly/status").json()
    assert any(m["name"] == "heldrig" and m["online"] for m in st["miners"])


def test_hysteresis_settles_before_resuming(client, yld, monkeypatch):
    """Idle does not resume instantly — the queue must stay quiet for settle_sec,
    so a burst of queued jobs can't flap the miner on and off."""
    import time
    client.post("/api/jelly/miner-yield", json={"settle_sec": 30})
    _busy(monkeypatch, True)
    assert _work(client).status_code == 503

    _busy(monkeypatch, False)                      # queue just drained
    r = _work(client)
    assert r.status_code == 503, "must not resume the instant the queue empties"
    assert r.json()["busy"] is False and 0 < r.json()["resume_in"] <= 30

    # still inside the window
    monkeypatch.setattr(time, "time", lambda: yld._yield["idle_since"] + 29)
    assert _work(client).status_code == 503
    # past it → back to mining
    monkeypatch.setattr(time, "time", lambda: yld._yield["idle_since"] + 31)
    assert _work(client).status_code == 200


def test_single_momentary_job_pauses_immediately(client, yld, monkeypatch):
    _busy(monkeypatch, False)
    assert _work(client).status_code == 200
    _busy(monkeypatch, True)
    assert _work(client).status_code == 503, "one job is enough — no ramp-up delay"


def test_toggle_off_never_pauses(client, yld, monkeypatch):
    _busy(monkeypatch, True)
    r = client.post("/api/jelly/miner-yield", json={"enabled": False}).json()
    assert r["enabled"] is False and r["held"] is False
    assert _work(client).status_code == 200, "toggle OFF ⇒ mine straight through AI work"
    # and back on
    assert client.post("/api/jelly/miner-yield", json={"enabled": True}).json()["enabled"] is True
    assert _work(client).status_code == 503


def test_settings_round_trip_and_clamped(client, yld):
    r = client.post("/api/jelly/miner-yield", json={"settle_sec": 90, "retry_sec": 9}).json()
    assert r["settle_sec"] == 90 and r["retry_sec"] == 9
    r = client.post("/api/jelly/miner-yield", json={"settle_sec": 99999, "retry_sec": 0}).json()
    assert r["settle_sec"] == 600 and r["retry_sec"] == 2
    assert client.get("/api/jelly/miner-yield").json()["settle_sec"] == 600


def test_in_flight_submit_survives_a_pause(client, yld, monkeypatch):
    """A rig that got work, then the queue went busy, must still be able to bank
    the nonce it found. Submits are never gated, and because the hold returns
    before jellycoin.get_work() the WORK_TTL sweep can't expire the work either."""
    _busy(monkeypatch, False)
    w = _work(client, "inflightrig").json()
    header, target = bytes.fromhex(w["header76"]), int(w["target"], 16)
    for nonce in range(5_000_000):
        h = hashlib.sha256(hashlib.sha256(header + struct.pack(">I", nonce)).digest()).digest()
        if int.from_bytes(h, "big") < target:
            break
    else:
        pytest.fail("no nonce found at genesis difficulty")

    _busy(monkeypatch, True)                      # queue grabs the GPU mid-grind
    assert _work(client, "inflightrig").status_code == 503
    res = client.post("/api/jelly/mining/submit",
                      json={"work_id": w["work_id"], "nonce": nonce, "miner": "inflightrig"}).json()
    assert res.get("ok"), f"a pause must never cost a block: {res}"
    assert res["height"] == w["height"]


def test_token_guard_still_rejects_bad_or_missing_token(client, yld):
    """The hold path must not have loosened the LAN rig guard."""
    from types import SimpleNamespace
    from fastapi import HTTPException
    from routers import jellycoin as jr

    def req(headers):
        return SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"), headers=headers)

    for headers in ({}, {"X-Jelly-Token": "nope"}):
        with pytest.raises(HTTPException) as ex:
            jr._check_miner(req(headers))
        assert ex.value.status_code == 403
    jr._check_miner(req({"X-Jelly-Token": jr._miner_token()}))     # good token passes
