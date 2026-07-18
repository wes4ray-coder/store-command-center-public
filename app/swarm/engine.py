"""Dev Swarm — the stage machine + background driver.

Owns the run state (_running set), the per-stage prompts, the stage functions
(architect/planning/coding/reviewing/testing), the _drive loop, and the public
entrypoints start_job / is_running / reconcile_on_start.

Layering (top of the package graph): depends on ._base, .llm, .workspace, .systasks.
"""
import json
import subprocess
import threading
from pathlib import Path

from db import get_conn
from deps import get_prompt
from config import REPO_DEV

from ._base import _ev, _set, _job, _config
from .llm import _roster, load_and_pin, _turn, _extract_json, _parse_vote
from .workspace import (_git_dev, _scoped_paths, _path_allowed, _parse_files,
                        _read_scoped_context, _fallback_single_file, _repo_tree, _read_files)
from .systasks import propose_system_task

_running: set[int] = set()
_running_lock = threading.Lock()

MAX_CODE_ROUNDS = 3   # coding↔review/test retries before pausing for the human


# ─────────────────────────────────────────────────────────────────────────────
# Turns — stage prompts (defaults; live copies are editable via the prompt registry)
# ─────────────────────────────────────────────────────────────────────────────
PLANNER_SYS = (
    "You are the PLANNER in a local-model dev swarm. Given a job, produce a short, "
    "concrete plan (numbered steps). If — and only if — the ask is genuinely ambiguous, "
    "or it implies a big change, a file split, or a change of direction, ask the human "
    "clarifying questions. ONLY list system_needs when the work genuinely requires a tool/"
    "library/service that is not already available (e.g. a new pip/npm package the code "
    "imports); for ordinary file edits or code changes leave system_needs EMPTY. Respond in "
    'STRICT JSON: {"plan": ["step 1", ...], "questions": ["q1", ...], "system_needs": [...]}. '
    "Use empty lists when not applicable.")

SCOUT_SYS = (
    "You are scouting a codebase before planning. Given a request and the repo file listing, "
    "choose up to 6 EXISTING files whose CONTENT you should read to plan accurately — e.g. where "
    "routes/tabs are registered, config, the DB schema, or a similar existing feature to mirror. "
    'Return STRICT JSON: {"files_to_read": ["real/path", ...]}. Only paths from the listing.')

ARCHITECT_SYS = (
    "You are the ARCHITECT in a local-model dev swarm. Turn a possibly-vague request into an "
    "actionable plan. Coders can only rewrite WHOLE files, so a big multi-file feature must be "
    "split into small, independently-buildable pieces. Return STRICT JSON with keys:\n"
    '  "enhanced_spec": a clear, detailed restatement (goal, constraints, acceptance criteria);\n'
    '  "questions": [only genuinely-blocking clarifications — usually []];\n'
    '  "atomic": true if this is ONE focused change to a single file/area, false if it needs several files;\n'
    '  "plan": [numbered steps]  (when atomic);\n'
    '  "subtasks": [ {"title": "...", "spec": "detailed", "scope": "file"|"folder", "paths": ["rel/path"]} ] '
    "(when NOT atomic — 2-6 focused pieces, each scoped to specific files small enough to rewrite whole).\n"
    "Base paths on the repo when given. Do not invent unrelated work.")

CODER_SYS = (
    "You are a CODER in a local-model dev swarm. Implement the plan by rewriting whole "
    "files. Output ONLY changed files, each EXACTLY in this format:\n"
    "<<<FILE relative/path>>>\n<full new file content>\n<<<END>>>\n\n"
    "Example:\n<<<FILE docs/note.md>>>\n# Title\n\nSome body text.\n<<<END>>>\n\n"
    "Rules: no prose, no ``` code fences, no explanation outside the blocks. Emit the "
    "COMPLETE file content (not a diff). Keep changes minimal and within the job's scope.")

_CODER_RETRY = ("\n\nIMPORTANT: your previous reply had no valid <<<FILE ...>>> ... <<<END>>> "
                "blocks. Re-emit the file(s) using EXACTLY that format and nothing else.")

REVIEWER_SYS = (
    "You are a REVIEWER in a local-model dev swarm reviewing ANOTHER agent's change (never "
    "your own). Judge correctness, clarity, and whether it satisfies the job. Respond in "
    'STRICT JSON: {"vote": "approve"|"reject", "comments": "specific feedback"}.')

