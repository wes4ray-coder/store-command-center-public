"""
The Company — the LEADERBOARD (competition makes them better).

Ranks every citizen across the things the town actually does, from data the
systems already record — no new bookkeeping. Categories cover the user's list:
highest skills, most stuff, best stuff (god's taste + vision scores), fastest
(competence/merit), gathering, scholarship, combat, ideas, and real dev work.

Standings are served in /api/world/state (company.rankings) and the reigning
champions get a mood boost each time standings are computed with them on top —
being #1 FEELS good, losing the crown stings, so the crew chases the board.
"""
import logging

logger = logging.getLogger("store")

GATHER = ("woodcutting", "mining", "farming", "fishing", "construction", "hunting")


# ── assists: helping is a first-class stat (anti-selfishness pressure) ────────
# Fed by medic revives now; the GitHub friends system and construction donations
# call add_assist too as they wire in. Sum → the 🤝 Best friend crown.
def add_assist(c, agent_key, kind="help"):
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS world_assists(
            agent_key TEXT, kind TEXT, n INTEGER DEFAULT 0, UNIQUE(agent_key, kind))""")
        c.execute("INSERT INTO world_assists(agent_key,kind,n) VALUES(?,?,1) "
                  "ON CONFLICT(agent_key,kind) DO UPDATE SET n=n+1", (agent_key, kind))
        import world_mood
        world_mood.add_thought(c, agent_key, "helped a friend", 5, hours=8, unique=True)
    except Exception:
        logger.exception("add_assist failed")


def _top(c, sql, args=(), n=3, fmt=lambda v: int(v)):
    try:
        rows = c.execute(sql, args).fetchall()[:n]
        return [{"name": r[0], "value": fmt(r[1])} for r in rows if r[0]]
    except Exception:
        return []


def standings(c):
    """All category standings, top-3 each. Cheap queries over existing tables."""
    cats = []

    def add(key, emoji, label, top):
        if top:
            cats.append({"key": key, "emoji": emoji, "label": label, "top": top})

    names = {r["key"]: r["name"] for r in c.execute(
        "SELECT key, name FROM world_agents").fetchall()}
    by_key_sql = lambda sql: [{"name": names.get(r[0], r[0]), "value": int(r[1])}
                              for r in c.execute(sql).fetchall()[:3] if names.get(r[0])]

    add("level", "🏅", "Highest level",
        _top(c, "SELECT name, xp FROM world_agents WHERE kind IN ('worker','openclaw') "
                "ORDER BY xp DESC"))
    add("rich", "🪙", "Wealthiest",
        _top(c, "SELECT name, coins FROM world_agents WHERE kind IN ('worker','openclaw') "
                "ORDER BY coins DESC"))
    add("worker", "⚙️", "Most jobs done",
        _top(c, "SELECT name, jobs_done FROM world_agents WHERE kind IN ('worker','openclaw') "
                "ORDER BY jobs_done DESC"))
    add("gatherer", "🪓", "Master gatherer", by_key_sql(
        "SELECT agent_key, SUM(xp) v FROM world_skills WHERE skill IN "
        f"({','.join(repr(s) for s in GATHER)}) GROUP BY agent_key ORDER BY v DESC"))
    add("scholar", "📖", "Top scholar", by_key_sql(
        "SELECT agent_key, xp FROM world_skills WHERE skill='knowledge' ORDER BY xp DESC"))
    add("warrior", "⚔️", "Fiercest warrior", by_key_sql(
        "SELECT agent_key, xp FROM world_skills WHERE skill='attack' ORDER BY xp DESC"))
    add("guardian", "🛡️", "Stoutest guardian", by_key_sql(
        "SELECT agent_key, xp FROM world_skills WHERE skill='defense' ORDER BY xp DESC"))
    # BEST stuff — god's learned taste on their creations + the vision reviewer
    add("tastemaker", "🎨", "God's favourite artist",
        _top(c, "SELECT agent_name, ROUND(AVG(taste)*100) FROM world_prayers "
                "WHERE agent_name IS NOT NULL AND taste IS NOT NULL "
                "GROUP BY agent_name HAVING COUNT(*) >= 2 ORDER BY AVG(taste) DESC"))
    add("craftsman", "✨", "Finest craftsman", by_key_sql(
        "SELECT owner_key, ROUND(AVG(score),1) FROM world_props "
        "WHERE owner_key IS NOT NULL AND score IS NOT NULL "
        "GROUP BY owner_key ORDER BY AVG(score) DESC"))
    # ideas — Republic strategy proposals authored
    add("visionary", "💡", "Boldest ideas",
        _top(c, "SELECT proposer, COUNT(*) FROM world_strategies "
                "WHERE proposer IS NOT NULL GROUP BY proposer ORDER BY COUNT(*) DESC"))
    # fastest / merit — the learning system's competence measure
    try:
        import world_learn
        comps = []
        for r in c.execute("SELECT * FROM world_agents WHERE kind IN ('worker','openclaw')").fetchall():
            comps.append((r["name"], round(world_learn.competence(c, dict(r)), 2)))
        comps.sort(key=lambda t: -t[1])
        add("fastest", "⚡", "Sharpest operator",
            [{"name": n, "value": v} for n, v in comps[:3]])
    except Exception:
        pass
    # real DEV work — succeeded OpenClaw task runs per bound agent
    try:
        from world_defs import OPENCLAW_DB
        import sqlite3 as _sq
        if OPENCLAW_DB.exists():
            oc = _sq.connect(f"file:{OPENCLAW_DB}?mode=ro&immutable=1", uri=True, timeout=2)
            runs = {r[0]: r[1] for r in oc.execute(
                "SELECT agent_id, COUNT(*) FROM task_runs WHERE status='succeeded' "
                "GROUP BY agent_id").fetchall()}
            oc.close()
            rows = [(r["name"], runs.get(r["job_class"], 0)) for r in c.execute(
                "SELECT name, job_class FROM world_agents WHERE kind='openclaw'").fetchall()]
            rows = sorted([t for t in rows if t[1] > 0], key=lambda t: -t[1])
            add("coder", "💻", "Top coder",
                [{"name": n, "value": v} for n, v in rows[:3]])
    except Exception:
        pass
    # helping — assists across revives, donations, dev unblocks
    try:
        add("friend", "🤝", "Best friend", by_key_sql(
            "SELECT agent_key, SUM(n) v FROM world_assists GROUP BY agent_key ORDER BY v DESC"))
    except Exception:
        pass
    # raid kill board (current/last raid)
    try:
        import json as _json
        from world_defs import mget
        kills = sorted(_json.loads(mget(c, "raid_kills", "{}") or "{}").items(),
                       key=lambda kv: -kv[1])
        add("slayer", "🗡️", "Raid slayer",
            [{"name": k, "value": v} for k, v in kills[:3]])
    except Exception:
        pass
    return cats


def crown_champions(c):
    """Give each category's #1 a mood boost (called on a slow cadence by the
    ticker) — holding a crown feels good, which makes the crew defend it."""
    try:
        import world_mood
        for cat in standings(c):
            top = cat["top"][0]["name"] if cat["top"] else None
            key = next((r["key"] for r in c.execute(
                "SELECT key, name FROM world_agents WHERE name=?", (top,)).fetchall()), None)
            if key:
                world_mood.add_thought(c, key, f"reigning {cat['label'].lower()}", 3,
                                       hours=6, unique=True)
    except Exception:
        logger.exception("crown_champions failed")
