"""
The Company — STRATEGY GENOMES: no two agents play the game the same way.

Every agent carries a personal strategy (a small genome of behaviour
hyper-parameters) and TWEAKS it from results — a (1+1) evolution strategy plus
cultural imitation of the leaderboard:

    epsilon 0.05–0.35   how much they experiment vs exploit (bandit explore rate)
    focus   0.5–2.0     grinder vs switcher (dwell-length multiplier)
    spend   0.4–2.5     saver vs shopper (furnish-roll multiplier)

Review loop (ticker, ~6h): fitness = ΔXP + 2·Δearnings over the window.
  improved → keep drifting the same direction (small mutation)
  declined → bigger random mutation (try something else)
  bottom performers sometimes IMITATE a top performer's genome ± noise —
  "what works best" spreads through the town, mutation keeps diversity.

Initial genomes are hash-seeded per agent, so the town starts diverse.
All persisted in world_agents.strategy (JSON); zero new heavy dependencies.
"""
import json
import logging
import random
import time

from world_defs import mget, mset, log_agent

logger = logging.getLogger("store")

REVIEW_EVERY_SEC = 6 * 3600
BOUNDS = {"epsilon": (0.05, 0.35), "focus": (0.5, 2.0), "spend": (0.4, 2.5)}


def _ensure(c):
    try:
        c.execute("ALTER TABLE world_agents ADD COLUMN strategy TEXT")
    except Exception:
        pass


def _default(a):
    h = (a["id"] * 2654435761) & 0xffffff
    return {"epsilon": 0.05 + (h % 100) / 100 * 0.30,
            "focus": 0.6 + ((h >> 8) % 100) / 100 * 1.2,
            "spend": 0.5 + ((h >> 16) % 100) / 100 * 1.6,
            "fit": None, "xp0": a.get("xp") or 0, "earn0": a.get("coins_earned") or 0}


def genome(a):
    """Parse an agent row's strategy (dict rows and sqlite Rows both fine)."""
    try:
        g = json.loads(a["strategy"] or "")
        if isinstance(g, dict) and "epsilon" in g:
            return g
    except Exception:
        pass
    return _default(dict(a))


def _clamp(g):
    for k, (lo, hi) in BOUNDS.items():
        g[k] = max(lo, min(hi, float(g.get(k, (lo + hi) / 2))))
    return g


def _mutate(g, scale):
    for k in BOUNDS:
        g[k] = g[k] + random.uniform(-1, 1) * scale * (BOUNDS[k][1] - BOUNDS[k][0])
    return _clamp(g)


STYLE = lambda g: ("🧪 experimenter" if g["epsilon"] > 0.24 else
                   "🎯 exploiter" if g["epsilon"] < 0.11 else "⚖️ balanced")


def review(conn):
    """The tweak loop: score every agent's window, mutate/imitate, persist."""
    c = conn.cursor()
    _ensure(c)
    if time.time() - float(mget(c, "last_genome_review", 0) or 0) < REVIEW_EVERY_SEC:
        return
    mset(c, "last_genome_review", time.time())
    rows = [dict(r) for r in c.execute(
        "SELECT id, key, name, xp, coins_earned, strategy FROM world_agents "
        "WHERE kind IN ('worker','openclaw')").fetchall()]
    scored = []
    for a in rows:
        g = genome(a)
        fit = (a["xp"] - g.get("xp0", a["xp"])) + 2 * (a["coins_earned"] - g.get("earn0", a["coins_earned"]))
        scored.append((fit, a, g))
    scored.sort(key=lambda t: -t[0])
    top = scored[: max(1, len(scored) // 3)]
    for rank, (fit, a, g) in enumerate(scored):
        prev = g.get("fit")
        if prev is not None and rank >= len(scored) * 2 // 3 and random.random() < 0.35 and top:
            # struggling → learn from a champion (imitate ± noise)
            src = random.choice(top)[2]
            g = _mutate({**g, **{k: src[k] for k in BOUNDS}}, 0.08)
            log_agent(a["key"], a["name"], "🧬 Studied how the top performers work and adjusted my whole approach.")
        elif prev is not None and fit < prev:
            g = _mutate(g, 0.15)                          # worse → shake it up
            log_agent(a["key"], a["name"], f"🧬 That approach underperformed — trying something new ({STYLE(g)}).")
        else:
            g = _mutate(g, 0.04)                          # better/first pass → gentle drift
        g["fit"], g["xp0"], g["earn0"] = fit, a["xp"], a["coins_earned"]
        c.execute("UPDATE world_agents SET strategy=? WHERE id=?", (json.dumps(g), a["id"]))
    conn.commit()
    try:
        c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES ('','system',?)",
                  (f"🧬 Strategy review: the crew tuned their approaches — "
                   f"best window {int(scored[0][0])} ({scored[0][1]['name']}).",))
        conn.commit()
    except Exception:
        pass
