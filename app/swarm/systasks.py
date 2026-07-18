"""Dev Swarm — the system agent.

Turns a NEED (a missing tool/library/service) into a single, verifiable shell command
and files it as a 'requested' task. Nothing runs until the user approves; execution +
verify + job-resume happens in run_system_task.

Layering: depends on ._base (state/config) and .llm (turn + parsing). It resumes a job
via engine.start_job, which is imported LAZILY inside run_system_task to break the
engine⇄systasks import cycle.
"""
import json
import re
import subprocess

from db import get_conn
from deps import get_prompt
from config import REPO_DEV

from ._base import _config, _ev, _set, _job
from .llm import _model_pool, _turn, _extract_json


SYSTEM_SYS = (
    "You are the SYSTEM AGENT for a local-model dev swarm. Given a NEED or an error, propose "
    "the SINGLE shell command that installs/fixes it, plus a verify command that proves it "
    "worked. Prefer PROJECT-LOCAL installs — for Python use `./venv/bin/pip install <pkg>`, "
    "for Node use `npm install <pkg>`. Never propose destructive or interactive commands. "
    'Respond in STRICT JSON: {"command": "...", "reason": "one line", "verify": "shell command '
    'that exits 0 if the need is satisfied"}.')


def _system_task(task_id) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM swarm_system_tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _set_system_task(task_id, **f):
    sets = ", ".join(f"{k}=?" for k in f) + ", updated_at=datetime('now')"
    conn = get_conn()
    conn.execute(f"UPDATE swarm_system_tasks SET {sets} WHERE id=?", (*f.values(), task_id))
    conn.commit(); conn.close()


def propose_system_task(job_id: int, need: str, model: str = None) -> dict:
    """System-agent turn: turn a NEED into a concrete, verifiable command and file it as a
    'requested' task (nothing runs — the user must approve). Gates the job on approval."""
    cfg = _config()
    model = model or (cfg.get("system_agent") or {}).get("model") or (_model_pool(cfg) or [""])[0]
    out = _turn(model, get_prompt('swarm_system'), f"NEED: {need}", max_tokens=800)
    data = _extract_json(out)

    def _field(key):
        v = data.get(key)
        if v:
            return str(v).strip()
        m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', out)   # salvage from imperfect JSON
        return (m.group(1).encode().decode("unicode_escape") if m else "").strip()

    command = _field("command")
    reason = _field("reason")
    verify = _field("verify")
    if not command:
        m = re.search(r"`([^`\n]+)`", out)   # last resort: a backtick command
        command = m.group(1).strip() if m else ""
    if not command:
        _ev(job_id, "system-agent", "error", f"Could not derive a command for: {need}\n{out[:300]}")
        return {}
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO swarm_system_tasks (job_id,request,command,status,report) VALUES (?,?,?,'requested',?)",
        (job_id, need, command, json.dumps({"reason": reason, "verify": verify})))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    _ev(job_id, "system-agent", "system",
        f"Proposes: `{command}`  —  {reason}  (awaiting your approval)", model=model)
    _set(job_id, status="awaiting_system", progress_msg="System install proposed — approve it")
    return _system_task(tid)


def run_system_task(task_id: int) -> dict:
    """Execute an APPROVED system command (ask-before-every-command means this is only ever
    called after the user approves), verify it, report, and resume the job."""
    from .engine import start_job   # lazy: breaks the engine⇄systasks import cycle
    t = _system_task(task_id)
    if not t:
        return {"ok": False, "error": "not found"}
    if t["status"] != "approved":
        return {"ok": False, "error": f"task is '{t['status']}', not approved"}
    meta = {}
    try:
        meta = json.loads(t.get("report") or "{}")
    except Exception:
        pass
    verify = meta.get("verify", "")
    _set_system_task(task_id, status="installing")
    if t.get("job_id"):
        _ev(t["job_id"], "system-agent", "system", f"Running: `{t['command']}`")

    def _sh(cmd, timeout=900):
        try:
            r = subprocess.run(["bash", "-lc", cmd], cwd=REPO_DEV, capture_output=True,
                               text=True, timeout=timeout)
            return r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            return 124, "timed out"
        except Exception as e:
            return 1, str(e)

    rc, out = _sh(t["command"])
    ok = rc == 0
    vrc = None
    if ok and verify:
        vrc, vout = _sh(verify, timeout=120)
        out += f"\n\n--- verify ({verify}) ---\n{vout}"
        ok = vrc == 0
    status = "verified" if (ok and verify) else ("done" if ok else "failed")
    report = f"$ {t['command']}\n{out[:4000]}"
    _set_system_task(task_id, status=status, report=report)
    if t.get("job_id"):
        _ev(t["job_id"], "system-agent", "test",
            ("✅ " if ok else "❌ ") + f"{status}: {t['command']}")
        if ok:
            # Only resume once EVERY proposed system task for this job is resolved.
            conn = get_conn()
            pending = conn.execute(
                "SELECT COUNT(*) c FROM swarm_system_tasks WHERE job_id=? AND "
                "status IN ('requested','approved','installing')", (t["job_id"],)).fetchone()["c"]
            conn.close()
            if pending == 0:
                _ev(t["job_id"], "system-agent", "system", "All installs verified — resuming the swarm.")
                job = _job(t["job_id"])
                if job and job.get("status") in ("awaiting_system", "paused"):
                    _set(t["job_id"], status="coding", progress_msg="Resuming after install")
                    start_job(t["job_id"])
            else:
                _ev(t["job_id"], "system-agent", "system",
                    f"Install verified — {pending} more await your approval.")
        else:
            _set(t["job_id"], status="paused", progress_msg="System install failed — see report")
    return {"ok": ok, "status": status}
