"""Agent Watcher — background health monitor for every agent-run task.

Watches the Dev Swarm (coder/builder jobs), gated system-agent installs, and the
media job tables (image/video/audio/3D) for failures, pauses, and silent stalls.
For each NEW problem it opens an incident with a DIAGNOSIS — what happened, the
likely cause, and concrete fix steps — built from a fast rule engine first, then
(optionally) enriched by the local LLM "doctor". The diagnosis is:

  • recorded in `watcher_incidents` (queryable at /api/watcher/* — which the MCP
    mount also exposes, so OpenClaw agents can ask "what's wrong and how do I fix it")
  • posted onto the job's own swarm_events timeline (agent='watcher'), where the
    next coding round reads it as context — agents resume KNOWING what broke
  • surfaced to the God Console via world_ops.note() for high-severity cases

Settings (every behaviour has a toggle; edited via /api/watcher/settings):
  agent_watcher_enabled     "1"/"0"  master switch                     (default ON)
  agent_watcher_interval    minutes between scheduler ticks           (default 5)
  agent_watcher_stall_min   minutes with no swarm progress → stalled  (default 20)
  agent_watcher_media_min   minutes before a media job counts stuck   (default 90)
  agent_watcher_llm         "1"/"0"  LLM doctor on top of the rules   (default ON)
  agent_watcher_notify      "1"/"0"  God-Console notes on incidents    (default ON)
  agent_watcher_autoresume  "1"/"0"  auto re-run resumable paused jobs (default OFF)

Layering: imports only db/deps at module load; swarm / world_ops / model_registry
are imported lazily inside functions (same pattern as scheduler.py) so this module
is safe to import from anywhere.
"""
import json
import logging
import threading

from db import get_conn
from deps import get_setting

log = logging.getLogger("agentwatch")

# One LLM-enrichment worker at a time; rules never wait on the GPU.
_enrich_lock = threading.Lock()

