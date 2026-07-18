"""
The Company — agent EPISODIC MEMORY (felt, not just archived).

Every agent has always kept a journal (world_agents/<key>.md) — write-only.
This module makes them able to REMEMBER it:

  • index_journal — meaningful journal lines (blessings, kills, purchases,
    studies, saves) get embedded on world_taste's embedding rail and stored
    per-agent in `world_memories`
  • recall — given what the agent is doing right now, cosine-retrieve their
    most relevant lived moments
  • remember_context — one-call helper the cognition prompt uses, so their
    spoken thoughts reference real events ("still proud of felling that
    warlord") instead of being generated from a blank present

Embed traffic is tiny and bounded: ≤4 new lines indexed + 1 query embed per
thinking agent, only when the hourly cognition batch runs.
"""
import json
import logging
import re

from world_defs import AGENT_LOG_DIR

logger = logging.getLogger("store")

MAX_PER_AGENT = 120
# journal lines worth remembering (vs routine "heads to the bar" noise)
_MEANING = re.compile(r"🙌|😞|⚔️|🎨|🛍️|📚|⛑️|🏆|🔁|📝|💫|Bought|Ate|Slew|God|level|blessed|"
                      r"commissioned|saved|wounded|refresh", re.I)


def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS world_memories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_key TEXT NOT NULL,
        text TEXT NOT NULL,
        vec TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(agent_key, text))""")


def index_journal(c, key, max_new=4):
    """Embed up to `max_new` meaningful new journal lines for this agent."""
    _ensure(c)
    try:
        p = AGENT_LOG_DIR / f"{key}.md"
        if not p.exists():
            return 0
        lines = [ln[2:].strip() for ln in p.read_text().splitlines()[-60:]
                 if ln.startswith("- ") and _MEANING.search(ln)]
    except Exception:
        return 0
    have = {r["text"] for r in c.execute(
        "SELECT text FROM world_memories WHERE agent_key=? ORDER BY id DESC LIMIT 200", (key,))}
    n = 0
    import world_taste
    for ln in reversed(lines):                    # newest first
        if n >= max_new:
            break
        txt = ln.split("— ", 1)[-1][:200]         # drop the timestamp prefix
        if not txt or txt in have:
            continue
        vec = world_taste._embed(txt)
        c.execute("INSERT OR IGNORE INTO world_memories (agent_key,text,vec) VALUES (?,?,?)",
                  (key, txt, json.dumps(vec) if vec else None))
        n += 1
    # forget the distant past beyond the cap (oldest first — renewal for minds too)
    c.execute("DELETE FROM world_memories WHERE agent_key=? AND id NOT IN "
              "(SELECT id FROM world_memories WHERE agent_key=? ORDER BY id DESC LIMIT ?)",
              (key, key, MAX_PER_AGENT))
    return n


def recall(c, key, query, k=3):
    """The agent's most relevant lived moments for what's happening now."""
    _ensure(c)
    rows = c.execute("SELECT text, vec FROM world_memories WHERE agent_key=? "
                     "ORDER BY id DESC LIMIT 120", (key,)).fetchall()
    if not rows:
        return []
    import world_taste
    vecs = [(r["text"], json.loads(r["vec"])) for r in rows if r["vec"]]
    if len(vecs) >= 2:
        qv = world_taste._embed(query)
        if qv:
            scored = sorted(((world_taste._cos(qv, v), t) for t, v in vecs), reverse=True)
            return [t for _, t in scored[:k]]
    return [r["text"] for r in rows[:k]]          # fallback: most recent moments


def remember_context(a, conn=None):
    """One-line memory context for the cognition prompt. Opens its own conn if
    needed; never raises."""
    from deps import get_conn
    own = conn is None
    if own:
        conn = get_conn()
    try:
        c = conn.cursor()
        index_journal(c, a["key"])
        conn.commit()
        q = f"{a.get('state','')} {a.get('location','')} {a.get('goal','')}"
        mems = recall(c, a["key"], q)
        return "; ".join(mems[:3])
    except Exception:
        logger.exception("remember_context failed")
        return ""
    finally:
        if own:
            conn.close()
