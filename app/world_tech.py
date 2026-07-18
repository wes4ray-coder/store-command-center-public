"""THE COMPANY — materials & research tiers (Phase-2 chunk 4).

The town advances up a material ladder — wood → stone → bronze → iron → steel —
and can only work the tier it has unlocked. Unlocking the next tier takes RESEARCH
(earned by agents studying Knowledge at the Library + dev-lab work) PLUS a real
resource cost from the company stockpile. When both are met the breakthrough is
"pushed to the repo" (a GitHub research milestone) and the tier advances, granting
a company-wide efficiency bonus (better tools = higher gather yield).

State in world_meta: tech_tier (index), research_points, tech_bonus (mirror for
world_skills.gather to read, like season_bonus). Decoupled; degrades gracefully.
"""
from world_defs import mget, mset, log_town
import world_skills as WS

# the ladder; each tier lists the research points + stockpile cost to REACH it.
TIERS = [
    {"key": "wood",   "name": "Wood",   "emoji": "🪵", "rp": 0,   "cost": {}},
    {"key": "stone",  "name": "Stone",  "emoji": "🪨", "rp": 80,  "cost": {"logs": 40}},
    {"key": "bronze", "name": "Bronze", "emoji": "🥉", "rp": 220, "cost": {"logs": 60, "ore": 40}},
    {"key": "iron",   "name": "Iron",   "emoji": "⚙️", "rp": 450, "cost": {"ore": 100, "planks": 40}},
    {"key": "steel",  "name": "Steel",  "emoji": "🔩", "rp": 800, "cost": {"ore": 180, "logs": 80}},
]
BONUS_PER_TIER = 0.06           # +6% gather yield per tier unlocked


def tier_index(c):
    return max(0, min(len(TIERS) - 1, int(float(mget(c, "tech_tier", 0) or 0))))


def research_points(c):
    return int(float(mget(c, "research_points", 0) or 0))


def add_research(c, rp):
    if rp <= 0:
        return
    mset(c, "research_points", research_points(c) + int(round(rp)))


def _write_bonus(c, idx):
    mset(c, "tech_bonus", round(1.0 + idx * BONUS_PER_TIER, 3))


def tech_bonus(c):
    try:
        return float(mget(c, "tech_bonus", 1.0) or 1.0)
    except Exception:
        return 1.0


def _event(c, kind, text):
    try:
        c.execute("INSERT INTO world_events (agent_key, kind, text) VALUES (?,?,?)", ("", kind, text))
    except Exception:
        pass


def check_unlock(c):
    """Advance one tier if research + resources are both ready. Called on a cadence."""
    idx = tier_index(c)
    _write_bonus(c, idx)                            # keep the mirror fresh
    if idx >= len(TIERS) - 1:
        return None
    nxt = TIERS[idx + 1]
    if research_points(c) < nxt["rp"]:
        return None
    if not WS.spend(c, nxt["cost"]):                # need the materials too
        return None
    mset(c, "tech_tier", idx + 1)
    _write_bonus(c, idx + 1)
    cost = ", ".join(f"{n} {r}" for r, n in nxt["cost"].items()) or "no materials"
    _event(c, "tech", f"🔬 {nxt['emoji']} {nxt['name']} Age unlocked — research pushed to the repo (spent {cost}).")
    log_town(f"TECH: advanced to the {nxt['name']} Age (+{int(BONUS_PER_TIER*100*(idx+1))}% tooling).")
    return nxt["key"]


def snapshot(c):
    idx = tier_index(c)
    cur = TIERS[idx]
    nxt = TIERS[idx + 1] if idx < len(TIERS) - 1 else None
    rp = research_points(c)
    out = {
        "tier": cur["key"], "tier_name": cur["name"], "emoji": cur["emoji"], "index": idx,
        "research_points": rp, "bonus": round(1.0 + idx * BONUS_PER_TIER, 3),
        "ladder": [{"key": t["key"], "name": t["name"], "emoji": t["emoji"], "unlocked": i <= idx} for i, t in enumerate(TIERS)],
    }
    if nxt:
        sp = WS.stockpile(c)
        out["next"] = {
            "key": nxt["key"], "name": nxt["name"], "emoji": nxt["emoji"],
            "rp": nxt["rp"], "rp_pct": min(100, int(rp / max(1, nxt["rp"]) * 100)),
            "cost": nxt["cost"],
            "have": {r: int(sp.get(r, 0)) for r in nxt["cost"]},
            "ready": rp >= nxt["rp"] and WS.can_afford(c, nxt["cost"]),
        }
    return out
