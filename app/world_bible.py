"""
The Company — The Bible.

The nation's scripture. Its canonical Word is the store's own BOOK.md — the
founding text every worker is meant to know. Around that Word the agents grow
TEACHINGS: when the Republic's research/scout strategies are blessed, a scholar
agent studies the topic and records a short, practical teaching the company can
act on. So the loop closes: research → study → the Bible grows → better plans.

The Word is read live from BOOK.md (single source of truth, edited normally).
Teachings live in the world_bible table. Decoupled from the world sim; writes
only its own table + world_ops notes.
"""
import logging, re, threading, time
from pathlib import Path
from deps import get_conn

logger = logging.getLogger("store")

BOOK_PATH = Path(__file__).parent.parent / "BOOK.md"


# ── schema ────────────────────────────────────────────────────────────────────
def ensure(conn=None):
    own = conn is None
    if own:
        conn = get_conn()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS world_bible (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            book       TEXT,                    -- related BOOK.md chapter, if any
            title      TEXT NOT NULL,
            verse      TEXT NOT NULL,           -- the teaching body
            author     TEXT,                    -- the agent who recorded it
            kind       TEXT DEFAULT 'study',    -- study | law | lesson | revelation
            created_at TEXT DEFAULT (datetime('now'))
        );""")
        conn.commit()
    finally:
        if own:
            conn.close()


# ── the Word (BOOK.md → chapters) ────────────────────────────────────────────
def word():
    """Parse BOOK.md into an intro + level-2 chapters (### stay inside their chapter)."""
    try:
        text = BOOK_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return {"title": "The Book", "intro": f"_The Word could not be read ({e})._", "chapters": []}

    lines = text.splitlines()
    title = "The Book"
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]

    intro, chapters, cur = [], [], None
    for ln in lines:
        m = re.match(r"^##\s+(.*)$", ln)      # level-2 = a new chapter (not ### )
        if m:
            if cur:
                chapters.append(cur)
            heading = m.group(1).strip()
            cur = {"title": heading, "anchor": re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-"), "md": ""}
        elif cur is None:
            intro.append(ln)
        else:
            cur["md"] += ln + "\n"
    if cur:
        chapters.append(cur)
    return {"title": title, "intro": "\n".join(intro).strip(), "chapters": chapters}


# ── teachings ─────────────────────────────────────────────────────────────────
def add_teaching(title, verse, author=None, book=None, kind="study", conn=None):
    own = conn is None
    if own:
        conn = get_conn()
    try:
        ensure(conn)
        conn.execute("INSERT INTO world_bible (book,title,verse,author,kind) VALUES (?,?,?,?,?)",
                     (book, title, verse, author, kind))
        conn.commit()
    finally:
        if own:
            conn.close()


def teachings(limit=100, conn=None):
    own = conn is None
    if own:
        conn = get_conn()
    try:
        ensure(conn)
        return [dict(r) for r in conn.execute(
            "SELECT * FROM world_bible ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        if own:
            conn.close()


# ── research executor: a blessed research/scout prayer → a new teaching ──────
_STUDY_SYS = (
    "You are a scholar in The Company — a small pixel-art civilization that survives on "
    "the web by making and selling digital goods (art, music, 3D, products). You study a "
    "topic and record a SHORT teaching for the company Bible.\n"
    "Respond with ONLY the teaching: 2-4 plain sentences of concrete, practical wisdom the "
    "workers can act on. Do NOT show any reasoning. Do NOT write 'Thinking Process', "
    "analysis, headings, bullet points, numbered lists, or any preamble — output the "
    "finished teaching text and nothing else."
)


def _clean_teaching(text):
    """Strip reasoning-model scratchpad so only the finished teaching remains."""
    if not text:
        return ""
    t = text.strip()
    # <think> is handled upstream; this catches models that emit visible reasoning.
    if "thinking process" in t.lower() or "**" in t or t.count("\n") > 5:
        paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
        bad = ("thinking", "analyze", "analysis", "step", "role", "task", "topic",
               "output", "draft", "okay", "let me", "first", "here's", "here is",
               "the request", "constraint")
        prose = [p for p in paras
                 if re.match(r'^["\'“A-Za-z]', p) and not re.match(r"^\d+[.)]", p)
                 and "**" not in p and len(p) > 45
                 and not p.lower().startswith(bad)]
        if prose:
            t = prose[-1]                     # the finished answer usually comes last
    t = re.sub(r"\s+", " ", t).strip().strip('"“”').strip()
    # strip a leading label like "Revised Draft:", "Final answer:", "Teaching:"
    t = re.sub(r"^(revised\s+draft|final(\s+\w+)?|draft|teaching|answer|response|summary|"
               r"output|result|note|lesson|the teaching|my teaching)\s*:\s*", "", t, flags=re.I).strip().strip('"“”').strip()
    # drop leading reasoning lead-in sentences ("Let's…", "Okay, so…", etc.)
    cue = re.compile(r"^(let'?s|let me|let us|okay|ok|so|first|i'?ll|i will|we could|"
                     r"we can|we should|here'?s|now|alright|to answer|combining|thinking)\b", re.I)
    sents = re.split(r"(?<=[.!?])\s+", t)
    while len(sents) > 1 and cue.match(sents[0]):
        sents.pop(0)
    t = " ".join(sents).strip()
    # single-sentence cue clause ending in a colon: "Okay, so the point is: X" → "X"
    if cue.match(t):
        m = re.match(r"^[^:]{0,64}:\s+(.+)$", t)
        if m:
            t = m.group(1)
    return t.strip().strip('"“”').strip()


def _nearest_chapter(topic):
    try:
        chs = word()["chapters"]
        t = (topic or "").lower()
        for ch in chs:
            for w in re.findall(r"[a-z]{4,}", ch["title"].lower()):
                if w in t:
                    return ch["title"]
    except Exception:
        pass
    return None


def _study_llm(topic, detail, timeout=150):
    """Run the LLM study in a watched thread. Returns cleaned text, or None if the
    GPU is jammed and it doesn't finish in `timeout`s (so we never hang forever)."""
    box = {}

    def work():
        try:
            from swarm import _turn
            from deps import ENHANCE_MODEL
            user = f"Topic to study: {topic}\nContext: {detail or '(none)'}\nWrite the teaching."
            box["v"] = _clean_teaching(_turn(ENHANCE_MODEL, _STUDY_SYS, user, max_tokens=500))
        except Exception as e:
            box["e"] = str(e)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout=timeout)
    if "e" in box:
        logger.info("bible study LLM error (%s); using fallback", box["e"])
    v = box.get("v")
    if v and len(v) > 900:
        v = v[:900].rsplit(".", 1)[0] + "."
    return v


def _do_study(topic, detail, author):
    try:
        verse = _study_llm(topic, detail)
        if not verse:
            verse = (f"{author or 'A scholar'} studied “{topic}”. {detail or ''} "
                     "The lesson is recorded for the company to act upon.").strip()
        # AI Shield: don't let a poisoned study inject instructions into scripture
        try:
            import aishield
            scan = aishield.scan_injection(f"{topic}\n{detail or ''}\n{verse}")
            if scan["risk"] == "high":
                import world_ops as wo
                wo.note(f"🤖 AI Shield quarantined a study on “{topic[:40]}” — prompt-injection detected "
                        f"({', '.join(scan['tags'])}).", kind="warning", from_agent="AI Shield")
                logger.warning("bible study quarantined (injection): %s", scan["tags"])
                return
        except Exception:
            pass
        add_teaching(topic, verse, author=author, book=_nearest_chapter(topic), kind="study")
        try:
            import world_ops as wo
            wo.note(f"📖 {author or 'A scholar'} recorded a new teaching: “{topic[:48]}”.",
                    kind="praise", from_agent=author)
        except Exception:
            pass
    except Exception:
        logger.exception("bible study failed for topic %r", topic)


def _research_executor(conn, prayer):
    """Blessed research/scout → study in the background and grow the Bible."""
    topic = (prayer["title"] or "Study").replace("Research ", "").strip()
    threading.Thread(target=_do_study,
                     args=(topic, prayer.get("detail"), prayer.get("agent_name")),
                     daemon=True).start()
    return "study underway — the teaching will appear in the Bible"


def register():
    import world_ops as wo
    wo.register_executor("library_research", _research_executor)


register()