AUDITOR_SYS = (
    "You are an AUDITOR in a local-model dev swarm auditing ANOTHER agent's change (never "
    "your own) for SECURITY and QUALITY: injection, leaked secrets, unsafe/dangerous calls, "
    "breaking changes, missing error handling. Respond in STRICT JSON: "
    '{"vote": "approve"|"reject", "comments": "specific risks, or \'no issues found\'"}.')


def _spawn_subtasks(parent: dict, subtasks: list) -> list[int]:
    """Create scoped child jobs from an architect decomposition."""
    ids = []
    conn = get_conn()
    for st in subtasks[:8]:
        title = (st.get("title") or "").strip()[:200]
        if not title:
            continue
        scope = st.get("scope") if st.get("scope") in ("file", "folder", "project") else "file"
        paths = st.get("paths") or []
        cur = conn.execute(
            "INSERT INTO swarm_jobs (title,spec,repo,branch,autonomy,scope,paths,parent_id,status) "
            "VALUES (?,?,?,?,?,?,?,?,'proposed')",
            (title, st.get("spec") or "", parent.get("repo"), parent.get("branch") or "dev",
             parent.get("autonomy"), scope, json.dumps(paths), parent["id"]))
        ids.append(cur.lastrowid)
    conn.commit(); conn.close()
    return ids


def _stage_architect(job, roster, cfg):
    """Turn a possibly-vague request into an actionable plan: enhance the spec, decide
    atomic vs. multi-file, decompose big features into scoped child jobs, and raise
    clarifying questions only for real ambiguity. Honors autonomy (auto proceeds/auto-runs
    subtasks; gate/step shows it and waits for you)."""
    jid = job["id"]
    autonomy = job.get("autonomy") or cfg["autonomy"]
    _set(jid, status="planning", current_agent="architect", progress_msg="Architecting…")
    _ev(jid, "architect", "system", "Enhancing the request and planning.", model=roster["planner"])
    user = (f"REQUEST: {job['title']}\n\nDETAILS:\n{job.get('spec') or '(none)'}\n\n"
            f"REPO: {job.get('repo') or ''}  BRANCH: {job.get('branch')}")
    paths = _scoped_paths(job)
    if paths:
        user += f"\nUSER-SUGGESTED PATHS: {', '.join(paths)}"
    tree = _repo_tree()
    user += "\n\nREPO STRUCTURE (scope subtasks to REAL paths from this — do NOT invent src/… paths):\n" + tree

    # Pass 1 — SCOUT: pick real files to read, then read them, so the plan reflects the
    # actual code. Always include a few anchor files (wiring + a representative router +
    # the frontend entry) so context is solid even if the scout picks poorly.
    _set(jid, progress_msg="Reading code for context…")
    anchors = [p for p in ("app/main.py", "app/routers/portal.py", "static/index.html")
               if (Path(REPO_DEV) / p).is_file()]
    want = list(anchors)
    try:
        scout = _extract_json(_turn(roster["planner"], get_prompt('swarm_scout'),
                                    f"REQUEST: {job['title']}\nDETAILS: {job.get('spec') or ''}\n\nREPO FILES:\n{tree}",
                                    max_tokens=500))
        for f in (scout.get("files_to_read") or []):
            if f and f not in want:
                want.append(f)
    except Exception as e:
        logger.warning("swarm scout failed: %s", e)
    file_ctx, read = _read_files(want)
    _ev(jid, "architect", "system",
        ("Read for context: " + ", ".join(read)) if read else "No readable context files.",
        model=roster["planner"])
    if file_ctx:
        user += "\n\nRELEVANT EXISTING CODE (plan against this real code):\n" + file_ctx

    # Pass 2 — ARCHITECT: enhance + decompose with the real code in mind.
    out = _turn(roster["planner"], get_prompt('swarm_architect'), user, max_tokens=2500)
    data = _extract_json(out)
    enhanced = (data.get("enhanced_spec") or "").strip()
    questions = [q for q in (data.get("questions") or []) if q][:5]
    atomic = data.get("atomic", True)
    subtasks = data.get("subtasks") or []
    plan = data.get("plan") or []
    if enhanced:
        _set(jid, enhanced_spec=enhanced)
        _ev(jid, "architect", "plan", "ENHANCED SPEC:\n" + enhanced, model=roster["planner"])

    # 1) Clarifying questions (genuine ambiguity) — gate unless fully autonomous
    if questions and autonomy != "auto":
        conn = get_conn()
        for q in questions:
            conn.execute("INSERT INTO swarm_questions (job_id,agent,question) VALUES (?,?,?)", (jid, "architect", q))
        conn.commit(); conn.close()
        _ev(jid, "architect", "question", "\n".join(f"• {q}" for q in questions))
        _set(jid, status="awaiting_input", progress_msg="Needs your answers")
        return "stop"

    # 2) Decompose a multi-file feature into scoped child jobs
    if not atomic and subtasks:
        ids = _spawn_subtasks(job, subtasks)
        _ev(jid, "architect", "system",
            f"Broke this into {len(ids)} subtasks:\n" + "\n".join(f"• {s.get('title')}" for s in subtasks[:8]))
        _set(jid, status="decomposed", plan=json.dumps([s.get("title") for s in subtasks]),
             progress_msg=f"Decomposed into {len(ids)} subtasks")
        if autonomy == "auto":
            for cid in ids:
                start_job(cid)
            _ev(jid, "architect", "system", "Auto-running subtasks (autonomy=auto).")
        else:
            _ev(jid, "architect", "system", "Review the subtasks on the board and Run them (gate/step mode).")
        return "stop"

    # 3) Atomic → keep the plan, maybe surface system installs
    _set(jid, plan=json.dumps(plan))
    if plan:
        _ev(jid, "architect", "plan", "PLAN:\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan)),
            model=roster["planner"])
    sys_cfg = cfg.get("system_agent") or {}
    needs = [n for n in (data.get("system_needs") or []) if n][:4]
    if needs and sys_cfg.get("enabled", True):
        for need in needs:
            propose_system_task(jid, need)
        return "stop"

    # 4) Gate the plan for your approval in gate/step mode (auto just proceeds)
    if autonomy in ("gate", "step"):
        conn = get_conn()
        conn.execute("INSERT INTO swarm_questions (job_id,agent,question) VALUES (?,?,?)",
                     (jid, "architect", "Enhanced spec + plan ready (above). Reply 'go' to build it, or describe changes."))
        conn.commit(); conn.close()
        _set(jid, status="awaiting_input", progress_msg="Approve the plan to build")
        return "stop"
    return "coding"


