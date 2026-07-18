"""Domain C — jobs / proposals data model, questions, approve/reject, system-agent
tasks, run, and the dev→master→retail promote. Routes register on the shared router.
"""
import json
from typing import Optional

from deps import *   # get_conn, threading, config (GIT_BIN, REPO_*, RESTART_CMD), HTTPException
import swarm
from ._base import router, _gitc
from .models import get_swarm_config


# ─────────────────────────────────────────────────────────────────────────────
# Jobs / proposals (data model; engine is Phase 2)
# ─────────────────────────────────────────────────────────────────────────────
class JobIn(BaseModel):
    title: str
    spec: Optional[str] = ""
    repo: Optional[str] = ""
    branch: Optional[str] = "dev"
    autonomy: Optional[str] = None    # override global; gate|auto|step
    scope: Optional[str] = "project"  # project | folder | file
    paths: Optional[list] = None      # file/folder paths the job is scoped to
    agent_count: Optional[int] = None # per-job dynamic N (NULL = global default)


def _job_dict(row) -> dict:
    d = dict(row)
    conn = get_conn()
    d["open_questions"] = conn.execute(
        "SELECT COUNT(*) c FROM swarm_questions WHERE job_id=? AND status='open'", (d["id"],)
    ).fetchone()["c"]
    conn.close()
    return d


@router.get("/api/github/jobs")
def list_jobs(status: Optional[str] = None):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM swarm_jobs WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM swarm_jobs ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [_job_dict(r) for r in rows]


@router.post("/api/github/jobs")
def create_job(body: JobIn):
    if not body.title.strip():
        raise HTTPException(400, "Job title required.")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO swarm_jobs (title,spec,repo,branch,autonomy,scope,paths,agent_count,status) "
        "VALUES (?,?,?,?,?,?,?,?,'proposed')",
        (body.title.strip(), body.spec, body.repo, body.branch or "dev", body.autonomy,
         body.scope or "project", json.dumps(body.paths or []), body.agent_count))
    conn.commit()
    jid = cur.lastrowid
    scope_note = ""
    if body.scope and body.scope != "project" and body.paths:
        scope_note = f" Scoped to {body.scope}: {', '.join(body.paths)}."
    conn.execute("INSERT INTO swarm_events (job_id,agent,kind,content) VALUES (?,?,?,?)",
                 (jid, "system", "system", "Job proposed." + scope_note))
    conn.commit()
    row = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (jid,)).fetchone()
    conn.close()
    return _job_dict(row)


