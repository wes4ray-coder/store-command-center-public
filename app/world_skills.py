"""THE COMPANY — RuneScape-style skills (system A, the foundation).

Idle agents don't just wander: they train a GATHERING skill at a resource node,
earning skill-XP + resources into the company stockpile (personal coins still
require REAL completed work — the economy invariant holds). Combat skills
(attack/defense/knowledge) live here too but are trained by the raid/library
systems built later. Data-driven; every helper degrades gracefully.

Storage: table `world_skills(agent_key, skill, xp)`; the company stockpile is a
JSON blob in `world_meta.stockpile`.
"""
import json
import random

from world_defs import mget, mset
from world_balance import KNOWLEDGE_WAGE_FACTOR

# gathering/craft skills (idle labour) + combat/scholarly (raid & library)
GATHER = ["woodcutting", "mining", "farming", "fishing", "construction", "hunting"]
COMBAT = ["attack", "defense", "knowledge"]
ALL_SKILLS = GATHER + COMBAT

# gathering skill → (node location key, action phrase, resource, emoji)
SKILL_META = {
    "woodcutting":  ("woodcut", "chopping wood",  "logs",   "🪓"),
    "mining":       ("mine",    "mining ore",     "ore",    "⛏️"),
    "farming":      ("farm",    "tending crops",  "crops",  "🌾"),
    "fishing":      ("fish",    "fishing",        "fish",   "🎣"),
    "construction": ("build",   "hammering away", "planks", "🔨"),
    "hunting":      ("hunt",    "stalking game",  "venison", "🏹"),   # the wilds feed the shop
}

NODE_SKILL = {v[0]: k for k, v in SKILL_META.items()}   # node location key → skill (reverse map)

SECONDS_PER_RESOURCE = 42.0     # avg real-time per unit gathered
XP_PER_RESOURCE      = 12
XP_BASE_PER_TICK     = 2        # small trickle so leveling always creeps forward


# ── xp ↔ level (gentle curve; level N needs ~ (N-1)^2 * 80 xp) ──
def level_of(xp):
    return 1 + int((max(0, int(xp or 0)) / 80.0) ** 0.5)


def xp_for_level(lvl):
    return int(((max(1, lvl) - 1) ** 2) * 80)


# stable per-agent specialisation (so identities read: "Ada the miner")
def primary_skill(agent):
    key = str(agent.get("key") or agent.get("name") or "")
    h = sum(ord(ch) for ch in key) if key else 0
    return GATHER[h % len(GATHER)]


