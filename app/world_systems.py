"""
The Company — periodic systems (achievements, incidents, housekeeping).

Data-driven: the *content* (which milestones exist, which incidents can happen)
lives in world_balance; this module only evaluates it. Called from the background
ticker (world_ticker) on their own cadences. Adding a milestone or incident means
appending a dict in world_balance — no change here.
"""
import random, json

from world_defs import DEPARTMENTS, log_town, mget, mset
from world_balance import ACHIEVEMENTS, INCIDENTS, EVENTS_RETENTION


def company_summary(c):
    """Aggregate stats used by achievement checks and the API 'company' block."""
    ags = [dict(r) for r in c.execute("SELECT * FROM world_agents").fetchall()]
    pop = len(ags)
    def _n(sql, d=0):
        try: return c.execute(sql).fetchone()[0]
        except Exception: return d
    upgrades = 0
    for a in ags:
        try: upgrades += len(json.loads(a["upgrades"] or "[]"))
        except Exception: pass
    thriving = sum(1 for a in ags if (a["mood_label"] or "") == "thriving")
    return {
        "pop": pop,
        "total_jobs":  sum(a["jobs_done"] or 0 for a in ags),
        "treasury":    sum(a["coins"] or 0 for a in ags),
        "total_debt":  sum(a["debt"] or 0 for a in ags),
        "company_fund": int(float(mget(c, "company_fund", 0) or 0)),
        "max_level":   max((a["level"] or 1 for a in ags), default=1),
        "thriving":    thriving,
        "upgrades":    upgrades,
        "props_done":  _n("SELECT COUNT(*) FROM world_props WHERE status='done'"),
        "meetings":    _n("SELECT COUNT(*) FROM world_meetings"),
    }


def check_achievements(conn):
    """Evaluate the milestone registry; award any newly-satisfied ones."""
    c = conn.cursor()
    earned = {r["id"] for r in c.execute("SELECT id FROM world_achievements").fetchall()}
    s = company_summary(c)
    newly = []
    for a in ACHIEVEMENTS:
        if a["id"] in earned:
            continue
        try:
            if a["check"](s):
                c.execute("INSERT OR IGNORE INTO world_achievements (id,label) VALUES (?,?)",
                          (a["id"], a["label"]))
                c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
                          (None, "achievement", f"🏆 Achievement unlocked — {a['label']}: {a['desc']}"))
                log_town(f"ACHIEVEMENT: {a['label']} — {a['desc']}")
                newly.append(a["id"])
        except Exception:
            pass
    if newly:
        conn.commit()
    return newly


def fire_incident(conn):
    """Apply one random incident's effects to the world (data-driven)."""
    inc = random.choice(INCIDENTS)
    c = conn.cursor()
    for eff in inc.get("effects", []):
        scope = eff.get("scope", "all")
        where, params = "", []
        if scope != "all":
            # scope is a department key
            where = "WHERE dept=?"
            params = [scope]
        if "need" in eff:
            col = eff["need"]
            c.execute(f"UPDATE world_agents SET {col}=MAX(0,MIN(100,COALESCE({col},0)+?)) {where}",
                      [eff["delta"], *params])
        elif "coins" in eff:
            c.execute(f"UPDATE world_agents SET coins=MAX(0,COALESCE(coins,0)+?) {where}",
                      [eff["coins"], *params])
    c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
              (None, "incident", inc["text"]))
    log_town(f"INCIDENT: {inc['text']}")
    conn.commit()
    return inc["id"]


def prune_events(conn):
    """Keep world_events bounded (retention from balance)."""
    c = conn.cursor()
    c.execute("DELETE FROM world_events WHERE id NOT IN "
              "(SELECT id FROM world_events ORDER BY id DESC LIMIT ?)", (EVENTS_RETENTION,))
    conn.commit()