# Swarm statuses that mean "the driver should be actively working".
_ACTIVE = ("planning", "coding", "reviewing", "testing")


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────
def _ensure_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS watcher_incidents (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        source      TEXT NOT NULL,     -- swarm|system_task|media
        ref_id      INTEGER,           -- swarm_jobs.id / swarm_system_tasks.id / media row id
        ref_kind    TEXT,              -- media table name for source=media (videos|generations|…)
        title       TEXT,
        status_seen TEXT,              -- job status when detected (failed|paused|stalled|stuck)
        severity    TEXT DEFAULT 'warn',   -- info|warn|high
        summary     TEXT,              -- one-line what happened
        cause       TEXT,              -- likely root cause
        fix         TEXT,              -- concrete steps to fix
        resumable   INTEGER DEFAULT 0, -- 1 = re-running with the fix notes is likely to work
        llm_notes   TEXT,              -- doctor's addendum (when the LLM pass ran)
        status      TEXT DEFAULT 'open',   -- open|resolved
        action      TEXT,              -- what closed it (resolved|rerun|auto_resume)
        created_at  TEXT DEFAULT (datetime('now')),
        resolved_at TEXT
    )""")
    conn.commit(); conn.close()


_ensure_table()


def _has_open(conn, source: str, ref_id, ref_kind=None) -> bool:
    row = conn.execute(
        "SELECT id FROM watcher_incidents WHERE source=? AND ref_id=? "
        "AND COALESCE(ref_kind,'')=COALESCE(?,'') AND status='open'",
        (source, ref_id, ref_kind)).fetchone()
    return row is not None


def _open_incident(source, ref_id, title, status_seen, diag, ref_kind=None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO watcher_incidents (source,ref_id,ref_kind,title,status_seen,severity,"
        "summary,cause,fix,resumable) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (source, ref_id, ref_kind, (title or "")[:200], status_seen,
         diag.get("severity", "warn"), diag.get("summary", ""), diag.get("cause", ""),
         diag.get("fix", ""), 1 if diag.get("resumable") else 0))
    iid = cur.lastrowid
    conn.commit(); conn.close()
    return iid


def incidents(status: str = None, limit: int = 50) -> list[dict]:
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM watcher_incidents WHERE status=? "
                            "ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM watcher_incidents ORDER BY id DESC LIMIT ?",
                            (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_incident(iid: int, action: str = "resolved") -> bool:
    conn = get_conn()
    cur = conn.execute("UPDATE watcher_incidents SET status='resolved', action=?, "
                       "resolved_at=datetime('now') WHERE id=? AND status='open'", (action, iid))
    conn.commit(); ok = cur.rowcount > 0
    conn.close()
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Rule engine — fast, offline diagnosis of the failure signatures we know
# ─────────────────────────────────────────────────────────────────────────────
def _rule_diagnosis(job: dict, events: list[dict], status_seen: str) -> dict:
    """Map known progress/error signatures to (summary, cause, fix, resumable)."""
    msg = (job.get("progress_msg") or "")
    err = (job.get("error") or "")
    last_err = next((e["content"] for e in events if e.get("kind") == "error"), "")
    blob = " ".join((msg, err, last_err)).lower()

    if "no usable change" in blob or "no parseable" in blob:
        return {"summary": "The coder produced no parseable file blocks.",
                "cause": "The coder model is too weak for this job or the context is too "
                         "large — it drifted from the required <<<FILE>>> output format.",
                "fix": "Pick a stronger coder model in Agents & Models, or shrink the job "
                       "(scope it to one file / split it into subtasks), then re-run.",
                "resumable": True, "severity": "warn"}
    if "out of scope" in blob:
        return {"summary": "Every edit the coder proposed was outside the job's allowed paths.",
                "cause": "The job's scope/paths are narrower than the change actually needs.",
                "fix": "Widen the job's paths (or set scope=project) so the right files are "
                       "editable, then re-run.",
                "resumable": True, "severity": "warn"}
    if "server restart" in blob or "interrupted" in blob:
        return {"summary": "The job was interrupted by a server restart.",
                "cause": "In-memory driver state is lost on restart; the job was parked safely.",
                "fix": "Nothing is broken — re-run the job to continue from its last commit.",
                "resumable": True, "severity": "info"}
    if "rounds" in blob and "paused" in blob:
        return {"summary": "Paused after hitting the max code/review rounds.",
                "cause": "Reviewers kept rejecting the change — the spec and the reviewers' "
                         "expectations don't converge.",
                "fix": "Read the last review feedback on the timeline, refine the spec or "
                       "answer the open questions, then re-run.",
                "resumable": False, "severity": "warn"}
    if "no models configured" in blob:
        return {"summary": "The swarm has no model pool configured.",
                "cause": "Agents & Models has an empty model list.",
                "fix": "Configure at least one local model in Agents & Models, then re-run.",
                "resumable": True, "severity": "high"}
    if "system install failed" in blob:
        return {"summary": "A gated system install the job depends on failed.",
                "cause": "The approved system command errored — see the system task's report.",
                "fix": "Open the job's System tasks, read the report, fix or re-propose the "
                       "command, approve it, then re-run the job.",
                "resumable": False, "severity": "warn"}
    if status_seen == "stalled":
        return {"summary": f"No progress for a while (status={job.get('status')}).",
                "cause": "Most likely a long/hung LLM turn — the node's LM Studio may be "
                         "unloaded, busy (GPU guard / a game), or the queue is jammed.",
                "fix": "Check the universal queue and the node's LM Studio; if the turn is "
                       "hung, restart the store service — the job parks safely and can re-run.",
                "resumable": False, "severity": "warn"}
    if status_seen == "orphaned":
        return {"summary": "The job says it's running but no driver thread exists.",
                "cause": "The driver died without updating status (crash or restart race).",
                "fix": "The watcher parked it as paused — re-run to continue.",
                "resumable": True, "severity": "warn"}
    if err or last_err:
        e = (err or last_err)[:300]
        low = e.lower()
        if any(k in low for k in ("timed out", "timeout", "connect", "refused", "ssh")):
            return {"summary": f"The run errored: {e}",
                    "cause": "The GPU node / LM Studio looks unreachable (network, SSH, or "
                             "the service is down).",
                    "fix": "Check the node is up and LM Studio is serving, then re-run the job.",
                    "resumable": True, "severity": "high"}
        return {"summary": f"The run errored: {e}",
                "cause": "Unhandled error in the swarm driver — see the timeline.",
                "fix": "Read the error on the timeline; if it looks transient, re-run. "
                       "Otherwise fix the underlying issue first.",
                "resumable": True, "severity": "warn"}
    return {"summary": f"Job is {status_seen} ({msg or 'no progress message'}).",
            "cause": "No known failure signature matched.",
            "fix": "Read the job timeline; re-run if it looks transient.",
            "resumable": False, "severity": "info"}


# ─────────────────────────────────────────────────────────────────────────────
# LLM doctor — optional enrichment (never blocks the scheduler tick)
# ─────────────────────────────────────────────────────────────────────────────
WATCHER_DOCTOR_SYS = (
    "You are the WATCHER, a background health monitor for a local-model dev swarm. "
    "You are given a stuck/failed job's state and its recent event timeline. Diagnose "
    "what is going on for BOTH the human and the agents that will retry the job. "
    'Respond in STRICT JSON: {"summary": "one line — what happened", '
    '"cause": "the likely root cause", '
    '"fix": "concrete numbered steps the agents or the human should take", '
    '"resumable": true|false — true if simply re-running the job with your fix notes '
    "is likely to succeed}. Be specific; reference actual file paths, models, and "
    "errors from the timeline, never generic advice.")


def _job_context(jid: int) -> tuple[dict, list[dict]]:
    conn = get_conn()
    job = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (jid,)).fetchone()
    evs = conn.execute("SELECT agent,kind,content,vote,model,created_at FROM swarm_events "
                       "WHERE job_id=? ORDER BY id DESC LIMIT 14", (jid,)).fetchall()
    conn.close()
    return (dict(job) if job else None), [dict(e) for e in evs]


def _llm_diagnose(job: dict, events: list[dict]) -> dict | None:
    """One doctor turn through the orchestrator queue. Returns None on any failure."""
    try:
        import model_registry
        from deps import get_prompt
        from swarm import _extract_json
        from swarm.llm import _turn
        model = model_registry.resolve("watcher_model")
        timeline = "\n".join(
            f"[{e['created_at']}] {e['agent']}/{e['kind']}"
            + (f" vote={e['vote']}" if e.get("vote") else "")
            + f": {(e['content'] or '')[:400]}"
            for e in reversed(events))
        user = (f"JOB #{job['id']}: {job['title']}\nSTATUS: {job['status']}  "
                f"PROGRESS: {job.get('progress_msg') or ''}\nERROR: {job.get('error') or '(none)'}\n"
                f"SPEC: {(job.get('enhanced_spec') or job.get('spec') or '')[:800]}\n\n"
                f"RECENT TIMELINE (oldest first):\n{timeline}")
        out = _turn(model, get_prompt("watcher_doctor"), user, max_tokens=900)
        data = _extract_json(out)

        def _s(v):   # models sometimes return the fix as a list of steps
            if isinstance(v, (list, tuple)):
                return "\n".join(str(x) for x in v)
            return str(v or "")
        if data.get("summary") or data.get("fix"):
            return {"summary": _s(data.get("summary"))[:400],
                    "cause": _s(data.get("cause"))[:600],
                    "fix": _s(data.get("fix"))[:1200],
                    "resumable": bool(data.get("resumable"))}
    except Exception as e:
        log.warning("watcher LLM diagnosis failed: %s", e)
    return None


def _enrich_async(incident_ids: list[int]):
    """Run the LLM doctor over fresh incidents in a daemon thread — the scheduler
    tick must never wait on the GPU queue."""
    if not incident_ids or not _enrich_lock.acquire(blocking=False):
        return

    def work():
        try:
            for iid in incident_ids:
                conn = get_conn()
                row = conn.execute("SELECT * FROM watcher_incidents WHERE id=? AND status='open'",
                                   (iid,)).fetchone()
                conn.close()
                if not row or row["source"] != "swarm":
                    continue
                job, evs = _job_context(row["ref_id"])
                if not job:
                    continue
                diag = _llm_diagnose(job, evs)
                if not diag:
                    continue
                conn = get_conn()
                conn.execute("UPDATE watcher_incidents SET llm_notes=?, fix=COALESCE(NULLIF(?,''),fix), "
                             "cause=COALESCE(NULLIF(?,''),cause) WHERE id=?",
                             (diag["summary"], diag["fix"], diag["cause"], iid))
                conn.commit(); conn.close()
                _post_to_timeline(job["id"], diag, enriched=True)
        finally:
            _enrich_lock.release()

    threading.Thread(target=work, daemon=True, name="agentwatch-doctor").start()


# ─────────────────────────────────────────────────────────────────────────────
# Delivery — put the diagnosis where agents and the human will actually see it
# ─────────────────────────────────────────────────────────────────────────────
def _post_to_timeline(jid: int, diag: dict, enriched: bool = False):
    """Write the diagnosis onto the job's swarm timeline. The coding stage reads the
    latest watcher event back into the coder's context on the next run."""
    try:
        from swarm import _ev
        head = "🩺 WATCHER DIAGNOSIS" + (" (doctor)" if enriched else "")
        _ev(jid, "watcher", "watcher",
            f"{head}\nWhat happened: {diag.get('summary')}\n"
            f"Likely cause: {diag.get('cause')}\nHow to fix: {diag.get('fix')}")
    except Exception as e:
        log.warning("watcher timeline post failed: %s", e)


