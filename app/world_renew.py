"""
The Company — RENEWAL: the community keeps itself fresh, oldest first.

Two duties, run on a slow ticker cadence:

  1. REFRESH the oldest things. The town's earliest prop sprites were made by an
     older, worse pipeline — renewal re-renders the single oldest one through
     the CURRENT pipeline (LoRA, transparency, vision review), owner credited
     with a community assist. One at a time, oldest first, all GPU guards apply.

  2. REQUEST improvements. Agents file suggestions drawn from REAL observations
     (the oldest asset, the sickest subsystem, the weakest defense, a full
     shelf) — covering feature improvements, core store systems, Company
     systems and world changes. They land in `world_suggestions` (Town Hall →
     Open suggestions) attributed to a citizen, for god + the Republic to see.
"""
import logging
import random
import threading
import time

from world_defs import mget, mset, log_town

logger = logging.getLogger("store")

RENEW_EVERY_SEC = 3 * 3600          # consider one renewal every ~3h
PROP_MIN_AGE_DAYS = 3               # a prop must be this old before a refresh
REQUEST_CHANCE = 0.5                # odds a renewal tick also files one suggestion


def _event(c, key, text):
    try:
        c.execute("INSERT INTO world_events (agent_key, kind, text) VALUES (?, 'system', ?)",
                  (key or "", text))
    except Exception:
        pass


def _refresh_oldest_prop(c):
    """Re-render the town's single oldest finished prop through today's pipeline."""
    row = c.execute(
        "SELECT id, label, owner_key, created_at FROM world_props WHERE status='done' "
        "AND created_at < datetime('now', ?) ORDER BY created_at ASC LIMIT 1",
        (f"-{PROP_MIN_AGE_DAYS} days",)).fetchone()
    if not row:
        return False
    if c.execute("SELECT 1 FROM world_props WHERE status IN ('queued','generating') LIMIT 1").fetchone():
        return False                                     # GPU lane busy — wait our turn
    c.execute("UPDATE world_props SET status='queued', created_at=datetime('now') WHERE id=?",
              (row["id"],))
    owner = row["owner_key"]
    nm = c.execute("SELECT name FROM world_agents WHERE key=?", (owner,)).fetchone()
    who = nm["name"] if nm else "The town"
    _event(c, owner, f"🔁 {who} is refreshing the town's oldest piece — the {row['label']} — "
                     f"with today's craftsmanship.")
    try:
        import world_rank
        if owner:
            world_rank.add_assist(c, owner, "renewal")   # community upkeep counts as helping
    except Exception:
        pass
    c.connection.commit() if hasattr(c, "connection") else None
    import world_build
    threading.Thread(target=world_build.generate_world_prop, args=(row["id"],), daemon=True).start()
    return True


# observation templates: (finder(c) -> text or None, category)
def _obs_oldest_design(c):
    r = c.execute("SELECT prompt, created_at FROM generations WHERE status='done' "
                  "ORDER BY created_at ASC LIMIT 1").fetchone()
    if r and r["prompt"]:
        return f"Our earliest piece (“{r['prompt'][:40]}…”) predates everything we've learned — let's remake it better."
    return None


def _obs_sick_system(c):
    try:
        import world_security
        sick = [(k, h) for k, h in world_security.scan_systems(c).items() if h.get("issues")]
        if sick:
            k, h = max(sick, key=lambda kv: kv[1]["issues"])
            return f"The {k} subsystem keeps failing ({h['issues']} issue(s)) — it needs a proper fix, not patches."
    except Exception:
        pass
    return None


def _obs_defense(c):
    try:
        import world_raid
        r = world_raid.readiness(c)
        if r < 45:
            return f"Our raid readiness is only {int(r)}% — we should drill, and build another watchtower."
    except Exception:
        pass
    return None


def _obs_world(c):
    pool = [
        "The wilds are getting busier — a hunting lodge would turn the deer into food for the shop.",
        "The shop catalog hasn't grown in a while — new goods would give our coins somewhere to go.",
        "Our oldest houses deserve an upgrade pass — the newest ones are far nicer inside.",
        "The library should index our newest work — the archives drift out of date.",
    ]
    return random.choice(pool)


def _file_request(c):
    """One agent turns a real observation into an open suggestion."""
    finders = [(_obs_sick_system, "store"), (_obs_defense, "company"),
               (_obs_oldest_design, "store"), (_obs_world, "world")]
    random.shuffle(finders)
    for fn, cat in finders:
        text = fn(c)
        if not text:
            continue
        if c.execute("SELECT 1 FROM world_suggestions WHERE status='open' AND text=?",
                     (text,)).fetchone():
            continue                                     # already on the board
        ag = c.execute("SELECT key, name FROM world_agents WHERE kind IN ('worker','openclaw') "
                       "ORDER BY RANDOM() LIMIT 1").fetchone()
        if not ag:
            return False
        c.execute("INSERT INTO world_suggestions (agent_key, text, category, votes, status) "
                  "VALUES (?,?,?,1,'open')", (ag["key"], text, cat))
        _event(c, ag["key"], f"📝 {ag['name']} filed an improvement request: {text}")
        return True
    return False


def tick(conn):
    """Called by the world ticker. One renewal action + maybe one request."""
    c = conn.cursor()
    last = float(mget(c, "last_renew", 0) or 0)
    if time.time() - last < RENEW_EVERY_SEC:
        return
    mset(c, "last_renew", time.time())
    did = _refresh_oldest_prop(c)
    if random.random() < REQUEST_CHANCE:
        _file_request(c)
    conn.commit()
    if did:
        log_town("RENEWAL: oldest prop sent back to the workshop.")
