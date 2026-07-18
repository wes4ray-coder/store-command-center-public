"""THE COMPANY — the adaptive layer (system E, the honest 'learning').

True Unity ML-Agents / RL isn't feasible in this FastAPI+JS stack, but the felt
goal — the town measurably gets better over time — is real here via two online
mechanisms plus a metric:

1. PER-AGENT BANDIT: each agent runs an ε-greedy multi-armed bandit over its idle
   activities (5 gathering skills + study + leisure). It records the reward of each
   choice (XP gained, or need relief for leisure) and drifts toward what pays off —
   genuine online learning, pure Python, no model. Agents self-specialise.

2. MERIT ROUTING: real completed work is assigned to workers weighted by
   COMPETENCE (Knowledge + track record). Good workers get more work → more XP →
   higher competence: a positive feedback loop = the org learning who's best.

3. INTELLIGENCE: a collective score (total skill levels + Knowledge) that rises as
   the town learns — the observable "it's growing" number.

Storage: table world_policy(agent_key, action, value, n). Decoupled from the sim.
"""
import random

from world_defs import NEEDS
import world_skills as WS

ACTIONS = WS.GATHER + ["study", "leisure"]
EPSILON = 0.15           # exploration rate
Q_INIT = 6.0             # optimistic start so every action gets tried early


def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS world_policy(
        agent_key TEXT, action TEXT, value REAL DEFAULT 0, n INTEGER DEFAULT 0,
        PRIMARY KEY(agent_key, action))""")


def _q(c, key, action):
    r = c.execute("SELECT value, n FROM world_policy WHERE agent_key=? AND action=?", (key, action)).fetchone()
    return (float(r[0]), int(r[1])) if r else (Q_INIT, 0)


def choose_activity(c, agent):
    """ε-greedy pick over the agent's idle activities. ε is PERSONAL — each
    agent's strategy genome sets how much they experiment vs exploit."""
    _ensure(c)
    key = agent["key"]
    eps = EPSILON
    try:
        import world_genome
        eps = world_genome.genome(agent)["epsilon"]
    except Exception:
        pass
    if random.random() < eps:
        return random.choice(ACTIONS)
    best, best_v = ACTIONS[0], -1e9
    for a in ACTIONS:
        v, _n = _q(c, key, a)
        if v > best_v:
            best, best_v = a, v
    return best


def record_reward(c, key, action, reward):
    """Incremental-mean update of the action's value estimate."""
    _ensure(c)
    v, n = _q(c, key, action)
    if n == 0:
        v = 0.0                       # discard the optimistic prior on first real sample
    n += 1
    v += (float(reward) - v) / n
    c.execute("""INSERT INTO world_policy(agent_key, action, value, n) VALUES(?,?,?,?)
        ON CONFLICT(agent_key, action) DO UPDATE SET value=?, n=?""", (key, action, v, n, v, n))


def policy_for(c, key):
    """{action: {'value':.., 'n':..}} — for display."""
    _ensure(c)
    rows = c.execute("SELECT action, value, n FROM world_policy WHERE agent_key=?", (key,)).fetchall()
    return {r[0]: {"value": round(float(r[1]), 1), "n": int(r[2])} for r in rows}


# ── merit routing: competence-weighted worker pick for real work ──
def competence(c, w):
    klvl = WS.level_of(WS.get_xp(c, w["key"], "knowledge"))
    return 1.0 + 0.5 * (klvl - 1) + 0.02 * (w.get("jobs_done") or 0) + ((w.get("earn_mult") or 1.0) - 1.0)


def pick_worker(c, workers):
    if not workers:
        return None
    weights = [max(0.1, competence(c, w)) for w in workers]
    return random.choices(workers, weights=weights, k=1)[0]


# ── collective intelligence + specialist leaderboard ──
def intelligence(c):
    _ensure(c)
    try:
        rows = c.execute("SELECT skill, SUM(xp) s FROM world_skills GROUP BY skill").fetchall()
    except Exception:
        return 0
    total = 0
    for r in rows:
        total += WS.level_of(int(r[1] or 0)) * (2 if r[0] == "knowledge" else 1)
    return int(total)


def leaderboard(c):
    """Top specialist per skill: {skill: {'name':.., 'level':..}}."""
    try:
        rows = c.execute("""SELECT s.skill, s.agent_key, s.xp, a.name FROM world_skills s
            JOIN world_agents a ON a.key = s.agent_key
            WHERE s.xp > 0 ORDER BY s.skill, s.xp DESC""").fetchall()
    except Exception:
        return {}
    top = {}
    for r in rows:
        sk = r[0]
        if sk not in top:
            top[sk] = {"name": r[3], "level": WS.level_of(int(r[2]))}
    return top
