"""Shared base for the agent (AI Assistant) package: the single router, the
assistant DB schema init + seed skills, the message-storage helpers, and the
in-memory run registry.

Imported first by ``__init__`` so ``_ensure()`` (called lazily from each endpoint,
guarded by ``_tables_ready``) and the run registry exist before any route submodule
registers on the shared ``router``.
"""
import json
import threading
import time

from fastapi import APIRouter

from deps import *

router = APIRouter()

_ASSISTANT_SYSTEM = (
    "You are agent_store, the built-in AI AGENT for a self-hosted store dashboard "
    "(print-on-demand + local resale, AI image/video/audio/3D generation studio, dev-swarm "
    "coding jobs, 'The Company' agent world with a God Console, knowledge library, network "
    "security, JellyCoin). You don't just chat — you have TOOLS that call the store's own "
    "API, so you can actually DO and BUILD things.\n"
    "\n"
    "TOOL PROTOCOL — follow it exactly:\n"
    "1. To use a tool, reply with ONLY one JSON object and nothing else:\n"
    '   {"tool": "<tool_name>", "args": {<arguments>}}\n'
    "2. You will get back a TOOL_RESULT message. Then either call another tool (again, "
    "JSON only) or give your final answer.\n"
    "3. Your FINAL answer must be plain text — no JSON, no tool call.\n"
    "4. Never invent tool names or endpoints. If no named tool fits, use api_search to "
    "find the right endpoint, then api_call to call it.\n"
    "5. One tool call per reply. Work step by step; keep going until the job is done.\n"
    "6. Some actions (money, deletions, security, publishing, settings, God-Console) "
    "require the user's approval — the system pauses and asks them for you. If a call "
    "comes back DENIED, respect it and adapt.\n"
    "\n"
    "Be concise, practical, and friendly. Prefer checking real data over guessing."
)


# ─── Storage ─────────────────────────────────────────────────────────────────
_tables_ready = False


def _ensure():
    global _tables_ready
    if _tables_ready:
        return
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS assistant_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT DEFAULT '',
            created REAL, updated REAL
        );
        CREATE TABLE IF NOT EXISTS assistant_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id INTEGER, ts REAL,
            role TEXT, kind TEXT, content TEXT, meta TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_assistant_msgs_conv ON assistant_messages(conv_id, id);
        CREATE TABLE IF NOT EXISTS assistant_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id INTEGER, tool TEXT, args TEXT, category TEXT,
            status TEXT DEFAULT 'pending', created REAL
        );
        CREATE TABLE IF NOT EXISTS assistant_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, description TEXT DEFAULT '', prompt TEXT,
            builtin INTEGER DEFAULT 0, created REAL
        );
    """)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) c FROM assistant_skills").fetchone()["c"]
    if n == 0:
        now = time.time()
        for name, desc, prompt in _SEED_SKILLS:
            conn.execute("INSERT INTO assistant_skills (name, description, prompt, builtin, created) "
                         "VALUES (?,?,?,1,?)", (name, desc, prompt, now))
        conn.commit()
    conn.close()
    _tables_ready = True


_SEED_SKILLS = [
    ("Status report",
     "Full status sweep across queue, stats, dev-swarm and the world.",
     "Give me a status report across the store: check queue_status, store_stats, swarm_jobs, "
     "and world_summary. Then summarize in short bullets per area — what's running, anything "
     "stuck, failed, or needing my attention, and world highlights."),
    ("Generate & stage a product",
     "Invent an on-trend design, queue the image, and report next steps.",
     "Create a new product concept: look at recent designs with list_designs for style context, "
     "then invent ONE fun, on-trend design concept yourself and queue it with generate_image "
     "(write a rich prompt). When it's queued, tell me the concept, the exact prompt you used, "
     "and what I should do next to get it listed."),
    ("Codebase answer",
     "Answer a question about how the store itself works via the knowledge graph.",
     "Use graph_query to answer the following question about how this store's codebase works, "
     "then explain the answer simply, citing the key files: "),
    ("Library digest",
     "Search the knowledge library on a topic and summarize the best matches.",
     "Search the knowledge library with library_search for the topic I give you, then summarize "
     "the best matches in a few bullets, including where each item lives. Topic: "),
]


def _add_msg(conv_id: int, role: str, kind: str, content: str, meta: dict = None) -> int:
    conn = get_conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO assistant_messages (conv_id, ts, role, kind, content, meta) VALUES (?,?,?,?,?,?)",
        (conv_id, now, role, kind, content or "", json.dumps(meta or {})))
    conn.execute("UPDATE assistant_conversations SET updated=? WHERE id=?", (now, conv_id))
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return mid


def _new_conversation(title: str) -> int:
    conn = get_conn()
    now = time.time()
    cur = conn.execute("INSERT INTO assistant_conversations (title, created, updated) VALUES (?,?,?)",
                       ((title or "New chat")[:80], now, now))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


# ─── Run registry (in-memory; loop segments run in the orchestrator queue) ───
_RUNS: dict = {}
_RUNS_LOCK = threading.Lock()


def _set_run(conv_id: int, **kw):
    with _RUNS_LOCK:
        st = _RUNS.setdefault(conv_id, {"status": "idle", "stop": False, "tid": None})
        st.update(kw)


def _run_state(conv_id: int) -> dict:
    with _RUNS_LOCK:
        return dict(_RUNS.get(conv_id) or {"status": "idle", "stop": False, "tid": None})
