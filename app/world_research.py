"""THE COMPANY — research TREE with prerequisites (RimWorld #7).

On top of the linear material ladder (world_tech), the player picks RESEARCH
PROJECTS to pursue. Each project has prerequisites, an RP cost, and a real
company-wide EFFECT. Study points flow into the ACTIVE project until it's done,
then it's banked and the player chooses the next unlocked project.

Effects are applied through mirror values in world_meta (like world_tech's
tech_bonus) so the consumers (gather yield, mood, pay, raid walls, research speed)
just read a number — no cross-imports. Decoupled; degrades gracefully.
State: research_done (json list), research_active (key), research_prog (float),
+ the mirror keys.
"""
import json
from world_defs import mget, mset, log_town

# key, name, icon, rp cost, prerequisites (all must be done), effect blurb, mirror (meta key, bonus)
PROJECTS = [
    {"key": "tools",      "name": "Power Tools",      "icon": "⛏️", "rp": 120, "req": [],
     "effect": "+12% gather yield",   "mirror": ("research_gather_mult", 0.12)},
    {"key": "wellness",   "name": "Wellness Program", "icon": "🧘", "rp": 150, "req": [],
     "effect": "+6 baseline mood",    "mirror": ("research_mood_bonus", 6)},
    {"key": "marketing",  "name": "Marketing Push",   "icon": "📣", "rp": 170, "req": [],
     "effect": "+15% earnings",       "mirror": ("research_pay_mult", 0.15)},
    {"key": "logistics",  "name": "Logistics",        "icon": "📦", "rp": 240, "req": ["tools"],
     "effect": "+18% gather yield",   "mirror": ("research_gather_mult", 0.18)},
    {"key": "security",   "name": "Security Systems", "icon": "🛡️", "rp": 260, "req": ["tools"],
     "effect": "+25% wall strength",  "mirror": ("research_wall_bonus", 0.25)},
    {"key": "automation", "name": "Automation",       "icon": "🤖", "rp": 360, "req": ["logistics"],
     "effect": "+24% gather yield",   "mirror": ("research_gather_mult", 0.24)},
    {"key": "analytics",  "name": "Analytics Suite",  "icon": "📈", "rp": 300, "req": ["marketing"],
     "effect": "+22% earnings",       "mirror": ("research_pay_mult", 0.22)},
    {"key": "rnd",        "name": "R&D Division",     "icon": "🔬", "rp": 480, "req": ["automation", "analytics"],
     "effect": "+25% research speed", "mirror": ("research_speed_mult", 0.25)},
]
_BY = {p["key"]: p for p in PROJECTS}
_MIRRORS = ("research_gather_mult", "research_mood_bonus", "research_pay_mult",
            "research_wall_bonus", "research_speed_mult")


def done_list(c):
    try:
        return json.loads(mget(c, "research_done", "[]") or "[]")
    except Exception:
        return []


def is_done(c, key):
    return key in done_list(c)


def _recompute(c):
    """Refresh the mirror meta values from the completed projects (later upgrades win)."""
    done = set(done_list(c))
    best = {}
    for p in PROJECTS:
        if p["key"] in done and p.get("mirror"):
            mk, mv = p["mirror"]
            best[mk] = max(best.get(mk, 0.0), mv)
    mset(c, "research_gather_mult", round(1.0 + best.get("research_gather_mult", 0.0), 3))
    mset(c, "research_mood_bonus", best.get("research_mood_bonus", 0.0))
    mset(c, "research_pay_mult", round(1.0 + best.get("research_pay_mult", 0.0), 3))
    mset(c, "research_wall_bonus", round(best.get("research_wall_bonus", 0.0), 3))
    mset(c, "research_speed_mult", round(1.0 + best.get("research_speed_mult", 0.0), 3))


def _prereqs_met(c, key):
    p = _BY.get(key)
    return bool(p) and all(is_done(c, r) for r in p["req"])


def available(c):
    """Projects whose prereqs are done and that aren't done yet."""
    return [p["key"] for p in PROJECTS if not is_done(c, p["key"]) and _prereqs_met(c, p["key"])]


def set_active(c, key):
    """Player picks the next project to research. Returns True if accepted."""
    if key not in _BY or is_done(c, key) or not _prereqs_met(c, key):
        return False
    mset(c, "research_active", key)
    mset(c, "research_prog", 0.0)
    return True


def _event(c, kind, text):
    try:
        c.execute("INSERT INTO world_events (agent_key, kind, text) VALUES (?,?,?)", ("", kind, text))
    except Exception:
        pass


def tick_research(c, rp):
    """Feed study points into the active project (sped up by R&D). Completes + banks it."""
    if rp <= 0:
        return
    rp *= float(mget(c, "research_speed_mult", 1.0) or 1.0)
    active = mget(c, "research_active", "") or ""
    if not active or active not in _BY:
        # nothing selected → auto-pick the cheapest available so research never stalls
        avail = available(c)
        if not avail:
            return
        active = min(avail, key=lambda k: _BY[k]["rp"])
        mset(c, "research_active", active)
        mset(c, "research_prog", 0.0)
    prog = float(mget(c, "research_prog", 0.0) or 0.0) + rp
    spec = _BY[active]
    if prog >= spec["rp"]:
        done = done_list(c)
        if active not in done:
            done.append(active)
        mset(c, "research_done", json.dumps(done))
        mset(c, "research_active", "")
        mset(c, "research_prog", 0.0)
        _recompute(c)
        _event(c, "tech", f"🔬 Researched {spec['icon']} {spec['name']} — {spec['effect']}.")
        log_town(f"RESEARCH: {spec['name']} complete — {spec['effect']}.")
    else:
        mset(c, "research_prog", prog)


def snapshot(c):
    # seed the mirror values once if absent — but never rewrite them on a read.
    # snapshot() sits on /api/world/state (polled every 3s per viewer); writing
    # here made a hot READ path contend with the ticker for the write lock.
    # tick_research already recomputes whenever a project completes.
    if mget(c, "research_gather_mult", None) is None:
        _recompute(c)
    done = set(done_list(c))
    active = mget(c, "research_active", "") or ""
    prog = float(mget(c, "research_prog", 0.0) or 0.0)
    projects = []
    for p in PROJECTS:
        status = ("done" if p["key"] in done else
                  "active" if p["key"] == active else
                  "available" if _prereqs_met(c, p["key"]) else "locked")
        projects.append({"key": p["key"], "name": p["name"], "icon": p["icon"], "rp": p["rp"],
                         "req": p["req"], "effect": p["effect"], "status": status,
                         "pct": int(prog / p["rp"] * 100) if p["key"] == active else (100 if p["key"] in done else 0)})
    return {"projects": projects, "active": active, "done": sorted(done),
            "speed": float(mget(c, "research_speed_mult", 1.0) or 1.0)}