def _stage_planning(job, roster, cfg):
    jid = job["id"]
    _set(jid, status="planning", current_agent="planner", progress_msg="Planning…")
    _ev(jid, "planner", "system", "Planning the job.", model=roster["planner"])
    user = f"JOB: {job['title']}\n\nDETAILS:\n{job.get('spec') or '(none)'}\n\nSCOPE: {job.get('scope')}"
    paths = _scoped_paths(job)
    if paths:
        user += f"\nTARGET PATHS: {', '.join(paths)}"
    out = _turn(roster["planner"], get_prompt('swarm_planner'), user, max_tokens=2000)
    data = _extract_json(out)
    plan = data.get("plan") or []
    questions = [q for q in (data.get("questions") or []) if q][:5]
    _set(jid, plan=json.dumps(plan))
    _ev(jid, "planner", "plan", "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan)) or out,
        model=roster["planner"])
    # Gate on questions unless fully autonomous
    if questions and cfg["autonomy"] != "auto":
        conn = get_conn()
        for q in questions:
            conn.execute("INSERT INTO swarm_questions (job_id,agent,question) VALUES (?,?,?)",
                         (jid, "planner", q))
        conn.commit(); conn.close()
        _ev(jid, "planner", "question", "\n".join(f"• {q}" for q in questions))
        _set(jid, status="awaiting_input", progress_msg="Waiting for your answers")
        return "stop"
    # System needs → the system agent proposes commands; user approves before anything runs
    sys_cfg = cfg.get("system_agent") or {}
    needs = [n for n in (data.get("system_needs") or []) if n][:4]
    if needs and sys_cfg.get("enabled", True):
        for need in needs:
            propose_system_task(jid, need)
        return "stop"   # job is now awaiting_system (set by propose_system_task)
    return "coding"


def _answered_context(jid) -> str:
    conn = get_conn()
    qs = conn.execute("SELECT question,answer FROM swarm_questions WHERE job_id=? AND status='answered'", (jid,)).fetchall()
    conn.close()
    return "\n".join(f"Q: {q['question']}\nA: {q['answer']}" for q in qs)