def _notify(text: str):
    if get_setting("agent_watcher_notify", "1") != "1":
        return
    try:
        import world_ops as wo
        wo.note(text, kind="warning", from_agent="Agent Watcher")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# The tick
# ─────────────────────────────────────────────────────────────────────────────
def watch_tick() -> dict:
    """One watcher pass. Fast and DB-only; LLM enrichment happens async."""
    import swarm
    stall_min = max(5, int(get_setting("agent_watcher_stall_min", "20") or 20))
    media_min = max(15, int(get_setting("agent_watcher_media_min", "90") or 90))
    new_ids, notes = [], []
    conn = get_conn()

    # 1) Swarm jobs that ended badly: failed / paused without an open incident.
    bad = conn.execute("SELECT * FROM swarm_jobs WHERE status IN ('failed','paused')").fetchall()
    # 2) Swarm jobs claiming to run: stalled (no update in stall_min) or orphaned.
    active = conn.execute(
        "SELECT * FROM swarm_jobs WHERE status IN (%s) AND "
        "updated_at <= datetime('now', ?)" % ",".join("?" * len(_ACTIVE)),
        (*_ACTIVE, f"-{stall_min} minutes")).fetchall()
    conn.close()

    for r in bad:
        job = dict(r)
        conn = get_conn()
        skip = _has_open(conn, "swarm", job["id"])
        conn.close()
        if skip:
            continue
        _, evs = _job_context(job["id"])
        diag = _rule_diagnosis(job, evs, job["status"])
        iid = _open_incident("swarm", job["id"], job["title"], job["status"], diag)
        new_ids.append(iid)
        _post_to_timeline(job["id"], diag)
        notes.append(f"job #{job['id']} {job['status']}: {diag['summary']}")
        if diag.get("severity") == "high":
            _notify(f"🩺 Swarm job #{job['id']} “{job['title']}” {job['status']} — {diag['summary']} "
                    f"Fix: {diag['fix']}")
        # Opt-in auto-resume: only clearly-resumable pauses, never failed jobs.
        if (get_setting("agent_watcher_autoresume", "0") == "1"
                and diag.get("resumable") and job["status"] == "paused"):
            if swarm.start_job(job["id"]):
                resolve_incident(iid, action="auto_resume")
                notes.append(f"auto-resumed job #{job['id']}")

    for r in active:
        job = dict(r)
        conn = get_conn()
        skip = _has_open(conn, "swarm", job["id"])
        conn.close()
        if skip:
            continue
        orphaned = not swarm.is_running(job["id"])
        seen = "orphaned" if orphaned else "stalled"
        if orphaned:
            # Park it exactly like reconcile_on_start does, so re-run is clean.
            conn = get_conn()
            conn.execute("UPDATE swarm_jobs SET status='paused', "
                         "progress_msg='Parked by the watcher — driver thread was gone' "
                         "WHERE id=?", (job["id"],))
            conn.commit(); conn.close()
        _, evs = _job_context(job["id"])
        diag = _rule_diagnosis(job, evs, seen)
        iid = _open_incident("swarm", job["id"], job["title"], seen, diag)
        new_ids.append(iid)
        _post_to_timeline(job["id"], diag)
        notes.append(f"job #{job['id']} {seen}")

    # 3) Failed gated system installs (blocks the jobs that requested them).
    conn = get_conn()
    try:
        sys_bad = conn.execute("SELECT * FROM swarm_system_tasks WHERE status='failed'").fetchall()
    except Exception:
        sys_bad = []
    conn.close()
    for r in sys_bad:
        t = dict(r)
        conn = get_conn()
        skip = _has_open(conn, "system_task", t["id"])
        conn.close()
        if skip:
            continue
        diag = {"summary": f"System install failed: {t['request']}",
                "cause": (t.get("report") or "The approved command errored.")[:400],
                "fix": "Read the report, fix or re-propose the command, approve it, then "
                       "re-run the blocked job.",
                "resumable": False, "severity": "warn"}
        iid = _open_incident("system_task", t["id"], t["request"], "failed", diag)
        new_ids.append(iid)
        if t.get("job_id"):
            _post_to_timeline(t["job_id"], diag)

    # 4) Media/builder jobs stuck mid-generate far beyond normal (report-only —
    #    never kills a long render; reconcile_stuck_media handles restart orphans).
    media_q = (
        ("generations", "prompt", "status='generating'"),
        ("videos", "prompt", "status IN ('queued','generating')"),
        ("video_chains", "COALESCE(NULLIF(title,''),concept)", "status IN ('pending','generating')"),
        ("audio_clips", "prompt", "status IN ('queued','generating')"),
        ("models3d", "COALESCE(NULLIF(title,''),gen_prompt)", "status='generating'"),
    )
    conn = get_conn()
    for table, label_sql, where in media_q:
        try:
            rows = conn.execute(
                f"SELECT id, {label_sql} AS label, status, created_at FROM {table} "
                f"WHERE {where} AND created_at <= datetime('now', ?)",
                (f"-{media_min} minutes",)).fetchall()
        except Exception:
            continue
        for r in rows:
            if _has_open(conn, "media", r["id"], ref_kind=table):
                continue
            diag = {"summary": f"{table} #{r['id']} has been '{r['status']}' for over "
                               f"{media_min} min.",
                    "cause": "The generator hung, the node is busy/paused (GPU guard), or "
                             "the worker died without updating the row.",
                    "fix": "Check the universal queue and the node; if nothing is actually "
                           "running, clear/re-queue the job from its tab.",
                    "resumable": False, "severity": "info"}
            iid = _open_incident("media", r["id"], (r["label"] or "")[:120], "stuck",
                                 diag, ref_kind=table)
            new_ids.append(iid)
    conn.close()

    # LLM doctor over the fresh swarm incidents, off-thread.
    if get_setting("agent_watcher_llm", "1") == "1":
        _enrich_async(new_ids)

    if notes:
        log.info("agent watcher: %s", "; ".join(notes)[:400])
    conn = get_conn()
    open_n = conn.execute("SELECT COUNT(*) FROM watcher_incidents WHERE status='open'").fetchone()[0]
    conn.close()
    return {"new": len(new_ids), "open": open_n}
