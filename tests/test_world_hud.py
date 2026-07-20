"""The game-first HUD's read aggregations — app/routers/world/hud.py.

The overlay HUD (static/js/world-hud.js) reads nearly everything from
/api/world/state; this covers the one thing it can't get there: the skills
metadata endpoint (tiles + milestone detail views). Read-only and cheap by
contract — assert shape, curve consistency with world_skills, and full skill
coverage."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def test_hud_skills_meta_shape(client):
    import world_skills as ws
    r = client.get("/api/world/hud/skills")
    assert r.status_code == 200
    j = r.json()
    # every skill present, gather + combat both covered
    keys = {s["key"] for s in j["skills"]}
    assert keys == set(ws.ALL_SKILLS)
    kinds = {s["key"]: s["kind"] for s in j["skills"]}
    for k in ws.GATHER:
        assert kinds[k] == "gather"
    for k in ws.COMBAT:
        assert kinds[k] == "combat"
    for s in j["skills"]:
        assert s["emoji"] and s["action"] and s["unlocks"]
        assert s["milestones"][0] == {"level": 1, "xp": 0}
        # milestone thresholds must match the real xp curve (the JS fallback
        # mirrors this formula — the endpoint is the source of truth)
        for m in s["milestones"]:
            assert m["xp"] == ws.xp_for_level(m["level"])
        if s["kind"] == "gather":
            assert s["resource"] == ws.SKILL_META[s["key"]][2]
    assert j["curve"]["base"] == 80
    assert j["tech"] is None or "ladder" in j["tech"]
