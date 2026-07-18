"""Production bills (world_bills) — CRUD, hysteresis band, scheduler integration."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def _conn():
    from deps import get_conn
    return get_conn()


def _clear_bills(c):
    import world_bills
    world_bills._ensure(c)
    c.execute("DELETE FROM world_bills")


def _set_done_images(c, n):
    c.execute("DELETE FROM generations")
    for i in range(n):
        c.execute("INSERT INTO generations (prompt,status) VALUES (?, 'done')", (f"bill test {i}",))


def test_bills_crud_via_api(client):
    r = client.post("/api/world/bills", json={"kind": "image", "target": 5})
    assert r.status_code == 200 and r.json()["id"]
    bid = r.json()["id"]
    bills = client.get("/api/world/bills").json()["bills"]
    b = next(x for x in bills if x["id"] == bid)
    assert b["target"] == 5 and b["unpause_at"] == 3   # default band ≈ 75% of target
    assert client.post(f"/api/world/bills/{bid}", json={"target": 8, "suspended": 1}).status_code == 200
    b = next(x for x in client.get("/api/world/bills").json()["bills"] if x["id"] == bid)
    assert b["target"] == 8 and b["suspended"] == 1 and b["active"] is False
    assert client.delete(f"/api/world/bills/{bid}").status_code == 200
    assert client.delete(f"/api/world/bills/{bid}").status_code == 404
    assert client.post("/api/world/bills", json={"kind": "nope", "target": 5}).status_code == 400


def test_hysteresis_pause_and_unpause(client):
    import world_bills
    conn = _conn(); c = conn.cursor()
    _clear_bills(c)
    bid = world_bills.create(c, "image", target=5, unpause_at=2)
    _set_done_images(c, 5)                     # reach target → pauses
    assert not any(b["id"] == bid for b in world_bills.active_bills(c))
    _set_done_images(c, 4)                     # inside the band → STAYS paused
    assert not any(b["id"] == bid for b in world_bills.active_bills(c))
    _set_done_images(c, 2)                     # at unpause point → filling again
    assert any(b["id"] == bid for b in world_bills.active_bills(c))
    _clear_bills(c); c.execute("DELETE FROM generations"); conn.commit(); conn.close()


def test_scheduler_offers_produce_for_active_bill(client):
    import world_bills
    import world_work
    conn = _conn(); c = conn.cursor()
    _clear_bills(c)
    _set_done_images(c, 0)
    world_bills.create(c, "image", target=3)
    agent = {"id": 3, "key": "test_bill_agent", "name": "Biller", "dept": "image", "level": 4}
    job = world_work.choose_work(c, agent, {"has_work": False, "t": 0})
    assert job["work_type"] == "produce" and "bill" in job["goal"]
    # min-level routing: a level-1 novice can't take a lv-3 bill
    world_bills.update(c, c.execute("SELECT id FROM world_bills").fetchone()["id"], min_level=3)
    novice = {"id": 4, "key": "test_bill_novice", "name": "Novice", "dept": "image", "level": 1}
    job = world_work.choose_work(c, novice, {"has_work": False, "t": 0})
    assert job["work_type"] != "produce"
    _clear_bills(c); c.execute("DELETE FROM generations"); conn.commit(); conn.close()


def test_drive_defaults_off(client):
    import world_bills
    conn = _conn(); c = conn.cursor()
    _clear_bills(c)
    world_bills.create(c, "image", target=3)
    _set_done_images(c, 0)
    assert world_bills.maybe_drive(c) is False   # world_bills_drive defaults to "0"
    _clear_bills(c); c.execute("DELETE FROM generations"); conn.commit(); conn.close()