def _stage_coding(job, roster, cfg, feedback=""):
    jid = job["id"]
    _set(jid, status="coding", current_agent="coder", progress_msg="Writing code…")
    plan = job.get("plan") or "[]"
    ctx = _read_scoped_context(job)
    answers = _answered_context(jid)
    user = (f"JOB: {job['title']}\nDETAILS: {job.get('enhanced_spec') or job.get('spec') or ''}\nPLAN: {plan}\n"
            f"SCOPE: {job.get('scope')} PATHS: {', '.join(_scoped_paths(job)) or 'project'}\n")
    if answers:
        user += f"\nCLARIFICATIONS:\n{answers}\n"
    if feedback:
        user += f"\nREVIEW/TEST FEEDBACK to address:\n{feedback}\n"
    user += f"\nCURRENT FILE CONTENTS:\n{ctx}\n\nReturn the full updated file(s)."
    files = []
    out = ""
    for attempt in range(2):
        sys_prompt = get_prompt('swarm_coder') + (_CODER_RETRY if attempt else "")
        out = _turn(roster["coder"], sys_prompt, user, max_tokens=6000)
        files = _parse_files(out)
        if files:
            break
    if not files:
        files = _fallback_single_file(out, job)   # salvage single-file jobs
    if not files:
        _ev(jid, "coder", "error", "No parseable <<<FILE>>> blocks in coder output (after retry).",
            model=roster["coder"])
        _set(jid, status="paused", progress_msg="Coder produced no usable change")
        return "stop"
    applied, rejected = [], []
    for path, content in files:
        if not _path_allowed(path, job):
            rejected.append(path); continue
        fp = Path(REPO_DEV) / path.lstrip("/")
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        applied.append(path)
    if rejected:
        _ev(jid, "coder", "system", f"Skipped out-of-scope paths: {', '.join(rejected)}")
    if not applied:
        _set(jid, status="paused", progress_msg="All proposed edits were out of scope")
        return "stop"
    _git_dev("add", *applied)
    _git_dev("commit", "-m", f"swarm job #{jid}: {job['title']}")
    _ev(jid, "coder", "diff", "Edited on dev branch: " + ", ".join(applied), model=roster["coder"])
    return "reviewing"


def _stage_reviewing(job, roster, cfg):
    jid = job["id"]
    reviewers = roster.get("reviewers") or [roster["reviewer"]]
    _set(jid, status="reviewing", current_agent="reviewers",
         progress_msg=f"Reviewing ({len(reviewers)} voter{'s' if len(reviewers) > 1 else ''})…")
    rc, diff = _git_dev("show", "--stat", "--patch", "HEAD", timeout=30)
    approvals = rejects = 0
    feedback = []
    for i, rm in enumerate(reviewers):
        # alternate a correctness reviewer and a security/quality auditor across the panel
        is_audit = (i % 2 == 1)
        role = "auditor" if is_audit else "reviewer"
        sys_p = get_prompt('swarm_auditor') if is_audit else get_prompt('swarm_reviewer')
        out = _turn(rm, sys_p, f"JOB: {job['title']}\n\nDIFF:\n{diff[:9000]}", max_tokens=1500)
        data = _extract_json(out)
        vote = _parse_vote(data, out)
        comments = data.get("comments") or out
        if not isinstance(comments, str):
            comments = json.dumps(comments)[:600]
        note = " (solo self-review)" if (roster.get("self_review") and rm == roster["coder"]) else ""
        _ev(jid, role, "vote", comments + note, vote=vote, model=rm)
        if vote == "approve":
            approvals += 1
        else:
            rejects += 1
            feedback.append(f"[{role}] {comments}")
    passed = approvals > rejects   # majority approves
    _ev(jid, "system", "system",
        f"Panel vote: {approvals} approve / {rejects} reject → {'PASS' if passed else 'CHANGES REQUESTED'}")
    return "testing" if passed else ("recode", "\n".join(feedback) or "reviewers requested changes")


