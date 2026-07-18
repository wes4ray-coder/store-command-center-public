"""THE COMPANY — Work-Priority scheduler (RimWorld-style).

The town is run by POLICY, not micro-management. Each agent has a priority for
every WORK TYPE (0 = never, 1 = highest … 4 = lowest). When an agent is free it
scans work types in priority order and takes the FIRST one that has an available
job right now — real department work, construction, research, or a gathering
skill, else it relaxes. This replaces the opaque `world_learn` bandit with a
player-legible control surface (the bandit survives as the optional "Auto" policy).

Columns are ordered left→right by default importance; the priority NUMBER dominates,
column order only breaks ties (RimWorld §2.3). Storage: world_work_priority.
"""
from world_defs import mget
import world_skills as WS
import world_tech as WT
import world_construct as WC

# work types in default left→right importance order
WORK_TYPES = ["operate", "produce", "build", "research", "mine", "woodcut", "farm", "fish", "relax"]
WT_META = {
    "operate":  {"label": "Operate",   "icon": "💼", "skill": None},          # run their department's real job
    "produce":  {"label": "Produce",    "icon": "🏭", "skill": None},          # fill open production BILLS (world_bills)
    "build":    {"label": "Construct",  "icon": "🔨", "skill": "construction"},
    "research": {"label": "Research",   "icon": "📖", "skill": "knowledge"},
    "mine":     {"label": "Mine",       "icon": "⛏️", "skill": "mining"},
    "woodcut":  {"label": "Woodcut",    "icon": "🪓", "skill": "woodcutting"},
    "farm":     {"label": "Farm",       "icon": "🌾", "skill": "farming"},
    "fish":     {"label": "Fish",       "icon": "🎣", "skill": "fishing"},
    "relax":    {"label": "Relax",      "icon": "🍺", "skill": None},
}
GATHER_WT = {"mine": "mine", "woodcut": "woodcut", "farm": "farm", "fish": "fish"}
LEISURE = ["bar", "arcade", "tv", "park", "cafe"]


def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS world_work_priority(
        agent_key TEXT, work_type TEXT, priority INTEGER,
        PRIMARY KEY(agent_key, work_type))""")


# ── default priorities: real work first, then the agent's primary skill, then chores ──
def default_priority(agent, wt):
    if wt == "operate":
        return 1
    if wt == "produce":
        return 2
    if wt == "research":
        return 3
    if wt == "build":
        return 3
    if wt == "relax":
        return 4
    # gathering skills: the agent's primary gets 2, the rest 3
    sk = WT_META[wt]["skill"]
    return 2 if (sk and sk == WS.primary_skill(agent)) else 3


def get_priorities(c, agent):
    _ensure(c)
    stored = {r[0]: int(r[1]) for r in c.execute(
        "SELECT work_type, priority FROM world_work_priority WHERE agent_key=?", (agent["key"],)).fetchall()}
    return {wt: stored.get(wt, default_priority(agent, wt)) for wt in WORK_TYPES}


def set_priority(c, agent_key, work_type, priority):
    _ensure(c)
    priority = max(0, min(4, int(priority)))
    if work_type not in WORK_TYPES:
        return
    c.execute("""INSERT INTO world_work_priority(agent_key, work_type, priority) VALUES(?,?,?)
        ON CONFLICT(agent_key, work_type) DO UPDATE SET priority=?""", (agent_key, work_type, priority, priority))


# ── WorkGivers: is there an available job of this type for this agent, right now? ──
def _wg_operate(c, agent, ctx):
    if ctx.get("has_work"):
        dept = agent.get("dept") or "trends"
        return {"work_type": "operate", "state": "working", "location": f"desk:{dept}", "goal": "on the clock", "skill": None}
    return None


def _wg_produce(c, agent, ctx):
    """Fill an open production bill (world_bills): agents work their dept desk
    while stock is below target. Also gives bills their (toggled, throttled)
    chance to kick a REAL world_auto creation."""
    try:
        import world_bills
        bill = world_bills.job_for(c, agent)
        if not bill:
            return None
        world_bills.maybe_drive(c, ctx.get("t"))
        dept = world_bills.KINDS[bill["kind"]]["dept"]
        return {"work_type": "produce", "state": "working", "location": f"desk:{dept}",
                "goal": f"filling the bill: {bill['label']} ({bill['count']}/{bill['target']})",
                "skill": None}
    except Exception:
        return None


def _wg_build(c, agent, ctx):
    try:
        if WC.has_work(c):
            snap = WC.snapshot(c)
            cur = snap.get("current")
            n = snap.get("in_flight", 0)
            goal = (f"working the {cur['name']}" if cur else "on the build site") + (f" (+{n-1} more)" if n > 1 else "")
            return {"work_type": "build", "state": "skilling", "location": "build", "goal": goal, "skill": "construction"}
    except Exception:
        pass
    return None


def _wg_research(c, agent, ctx):
    try:
        if WT.tier_index(c) < len(WT.TIERS) - 1:               # tech not maxed → research pays
            return {"work_type": "research", "state": "studying", "location": "library", "goal": "researching at the library", "skill": "knowledge"}
    except Exception:
        pass
    return None


def _wg_gather(wt):
    skill = WT_META[wt]["skill"]
    node, phrase, _res, _emoji = WS.SKILL_META[skill]
    def giver(c, agent, ctx):
        return {"work_type": wt, "state": "skilling", "location": node, "goal": phrase, "skill": skill}
    return giver


def _wg_relax(c, agent, ctx):
    spot = LEISURE[(agent["id"] + int(ctx.get("t", 0) / 45)) % len(LEISURE)]
    return {"work_type": "relax", "state": "leisure", "location": spot, "goal": "taking a break in town", "skill": None}


WORKGIVERS = {
    "operate": _wg_operate, "produce": _wg_produce, "build": _wg_build, "research": _wg_research,
    "mine": _wg_gather("mine"), "woodcut": _wg_gather("woodcut"),
    "farm": _wg_gather("farm"), "fish": _wg_gather("fish"), "relax": _wg_relax,
}


# ── the scheduler: first available job in priority order (number dominates, column breaks ties) ──
# Gather work is STOCK-AWARE (Colony-Manager style): a resource below its floor becomes
# urgent (effective priority 1); at/above its ceiling that gather is skipped (stop hoarding).
def choose_work(c, agent, ctx):
    prio = get_priorities(c, agent)
    sp = WS.stockpile(c)
    targets = WS.stock_targets(c)

    def eff(wt):
        p = prio.get(wt, 0)
        if p == 0:
            return None
        sk = WT_META[wt]["skill"]
        if wt in GATHER_WT and sk:
            res = WS.resource_of(sk)
            t = targets.get(res) if res else None
            if t:
                have = int(sp.get(res, 0))
                if have >= t["ceil"]:
                    return None                                # stock full → don't gather this
                if have < t["floor"]:
                    return 1                                   # stock low → urgent
        return p

    order = sorted((wt for wt in WORK_TYPES if eff(wt) is not None),
                   key=lambda wt: (eff(wt), WORK_TYPES.index(wt)))
    for wt in order:
        job = WORKGIVERS[wt](c, agent, ctx)
        if job:
            return job
    return _wg_relax(c, agent, ctx)                             # nothing enabled/available → relax
