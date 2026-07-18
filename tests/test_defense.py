"""Unified defense status (app/defense.py) — toggles, last-run persistence, posture."""
import time

import defense
import db


def test_last_run_roundtrip():
    assert defense.last_run("nosuchjob") is None
    assert defense.persisted_last("nosuchjob") == 0.0
    defense.record_run("testjob", "did a thing")
    lr = defense.last_run("testjob")
    assert lr and lr["ago_s"] < 5 and lr["note"] == "did a thing"
    assert abs(defense.persisted_last("testjob") - time.time()) < 5


def test_toggle_rejects_unknown_and_host_defenses():
    assert defense.toggle("nope", True)["ok"] is False
    assert defense.toggle("fail2ban", True)["ok"] is False   # host defense — not togglable


def test_toggle_writes_setting_and_interval():
    r = defense.toggle("sec_audit", True, interval_min=90)
    assert r["ok"] and r["enabled"] is True
    conn = db.get_conn()
    on = conn.execute("SELECT value FROM settings WHERE key='security_audit_enabled'").fetchone()
    iv = conn.execute("SELECT value FROM settings WHERE key='security_audit_interval'").fetchone()
    conn.close()
    assert on["value"] == "1" and iv["value"] == "90"
    assert defense.toggle("sec_audit", False)["enabled"] is False


def test_app_defenses_reflect_settings():
    defense.toggle("guardian", True)
    ids = {d["id"]: d for d in defense._app_defenses()}
    assert set(ids) == set(defense.APP_DEFENSES)
    assert ids["guardian"]["enabled"] is True and ids["guardian"]["toggle"] is True
    # enabled-but-stale jobs surface as 'warn', fresh ones as 'on'
    defense.record_run("guardian", "ok")
    ids = {d["id"]: d for d in defense._app_defenses()}
    assert ids["guardian"]["status"] == "on"
    defense.toggle("guardian", False)


def test_posture_shape_on_fresh_db():
    p = defense.posture()
    assert set(p) == {"score", "grade", "snapshot_at", "history", "events"}
    assert isinstance(p["history"], list) and isinstance(p["events"], list)


def test_toggle_endpoint(client):
    r = client.post("/api/security/defenses/toggle", json={"id": "nope", "on": True})
    assert r.status_code == 400
    r = client.post("/api/security/defenses/toggle", json={"id": "ai_hunt", "on": False})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.get("/api/security/posture")
    assert r.status_code == 200 and "grade" in r.json()