def _stage_testing(job, roster, cfg):
    jid = job["id"]
    _set(jid, status="testing", current_agent="tester", progress_msg="Testing…")
    # syntax-check the changed files (safe, fast, no side effects)
    rc, files = _git_dev("show", "--name-only", "--pretty=format:", "HEAD")
    changed = [f for f in files.splitlines() if f.strip()]
    problems = []
    for f in changed:
        fp = Path(REPO_DEV) / f
        if f.endswith(".py"):
            r = subprocess.run(["python3", "-m", "py_compile", str(fp)], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append(f"{f}: {r.stderr.strip()[:300]}")
        elif f.endswith(".js"):
            r = subprocess.run(["node", "--check", str(fp)], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append(f"{f}: {r.stderr.strip()[:300]}")
    if problems:
        _ev(jid, "tester", "test", "❌ FAILED:\n" + "\n".join(problems))
        return ("recode", "Tests failed:\n" + "\n".join(problems))
    _ev(jid, "tester", "test", "✅ Syntax checks passed on: " + (", ".join(changed) or "no files"))
    return "done_stage"


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────
def _drive(jid: int):
    try:
        cfg = _config()
        job = _job(jid)
        if not job:
            return
        autonomy = job.get("autonomy") or cfg["autonomy"]
        n = job.get("agent_count") or cfg.get("agent_count", 3)
        roster = _roster(cfg, n)
        if not roster:
            _ev(jid, "system", "error", "No local models configured — set a model pool in Agents & Models.")
            _set(jid, status="paused", progress_msg="No models configured")
            return
        _ev(jid, "system", "system",
            f"Swarm run — autonomy={autonomy}, agents={n}, coder={roster['coder']}, reviewer={roster['reviewer']}"
            + (" (self-review)" if roster.get("self_review") else ""))

        # Auto-pin the coder model so the first coding turns are fast and it won't
        # auto-unload mid-run (borrow-fallback still covers a failed pin).
        if cfg.get("auto_pin", True) and roster.get("coder"):
            _set(jid, progress_msg=f"Pinning {roster['coder']}…")
            r = load_and_pin(roster["coder"])
            _ev(jid, "system", "system",
                f"Auto-pin {roster['coder']}: " + ("resident @ %s ctx" % r.get("context")
                if r.get("ok") else "could not pin (%s) — will borrow the resident model" % r.get("note")))

        status = job["status"]
        # Fresh start → ARCHITECT (enhance/decompose/plan/questions). Resume → straight to coding.
        if status == "proposed":
            step = _stage_architect(job, roster, cfg)
            if step == "stop":
                return   # gated (questions / plan approval / system install) or decomposed
            job = _job(jid)

        rounds = 0
        feedback = ""
        while rounds < MAX_CODE_ROUNDS:
            rounds += 1
            job = _job(jid)
            r = _stage_coding(job, roster, cfg, feedback)
            if r == "stop":
                return
            if autonomy == "step":
                _set(jid, progress_msg="Coded — click Run to review"); # fallthrough to review anyway for now
            rv = _stage_reviewing(_job(jid), roster, cfg)
            if isinstance(rv, tuple) and rv[0] == "recode":
                feedback = rv[1]; continue
            tv = _stage_testing(_job(jid), roster, cfg)
            if isinstance(tv, tuple) and tv[0] == "recode":
                feedback = tv[1]; continue
            # passed review + test → gate for the human
            _set(jid, status="awaiting_review", current_agent=None,
                 progress=100, progress_msg="Ready for your review + approval")
            _ev(jid, "system", "system",
                "Change is on the dev branch and passed review + syntax tests. "
                "Approve to promote (dev→master→retail) or reject with a comment.")
            return
        _set(jid, status="paused", progress_msg=f"Paused after {MAX_CODE_ROUNDS} rounds — needs your input")
        _ev(jid, "system", "system", f"Stopped after {MAX_CODE_ROUNDS} code/review rounds. Last feedback:\n{feedback}")
    except Exception as e:
        _ev(jid, "system", "error", f"Swarm error: {e}")
        _set(jid, status="failed", error=str(e), progress_msg="Errored — see timeline")
    finally:
        with _running_lock:
            _running.discard(jid)


def start_job(jid: int) -> bool:
    """Launch the driver in a background thread. Returns False if already running."""
    with _running_lock:
        if jid in _running:
            return False
        _running.add(jid)
    threading.Thread(target=_drive, args=(jid,), daemon=True, name=f"swarm-{jid}").start()
    return True


def is_running(jid: int) -> bool:
    with _running_lock:
        return jid in _running


def reconcile_on_start():
    """Any job left mid-run by a restart → paused (in-memory driver state is gone)."""
    conn = get_conn()
    conn.execute("UPDATE swarm_jobs SET status='paused', progress_msg='Interrupted by a server restart' "
                 "WHERE status IN ('planning','coding','reviewing','testing')")
    conn.commit(); conn.close()
