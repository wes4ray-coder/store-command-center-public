"""THE COMPANY — mood as a thought-ledger + mental breaks (RimWorld-style).

Mood = a base (needs wellbeing) plus the sum of active THOUGHTS — tagged, timed
mood modifiers written by real events ("shipped a sale +6 / 1 day", "paid the
bills -5", "survived the raid +30 catharsis"). When mood drops under an agent's
break threshold it may snap into a MENTAL BREAK (sad-wander → tantrum → berserk)
that hijacks its behaviour for a while; on recovery it gets a Catharsis thought so
it doesn't immediately spiral again.

State: world_thoughts(agent_key,label,delta,expires_at) + world_agents.break_until
/break_kind. Decoupled; degrades gracefully.
"""
import time
import random

from world_defs import NEEDS

BREAK_THRESHOLD = 35            # mood below this risks a break
BREAK_MIN, BREAK_MAX = 55, 150  # break duration seconds
# tier by how low the mood is → (kind, emoji, label)
TIERS = [
    (15, "berserk", "😡", "berserk — storming off"),
    (25, "tantrum", "😤", "throwing a tantrum — refusing to work"),
    (BREAK_THRESHOLD, "sadwander", "😢", "wandering off, dejected"),
]


def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS world_thoughts(
        id INTEGER PRIMARY KEY AUTOINCREMENT, agent_key TEXT, label TEXT,
        delta REAL, expires_at REAL)""")


def add_thought(c, key, label, delta, hours=6.0, unique=False):
    """Record a mood thought. unique=True replaces an existing same-label thought."""
    _ensure(c)
    exp = time.time() + hours * 3600
    if unique:
        c.execute("DELETE FROM world_thoughts WHERE agent_key=? AND label=?", (key, label))
    c.execute("INSERT INTO world_thoughts(agent_key,label,delta,expires_at) VALUES(?,?,?,?)",
              (key, label, float(delta), exp))


def add_thought_all(c, keys, label, delta, hours=6.0):
    for k in keys:
        add_thought(c, k, label, delta, hours)


def thoughts_for(c, key):
    _ensure(c)
    now = time.time()
    return [{"label": r[0], "delta": round(float(r[1]), 1)} for r in c.execute(
        "SELECT label, delta FROM world_thoughts WHERE agent_key=? AND expires_at>? ORDER BY id DESC LIMIT 8",
        (key, now)).fetchall()]


def _thought_sum(c, key):
    _ensure(c)                     # mood_of() reaches here before any add_thought() on a fresh DB
    now = time.time()
    r = c.execute("SELECT COALESCE(SUM(delta),0) FROM world_thoughts WHERE agent_key=? AND expires_at>?",
                  (key, now)).fetchone()
    return float(r[0] or 0)


def prune(c):
    _ensure(c)
    c.execute("DELETE FROM world_thoughts WHERE expires_at < ?", (time.time(),))


def base_mood(a):
    """Wellbeing from the Sims-style needs, mapped onto a mood baseline.

    A content agent sits comfortably above the break threshold; mood only sinks
    under it through genuine deprivation + debt + a stack of negative thoughts.
    Raw needs avg ~30 → ~53 baseline, so nobody breaks just for existing.
    """
    avg = sum(a[n] or 0 for n in NEEDS) / len(NEEDS)
    base = 40 + avg * 0.45
    if (a.get("debt") or 0) > 0:
        base -= 12
    return base


def mood_of(c, a):
    from world_defs import mget
    wellness = float(mget(c, "research_mood_bonus", 0.0) or 0.0)   # research: Wellness Program (#7)
    return max(0.0, min(100.0, base_mood(a) + _thought_sum(c, a["key"]) + wellness))


# ── mental breaks ──
def is_broken(a):
    return (a.get("break_until") or 0) > time.time()


def _tier(mood):
    for thresh, kind, emoji, label in TIERS:
        if mood < thresh:
            return kind, emoji, label
    return None


def maybe_break(c, a, mood):
    """Roll for a mental break when mood is low. Returns (kind,emoji,label) if one starts."""
    if is_broken(a):
        return None
    if mood >= BREAK_THRESHOLD:
        return None
    # This rolls EVERY sim tick (~8s) per agent, so the per-tick probability must
    # stay tiny or breaks become constant. Scale by how far below threshold we are;
    # at the very bottom (mood 0) it's PER_TICK_MAX, tapering to ~0 near the line.
    PER_TICK_MAX = 0.03
    p = ((BREAK_THRESHOLD - mood) / BREAK_THRESHOLD) * PER_TICK_MAX
    if random.random() >= p:
        return None
    t = _tier(mood)
    if not t:
        return None
    kind, emoji, label = t
    a["break_until"] = time.time() + random.uniform(BREAK_MIN, BREAK_MAX)
    a["break_kind"] = kind
    try:
        c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
                  (a["key"], "break", f"{emoji} {a['name']} is {label}."))
    except Exception:
        pass
    return t


def end_break(c, a):
    """Called when a break's timer elapses → Catharsis so they don't instantly re-break."""
    a["break_until"] = 0
    a["break_kind"] = None
    add_thought(c, a["key"], "Catharsis (weathered a breakdown)", 30, hours=8, unique=True)


def break_view(a):
    """(state, emoji, label) for a currently-broken agent."""
    kind = a.get("break_kind") or "sadwander"
    for _thresh, k, emoji, label in TIERS:
        if k == kind:
            return emoji, label
    return "😢", "having a moment"