@router.get("/api/github/jobs/{jid}")
def get_job(jid: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Job not found")
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM swarm_events WHERE job_id=? ORDER BY id", (jid,)).fetchall()]
    questions = [dict(r) for r in conn.execute(
        "SELECT * FROM swarm_questions WHERE job_id=? ORDER BY id", (jid,)).fetchall()]
    children = [dict(r) for r in conn.execute(
        "SELECT id,title,status,scope,paths FROM swarm_jobs WHERE parent_id=? ORDER BY id", (jid,)).fetchall()]
    conn.close()
    d = _job_dict(row)
    d["events"] = events
    d["questions"] = questions
    d["children"] = children
    return d


@router.patch("/api/github/jobs/{jid}")
def update_job(jid: int, body: dict):
    if "paths" in body and isinstance(body["paths"], list):
        body["paths"] = json.dumps(body["paths"])
    fields = {k: v for k, v in body.items()
              if k in ("title", "spec", "repo", "branch", "autonomy", "status",
                       "cron_enabled", "cron_interval", "scope", "paths", "agent_count")}
    if not fields:
        raise HTTPException(400, "Nothing to update.")
    sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=datetime('now')"
    conn = get_conn()
    conn.execute(f"UPDATE swarm_jobs SET {sets} WHERE id=?", (*fields.values(), jid))
    conn.commit()
    row = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (jid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Job not found")
    return _job_dict(row)


@router.delete("/api/github/jobs/{jid}")
def delete_job(jid: int):
    conn = get_conn()
    conn.execute("DELETE FROM swarm_jobs WHERE id=?", (jid,))
    conn.execute("DELETE FROM swarm_events WHERE job_id=?", (jid,))
    conn.execute("DELETE FROM swarm_questions WHERE job_id=?", (jid,))
    conn.commit()
    conn.close()
    return {"ok": True}


class AnswerIn(BaseModel):
    answer: str


@router.post("/api/github/questions/{qid}/answer")
def answer_question(qid: int, body: AnswerIn):
    conn = get_conn()
    q = conn.execute("SELECT * FROM swarm_questions WHERE id=?", (qid,)).fetchone()
    if not q:
        conn.close(); raise HTTPException(404, "Question not found")
    conn.execute("UPDATE swarm_questions SET answer=?, status='answered', answered_at=datetime('now') WHERE id=?",
                 (body.answer, qid))
    conn.execute("INSERT INTO swarm_events (job_id,agent,kind,content) VALUES (?,?,?,?)",
                 (q["job_id"], "you", "answer", body.answer))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── User final approval — only YOU approve/reject; reject needs a comment ────
@router.post("/api/github/jobs/{jid}/approve")
def approve_job(jid: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Job not found")
    conn.execute("UPDATE swarm_jobs SET decision='approved', status='approved', "
                 "updated_at=datetime('now') WHERE id=?", (jid,))
    conn.execute("INSERT INTO swarm_events (job_id,agent,kind,content) VALUES (?,?,?,?)",
                 (jid, "you", "system", "APPROVED by you. Ready to promote dev → master → retail."))
    conn.commit(); conn.close()
    return {"ok": True, "decision": "approved"}


class RejectIn(BaseModel):
    comment: str


@router.post("/api/github/jobs/{jid}/reject")
def reject_job(jid: int, body: RejectIn):
    if not (body.comment or "").strip():
        raise HTTPException(400, "A reject comment (what's wrong) is required.")
    conn = get_conn()
    row = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Job not found")
    conn.execute("UPDATE swarm_jobs SET decision='rejected', decision_comment=?, status='paused', "
                 "updated_at=datetime('now') WHERE id=?", (body.comment.strip(), jid))
    conn.execute("INSERT INTO swarm_events (job_id,agent,kind,content) VALUES (?,?,?,?)",
                 (jid, "you", "comment", "REJECTED: " + body.comment.strip()))
    conn.commit(); conn.close()
    return {"ok": True, "decision": "rejected"}


# ── System agent tasks (install/configure deps the swarm needs) ──────────────
@router.get("/api/github/jobs/{jid}/system-tasks")
def list_system_tasks(jid: int):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM swarm_system_tasks WHERE job_id=? ORDER BY id", (jid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


class SystemTaskIn(BaseModel):
    job_id: Optional[int] = None
    request: str
    command: Optional[str] = ""


@router.post("/api/github/system-tasks")
def create_system_task(body: SystemTaskIn):
    """Record a system install/config request from the swarm. Execution is gated to
    Phase 2 (the system agent runs it, verifies, then signals the swarm to resume)."""
    if not body.request.strip():
        raise HTTPException(400, "request required")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO swarm_system_tasks (job_id,request,command,status) VALUES (?,?,?,'requested')",
        (body.job_id, body.request.strip(), body.command))
    conn.commit()
    if body.job_id:
        conn.execute("INSERT INTO swarm_events (job_id,agent,kind,content) VALUES (?,?,?,?)",
                     (body.job_id, "system-agent", "system",
                      "System install requested: " + body.request.strip()))
        conn.commit()
    row = conn.execute("SELECT * FROM swarm_system_tasks WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@router.post("/api/github/system-tasks/{tid}/approve")
def approve_system_task(tid: int):
    """You approve the exact command; it then executes, verifies, and resumes the swarm.
    Ask-before-every-command: nothing runs until this endpoint is hit."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM swarm_system_tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "System task not found")
    if row["status"] not in ("requested", "failed"):
        raise HTTPException(400, f"Task is '{row['status']}'.")
    conn = get_conn()
    conn.execute("UPDATE swarm_system_tasks SET status='approved', updated_at=datetime('now') WHERE id=?", (tid,))
    conn.commit(); conn.close()
    if row["job_id"]:
        _swarm_event(row["job_id"], "you", "system", f"Approved system command: {row['command']}")
    threading.Thread(target=swarm.run_system_task, args=(tid,), daemon=True,
                     name=f"systask-{tid}").start()
    return {"ok": True, "message": "Approved — running & verifying; watch the timeline."}


@router.post("/api/github/system-tasks/{tid}/reject")
def reject_system_task(tid: int):
    conn = get_conn()
    row = conn.execute("SELECT job_id, command FROM swarm_system_tasks WHERE id=?", (tid,)).fetchone()
    conn.execute("UPDATE swarm_system_tasks SET status='failed', report='Rejected by user', "
                 "updated_at=datetime('now') WHERE id=?", (tid,))
    conn.commit(); conn.close()
    if row and row["job_id"]:
        _swarm_event(row["job_id"], "you", "comment", f"Rejected system command: {row['command']}")
        _set_job_status(row["job_id"], "paused", "System command rejected")
    return {"ok": True}


class AskSystemIn(BaseModel):
    need: str


@router.post("/api/github/jobs/{jid}/ask-system")
def ask_system(jid: int, body: AskSystemIn):
    """Manually ask the system agent to propose a command for a stated need."""
    if not body.need.strip():
        raise HTTPException(400, "Describe what's needed.")
    threading.Thread(target=swarm.propose_system_task, args=(jid, body.need.strip()),
                     daemon=True, name=f"ask-system-{jid}").start()
    return {"ok": True, "message": "System agent is proposing a command — watch the timeline."}


@router.post("/api/github/jobs/{jid}/run")
def run_job(jid: int):
    """Launch (or resume) the swarm engine on this job in a background thread."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (jid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Job not found")
    if swarm.is_running(jid):
        return {"ok": True, "message": "Already running — watch the timeline."}
    started = swarm.start_job(jid)
    return {"ok": started, "message": "Swarm started — planner is working. Watch the timeline."
            if started else "Already running."}


# ── Promote an APPROVED job: dev → master → retail (user-triggered) ──────────
# The shared git helper _gitc lives in _base (also used by repos' setup-own).


# ── Retail (PUBLIC branch) scrub lives in app/retail_scrub.py ────────────────
# (imported lazily in promote_job; that module is itself dropped from retail so the
# public branch never ships the real identifiers it maps from).


@router.post("/api/github/jobs/{jid}/promote")
def promote_job(jid: int, body: dict = None):
    """Promote an approved job's dev work: merge dev→master (+push), then resync +
    re-genericize retail (+push). The running app keeps old code until you restart."""
    body = body or {}
    conn = get_conn()
    row = conn.execute("SELECT * FROM swarm_jobs WHERE id=?", (jid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Job not found")
    if row["decision"] != "approved":
        raise HTTPException(400, "Approve the job first — only you can approve.")
    steps = []

    def log_step(name, rc, out):
        steps.append({"step": name, "ok": rc == 0, "detail": out[:300]})

    # 1. dev must be clean (all swarm changes committed)
    rc, out = _gitc(REPO_DEV, "status", "--porcelain")
    if out.strip():
        _gitc(REPO_DEV, "add", "-A")
        _gitc(REPO_DEV, "commit", "-m", f"swarm job #{jid}: finalize")
    # 2. master may be dirty with UNRELATED concurrent work (other tabs being built).
    #    If the swarm's changes don't overlap those files, safely stash them, merge,
    #    and restore afterwards. If they overlap, refuse and say exactly what's blocking.
    stashed = False
    rc, dirty = _gitc(REPO_MASTER, "status", "--porcelain")
    dirty_files = {ln[3:].strip() for ln in dirty.splitlines() if ln.strip()}
    if dirty_files:
        rc, devfiles = _gitc(REPO_MASTER, "diff", "--name-only", "master...dev")
        dev_files = {f for f in devfiles.split() if f}
        overlap = dirty_files & dev_files
        if overlap:
            raise HTTPException(409, "master has uncommitted changes that overlap this promotion "
                                     f"({', '.join(sorted(overlap))}). Commit or stash them first.")
        rc, out = _gitc(REPO_MASTER, "stash", "push", "-u", "-m", f"promote-job-{jid} autostash")
        stashed = rc == 0 and "No local changes" not in out
        log_step("stash unrelated work", rc, out)
        if not stashed:
            raise HTTPException(409, "Could not stash master's uncommitted changes — commit/stash "
                                     f"them manually, then promote. {out[:200]}")
    # 3. merge dev → master
    rc, out = _gitc(REPO_MASTER, "merge", "dev", "--no-edit")
    log_step("merge dev→master", rc, out)
    if rc != 0:
        _gitc(REPO_MASTER, "merge", "--abort")
        if stashed:
            _gitc(REPO_MASTER, "stash", "pop")   # restore the unrelated work
        _swarm_event(jid, "system", "error", "Promote failed at merge; master unchanged.\n" + out)
        raise HTTPException(409, f"Merge conflict — aborted. master unchanged. {out[:200]}")
    # 4. push master
    rc, out = _gitc(REPO_MASTER, "push", "origin", "master"); log_step("push master", rc, out)
    # 4b. restore the unrelated work we stashed (no overlap → clean pop)
    if stashed:
        rc, out = _gitc(REPO_MASTER, "stash", "pop")
        log_step("restore stashed work", rc, out)
        if rc != 0:
            _swarm_event(jid, "system", "error",
                         "Stashed work could not auto-restore — recover it with `git stash pop` "
                         f"in {REPO_MASTER}. {out[:200]}")
    # 5. resync retail to master, scrub for PUBLIC release, republish as a clean
    #    parentless commit. retail must carry no real IPs/domains/identity/private
    #    docs, AND none of master's history (which still holds them).
    rc, out = _gitc(REPO_RETAIL, "reset", "--hard", "master"); log_step("retail reset→master", rc, out)
    import retail_scrub  # lazy: this module is dropped from retail, so import only here
    try:
        for line in retail_scrub.genericize_retail_tree(REPO_RETAIL):
            log_step("retail scrub", 0, line)
    except Exception as e:
        log_step("retail genericize", 1, str(e))
    _gitc(REPO_RETAIL, "add", "-A")
    # SAFETY GATE: never publish if any identifier survived the scrub.
    leaks = retail_scrub.verify_retail_clean(REPO_RETAIL)
    if leaks:
        log_step("retail VERIFY", 1, "LEAK — retail NOT pushed: " + ", ".join(leaks[:12]))
        _swarm_event(jid, "system", "error",
                     "Retail publish BLOCKED — identifiers survived the scrub in: "
                     + ", ".join(leaks[:20]) + ". Update retail_scrub.RETAIL_REPLACEMENTS/RETAIL_DROP.")
    else:
        log_step("retail VERIFY", 0, "clean — no identifiers survived the scrub")
        # Publish the scrubbed tree as a PARENTLESS commit so master's history (which
        # still contains the real values) never reaches the public branch.
        rc, tree = _gitc(REPO_RETAIL, "write-tree")
        rc2, commit = _gitc(REPO_RETAIL, "commit-tree", tree.strip(), "-m",
                            f"Store Command Center — public release (genericized, job #{jid})")
        if rc2 == 0 and commit.strip():
            rc, out = _gitc(REPO_RETAIL, "reset", "--hard", commit.strip())
            log_step("retail orphan commit", rc, out)
            # retail history is replaced each promote → force (lease guards a concurrent push).
            rc, out = _gitc(REPO_RETAIL, "push", "--force-with-lease", "origin", "retail")
            log_step("push retail", rc, out)
        else:
            log_step("retail commit-tree", 1, commit)

    # The merge already wrote the new code to the master worktree on disk, so the LIVE
    # app just needs a restart to load it (no GitHub pull needed for this instance).
    will_restart = bool(get_swarm_config().get("restart_after_promote"))
    _set_job_status(jid, "done",
                    "Promoted dev → master → retail." + (" Restarting…" if will_restart else " Restart to run the new code."))
    _swarm_event(jid, "you", "system",
                 "Promoted: " + "; ".join(f"{s['step']}={'ok' if s['ok'] else 'FAIL'}" for s in steps))
    if will_restart:
        _restart_live()
    return {"ok": True, "steps": steps, "restarting": will_restart,
            "note": ("Restarting the live app to load the promoted code…" if will_restart
                     else "Restart the store (Settings → Restart Server, or the Restart button here) to load it.")}


def _restart_live():
    """Restart the live app so it runs freshly-promoted code. Delayed slightly so the
    HTTP response returns first (mirrors system.py's restart)."""
    import threading as _t, shlex, subprocess as _sp
    def _do():
        if RESTART_CMD:
            _sp.Popen(shlex.split(RESTART_CMD))
        else:  # no supervisor cmd → re-exec in place
            import os, sys
            os.execv(sys.executable, [sys.executable] + sys.argv)
    _t.Timer(1.0, _do).start()


@router.post("/api/github/restart-live")
def restart_live():
    """Restart the live app now (loads any promoted code sitting in the master worktree)."""
    _restart_live()
    return {"ok": True, "message": "Restarting… the app will be back in a few seconds."}


def _swarm_event(jid, agent, kind, content):
    conn = get_conn()
    conn.execute("INSERT INTO swarm_events (job_id,agent,kind,content) VALUES (?,?,?,?)",
                 (jid, agent, kind, content))
    conn.commit(); conn.close()


def _set_job_status(jid, status, msg):
    conn = get_conn()
    conn.execute("UPDATE swarm_jobs SET status=?, progress_msg=?, updated_at=datetime('now') WHERE id=?",
                 (status, msg, jid))
    conn.commit(); conn.close()
