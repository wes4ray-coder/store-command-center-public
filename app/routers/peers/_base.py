"""Shared foundation for the peers package: the single APIRouter, the SQLite
schema (created once at import), cross-cutting key/row helpers, and the module
constants. Imported by api.py, rpc.py and client.py."""
import hashlib
import hmac
import secrets
import subprocess

from fastapi import APIRouter, HTTPException, Request

from deps import get_conn, get_setting
from config import GIT_BIN, BASE

router = APIRouter()

_RATE_PER_HOUR = 600          # rpc calls per peer per rolling hour
_MAX_DIFF = 200_000           # chars of diff accepted for review
_MAX_PROMPT = 60_000          # chars of llm prompt accepted for a peer job


def _ensure_schema():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS peers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        base_url TEXT,
        token_in_hash TEXT,            -- sha256 of the key WE accept from them
        token_out TEXT,                -- enc: the key WE present to them
        status TEXT DEFAULT 'pending', -- pending | approved | revoked
        accept_work INTEGER DEFAULT 0,
        accept_reviews INTEGER DEFAULT 1,
        work_kinds TEXT DEFAULT 'llm,embedding',  -- which job kinds this peer may run here
        last_seen TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS peer_invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_hash TEXT NOT NULL,
        note TEXT,
        used_by INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS peer_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        peer_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        status TEXT DEFAULT 'queued',  -- queued | done | error
        payload TEXT,
        result TEXT,
        error TEXT,
        orch_tid INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS peer_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        peer_id INTEGER NOT NULL,
        title TEXT,
        diff TEXT,
        status TEXT DEFAULT 'reviewing',  -- reviewing | done | error
        llm_vote TEXT, llm_comments TEXT, llm_model TEXT,
        human_vote TEXT, human_comments TEXT,
        orch_tid INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS peer_review_requests (   -- reviews WE asked a peer for
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        peer_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        remote_review_id INTEGER,
        status TEXT DEFAULT 'sent',    -- sent | done | error
        llm_vote TEXT, llm_comments TEXT, llm_model TEXT,
        human_vote TEXT, human_comments TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS peer_rpc_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        peer_id INTEGER,
        path TEXT,
        src TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_peer_rpc_log_peer_time ON peer_rpc_log (peer_id, created_at);
    """)
    # idempotent column migrations for installs whose peers table predates them
    for mig in ["ALTER TABLE peers ADD COLUMN work_kinds TEXT DEFAULT 'llm,embedding'"]:
        try:
            conn.execute(mig)
        except Exception:
            pass
    conn.commit()
    conn.close()


_ensure_schema()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _hash(key: str) -> str:
    return hashlib.sha256((key or "").encode()).hexdigest()


def _new_key(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def _peer_from_key(request: Request):
    """Authenticate an rpc call: X-Peer-Key must hash-match an APPROVED peer.
    Also rate-limits and logs the call. This runs INSIDE every rpc endpoint, so
    even localhost/MCP callers can't use the rpc surface without a key."""
    key = request.headers.get("X-Peer-Key", "")
    if not key:
        raise HTTPException(401, "Missing X-Peer-Key header.")
    h = _hash(key)
    conn = get_conn()
    row = None
    for p in conn.execute("SELECT * FROM peers WHERE status='approved'").fetchall():
        if p["token_in_hash"] and hmac.compare_digest(p["token_in_hash"], h):
            row = p
            break
    if not row:
        conn.close()
        raise HTTPException(401, "Unknown, pending, or revoked peer key.")
    n = conn.execute("SELECT COUNT(*) c FROM peer_rpc_log WHERE peer_id=? "
                     "AND created_at > datetime('now','-1 hour')", (row["id"],)).fetchone()["c"]
    if n >= _RATE_PER_HOUR:
        conn.close()
        raise HTTPException(429, "Peer rate limit reached — try again later.")
    src = request.client.host if request.client else ""
    conn.execute("INSERT INTO peer_rpc_log (peer_id,path,src) VALUES (?,?,?)",
                 (row["id"], request.url.path, src))
    # keep the log bounded: only the rate-limit window plus a week of audit trail is useful
    conn.execute("DELETE FROM peer_rpc_log WHERE created_at < datetime('now','-7 days')")
    conn.execute("UPDATE peers SET last_seen=datetime('now') WHERE id=?", (row["id"],))
    conn.commit()
    conn.close()
    return row


def _get_peer(pid: int, statuses=("approved",)):
    conn = get_conn()
    row = conn.execute("SELECT * FROM peers WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Peer not found")
    if statuses and row["status"] not in statuses:
        raise HTTPException(400, f"Peer is {row['status']} — approve/re-pair it first.")
    return row


def _my_name() -> str:
    return get_setting("store_name", "") or "a Store install"


def _git_info():
    out = {}
    for k, args in (("branch", ["rev-parse", "--abbrev-ref", "HEAD"]),
                    ("commit", ["rev-parse", "--short", "HEAD"])):
        try:
            r = subprocess.run([GIT_BIN, "-C", str(BASE), *args],
                               capture_output=True, text=True, timeout=10)
            out[k] = r.stdout.strip() if r.returncode == 0 else "?"
        except Exception:
            out[k] = "?"
    return out


def _set_row(table: str, rid: int, **fields):
    """Update columns on one row + touch updated_at. `table` is always a literal
    from this module, never user input."""
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=datetime('now')"
    conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*fields.values(), rid))
    conn.commit()
    conn.close()


def _set_job(jid: int, **fields):
    _set_row("peer_jobs", jid, **fields)


def _set_review(rid: int, **fields):
    _set_row("peer_reviews", rid, **fields)