# ── db ──
def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS world_skills(
        agent_key TEXT, skill TEXT, xp INTEGER DEFAULT 0,
        PRIMARY KEY(agent_key, skill))""")


def get_xp(c, key, skill):
    _ensure(c)
    r = c.execute("SELECT xp FROM world_skills WHERE agent_key=? AND skill=?", (key, skill)).fetchone()
    return int(r[0]) if r else 0


def add_xp(c, key, skill, amount):
    _ensure(c)
    amt = int(round(amount))
    if amt <= 0:
        return
    c.execute("""INSERT INTO world_skills(agent_key, skill, xp) VALUES(?,?,?)
        ON CONFLICT(agent_key, skill) DO UPDATE SET xp = xp + ?""", (key, skill, amt, amt))


def skills_for(c, key):
    """{skill: {'xp':int,'level':int}} for one agent."""
    _ensure(c)
    rows = c.execute("SELECT skill, xp FROM world_skills WHERE agent_key=?", (key,)).fetchall()
    return {r[0]: {"xp": int(r[1]), "level": level_of(int(r[1]))} for r in rows}


def total_level(c, key):
    return sum(v["level"] for v in skills_for(c, key).values()) or len(ALL_SKILLS)


# ── company stockpile (world_meta JSON) ──
def stockpile(c):
    try:
        return json.loads(mget(c, "stockpile", "{}") or "{}")
    except Exception:
        return {}


def _season_mult(c, skill):
    """Seasonal productivity multiplier for a gathering skill (orchestrator → meta)."""
    try:
        return float(json.loads(mget(c, "season_bonus", "{}") or "{}").get(skill, 1.0))
    except Exception:
        return 1.0


def _tech_mult(c):
    """Company tech-tier tooling bonus (world_tech → meta)."""
    try:
        return float(mget(c, "tech_bonus", 1.0) or 1.0)
    except Exception:
        return 1.0


def add_resource(c, resource, n):
    sp = stockpile(c)
    sp[resource] = int(sp.get(resource, 0)) + int(n)
    mset(c, "stockpile", json.dumps(sp))
    return sp


# ── stockpile targets (Colony-Manager style: keep floor..ceil of each resource) ──
def _ensure_targets(c):
    c.execute("CREATE TABLE IF NOT EXISTS world_stock_targets(resource TEXT PRIMARY KEY, floor INTEGER, ceil INTEGER)")


def stock_targets(c):
    _ensure_targets(c)
    return {r[0]: {"floor": int(r[1]), "ceil": int(r[2])} for r in
            c.execute("SELECT resource, floor, ceil FROM world_stock_targets").fetchall()}


def set_stock_target(c, resource, floor, ceil):
    _ensure_targets(c)
    floor, ceil = max(0, int(floor)), max(1, int(ceil))
    c.execute("""INSERT INTO world_stock_targets(resource, floor, ceil) VALUES(?,?,?)
        ON CONFLICT(resource) DO UPDATE SET floor=?, ceil=?""", (resource, floor, ceil, floor, ceil))


def resource_of(skill):
    m = SKILL_META.get(skill)
    return m[2] if m else None


def can_afford(c, cost):
    sp = stockpile(c)
    return all(int(sp.get(r, 0)) >= n for r, n in (cost or {}).items())


def spend(c, cost):
    """Deduct a {resource: n} cost from the stockpile if affordable. Returns True on success."""
    sp = stockpile(c)
    if not all(int(sp.get(r, 0)) >= n for r, n in (cost or {}).items()):
        return False
    for r, n in cost.items():
        sp[r] = int(sp.get(r, 0)) - int(n)
    mset(c, "stockpile", json.dumps(sp))
    return True


# ── the gather tick — called from world_sim while an agent is 'skilling' ──
def gather(c, agent, skill, dt):
    """Grant time-scaled XP + occasional resource yield to the stockpile.
    Returns (xp_gained, resource_name, units) — units may be 0 on a given tick."""
    key = agent["key"]
    lvl = level_of(get_xp(c, key, skill))
    node, phrase, resource, emoji = SKILL_META.get(skill, SKILL_META["woodcutting"])
    # time-based yield with a fractional carry via probability (no per-agent state),
    # scaled by the season's productivity bias + the tech tier's tooling bonus (both in meta)
    research_mult = float(mget(c, "research_gather_mult", 1.0) or 1.0)   # research tree (Tools/Logistics/Automation) (#7)
    units_f = (dt / SECONDS_PER_RESOURCE) * (1 + lvl * 0.04) * _season_mult(c, skill) * _tech_mult(c) * research_mult
    units = int(units_f) + (1 if random.random() < (units_f - int(units_f)) else 0)
    xp = XP_BASE_PER_TICK + units * XP_PER_RESOURCE
    add_xp(c, key, skill, xp)
    if units:
        add_resource(c, resource, units)
    return xp, resource, units


# ── system B: library study raises Knowledge, which buffs real-job output ──
STUDY_XP_PER_MIN = 22


def study(c, agent, dt):
    """Train the Knowledge skill at the library. Returns (xp_gained, new_level)."""
    key = agent["key"]
    xp = max(1, int(round(STUDY_XP_PER_MIN * (dt / 60.0))))
    add_xp(c, key, "knowledge", xp)
    return xp, level_of(get_xp(c, key, "knowledge"))


def knowledge_mult(c, key):
    """Wage/XP multiplier from an agent's Knowledge level (>= 1.0)."""
    lvl = level_of(get_xp(c, key, "knowledge"))
    return 1.0 + (lvl - 1) * KNOWLEDGE_WAGE_FACTOR
