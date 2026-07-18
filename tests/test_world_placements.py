"""The play-god movable-placement editor — /api/world/placement/move."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def _seed_placement(key="test_mover"):
    from deps import get_conn
    import world_items
    conn = get_conn()
    c = conn.cursor()
    world_items.ensure(c)
    c.execute("INSERT OR IGNORE INTO world_placements (agent_key,item,spot,slot) VALUES (?,?,?,?)",
              (key, "flower_pot" if "flower_pot" in world_items.CATALOG else next(iter(world_items.CATALOG)), "house", 0))
    conn.commit()
    conn.close()
    return key


def test_move_and_reset_placement(client):
    key = _seed_placement()
    r = client.post("/api/world/placement/move",
                    json={"agent_key": key, "spot": "house", "slot": 0, "ox": 123.5, "oy": 456.0})
    assert r.status_code == 200 and r.json()["ok"]
    from deps import get_conn
    conn = get_conn()
    row = conn.execute("SELECT ox, oy FROM world_placements WHERE agent_key=? AND spot='house' AND slot=0",
                       (key,)).fetchone()
    assert (row["ox"], row["oy"]) == (123.5, 456.0)
    # ox/oy null resets the pin back to the default slot position
    r = client.post("/api/world/placement/move",
                    json={"agent_key": key, "spot": "house", "slot": 0, "ox": None, "oy": None})
    assert r.status_code == 200
    row = conn.execute("SELECT ox, oy FROM world_placements WHERE agent_key=? AND spot='house' AND slot=0",
                       (key,)).fetchone()
    assert row["ox"] is None and row["oy"] is None
    conn.close()


def test_move_placement_validation(client):
    # unknown placement → 404
    r = client.post("/api/world/placement/move",
                    json={"agent_key": "nobody", "spot": "yard", "slot": 9, "ox": 1, "oy": 2})
    assert r.status_code == 404
    # bad spot / missing slot / half a coordinate → 400
    assert client.post("/api/world/placement/move",
                       json={"agent_key": "x", "spot": "roof", "slot": 0}).status_code == 400
    assert client.post("/api/world/placement/move",
                       json={"agent_key": "x", "spot": "house"}).status_code == 400
    assert client.post("/api/world/placement/move",
                       json={"agent_key": "x", "spot": "house", "slot": 0, "ox": 5}).status_code == 400
