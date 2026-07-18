"""Dev Swarm — shared persistence & config helpers used across the package.

This module has NO intra-package dependencies; every other swarm submodule
imports from here.
"""
import json

from db import get_conn
from deps import get_setting


# ─────────────────────────────────────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────────────────────────────────────
def _ev(job_id, agent, kind, content, vote=None, model=None):
    conn = get_conn()
    conn.execute("INSERT INTO swarm_events (job_id,agent,kind,content,vote,model) VALUES (?,?,?,?,?,?)",
                 (job_id, agent, kind, str(content)[:8000], vote, model))
    conn.commit(); conn.close()


def _set(job_id, **fields):
    if not fields:
        return
    fields["updated_at"] = None  # placeholder to force the datetime below
    sets = ", ".join(f"{k}=?" for k in fields if k != "updated_at") + ", updated_at=datetime('now')"
    vals = [v for k, v in fields.items() if k != "updated_at"]
    conn = get_conn()
    conn.execute(f"UPDATE swarm_jobs SET {sets} WHERE id=?", (*vals, job_id))
    conn.commit(); conn.close()


def _job(job_id) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _config() -> dict:
    raw = get_setting("swarm_config", "")
    cfg = {}
    if raw:
        try:
            cfg = json.loads(raw)
        except Exception:
            cfg = {}
    cfg.setdefault("autonomy", "gate")
    cfg.setdefault("mode", "dynamic")
    cfg.setdefault("agent_count", 3)
    cfg.setdefault("models", [])
    cfg.setdefault("voters", 2)
    cfg.setdefault("no_self_approval", True)
    cfg.setdefault("self_review_when_solo", True)
    return cfg
