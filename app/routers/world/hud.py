"""The Company — HUD read aggregations (game-first overlay panels).

Thin, read-only, no LLM calls. The overlay HUD (static/js/world-hud.js) reads
almost everything from the existing 3s ``/api/world/state`` poll; this module
only serves what that snapshot does NOT carry: the skill METADATA the
RuneScape-style skills panel needs to draw tiles and tier/milestone detail
views (xp curve, per-skill unlock notes, the tech ladder mapping). The
frontend ships a built-in fallback for all of it, so an old backend (before a
restart picks this file up) just degrades to the fallback copy.
"""
import world_skills
import world_tech
from world_balance import KNOWLEDGE_WAGE_FACTOR
from deps import get_conn
from ._base import router

# combat/scholarly skills have no SKILL_META row — their HUD meta lives here.
_COMBAT_META = {
    "attack":    {"emoji": "⚔️", "action": "raid combat & drills",
                  "unlocks": "Hits harder in raids — duel damage scales with Attack level."},
    "defense":   {"emoji": "🛡️", "action": "holding the walls",
                  "unlocks": "Takes less damage defending — trained by raids and 🛡️ drills."},
    "knowledge": {"emoji": "📖", "action": "studying at the library",
                  "unlocks": f"+{int(KNOWLEDGE_WAGE_FACTOR * 100)}% wage & XP on real work "
                             "per level, and study feeds the company research tree."},
}
_MILESTONE_LEVELS = (1, 5, 10, 15, 20, 30, 40, 50)


@router.get("/api/world/hud/skills")
def hud_skills_meta():
    """Skill metadata for the HUD skills panel: every skill's icon/action/yield,
    the xp→level curve, level milestones, and the tech-tier ladder (better tools
    per tier = the closest thing to a gathering 'skill tree')."""
    conn = get_conn()
    try:
        tech = world_tech.snapshot(conn.cursor())
    except Exception:
        tech = None
    finally:
        conn.close()

    skills = []
    for k in world_skills.ALL_SKILLS:
        gather = k in world_skills.GATHER
        s = {"key": k, "kind": "gather" if gather else "combat"}
        if gather:
            node, action, resource, emoji = world_skills.SKILL_META[k]
            s.update({
                "node": node, "action": action, "resource": resource, "emoji": emoji,
                "unlocks": f"+4% {resource} yield per level (stacks with season, "
                           "tech tier & research bonuses).",
            })
        else:
            m = _COMBAT_META[k]
            s.update({"node": None, "resource": None, **m})
        s["milestones"] = [{"level": lv, "xp": world_skills.xp_for_level(lv)}
                           for lv in _MILESTONE_LEVELS]
        skills.append(s)

    return {
        "skills": skills,
        "curve": {"base": 80},                       # level N needs (N-1)^2 * base xp
        "xp_per_resource": world_skills.XP_PER_RESOURCE,
        "seconds_per_resource": world_skills.SECONDS_PER_RESOURCE,
        "knowledge_wage_factor": KNOWLEDGE_WAGE_FACTOR,
        "tech": tech,                                # material ladder = gathering tool tiers
    }
