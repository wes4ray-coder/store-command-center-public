"""System control routes (restart, health, backup/restore)."""
import os
import sys
import shlex
import tarfile
import threading
import subprocess
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from deps import *

router = APIRouter()

# ── Backups ──────────────────────────────────────────────────────────────────
# Backups are stored in the store's data folder (config.BACKUP_DIR) so they
# travel with the app. venv / caches / the backups folder itself are excluded.
_BACKUP_SKIP = {"venv", "__pycache__", "backups"}

def _list_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(BACKUP_DIR.glob("store_backup_*.tar.gz"), reverse=True):
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    return out

def _create_backup():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"store_backup_{ts}.tar.gz"
    path = BACKUP_DIR / name

    def _filter(ti):
        parts = ti.name.split("/")
        if any(p in _BACKUP_SKIP for p in parts):
            return None
        if ti.name.endswith((".pyc", ".pyo")):
            return None
        return ti

    with tarfile.open(path, "w:gz") as tar:
        tar.add(BASE, arcname=BASE.name, filter=_filter)
    return {"name": name, "size": path.stat().st_size}

@router.get("/api/system/backups")
def list_backups():
    return {"backups": _list_backups(), "dir": str(BACKUP_DIR)}

@router.post("/api/system/backup")
def create_backup():
    return _create_backup()


@router.post("/api/system/db-backup")
def run_db_backup():
    """Trigger the lean nightly DB snapshot now (local + off-box copy). Same job the
    scheduler runs automatically."""
    import backups
    return backups.run_scheduled_backup()


@router.get("/api/system/db-backup/status")
def db_backup_status():
    import backups
    dests = [str(d) for d in backups._dest_dirs()]
    return {
        "enabled": get_setting("backup_enabled", "1") == "1",
        "last_run": get_setting("backup_last_run", None),
        "last_copies": get_setting("backup_last_copies", None),
        "destinations": dests,
        "off_box": len(dests) > 1,
    }

@router.get("/api/system/backups/{name}/download")
def download_backup(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "Invalid name")
    path = BACKUP_DIR / name
    if not path.exists():
        raise HTTPException(404, "Backup not found")
    return FileResponse(path, filename=name, media_type="application/gzip")

@router.delete("/api/system/backups/{name}")
def delete_backup(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "Invalid name")
    path = BACKUP_DIR / name
    if not path.exists():
        raise HTTPException(404, "Backup not found")
    path.unlink()
    return {"ok": True}

@router.post("/api/system/restore")
def restore_backup(data: dict):
    """Restore a backup over the current install, then restart. Destructive."""
    name = (data or {}).get("name", "")
    if "/" in name or ".." in name or not name:
        raise HTTPException(400, "Invalid name")
    path = BACKUP_DIR / name
    if not path.exists():
        raise HTTPException(404, "Backup not found")
    # Safety copy of the current DB before we overwrite anything.
    _create_backup()
    with tarfile.open(path, "r:gz") as tar:
        try:
            tar.extractall(BASE.parent, filter="data")   # py>=3.12 safe extraction
        except TypeError:
            tar.extractall(BASE.parent)
    threading.Timer(0.5, _do_restart).start()
    return {"ok": True, "message": "Restored — restarting…"}


@router.get("/api/system/info")
def system_info():
    """Basic runtime info, useful when moving the app to a new machine."""
    return {
        "pid": os.getpid(),
        "store_base": STORE_BASE,
        "host": HOST,
        "port": PORT,
        "llm_url": LMSTUDIO_URL,
        "gpu_host": GPU_HOST,
        "restart_cmd": RESTART_CMD or "(re-exec in place)",
    }


def _active_gpu_jobs() -> dict:
    """What GPU generation work is in flight (running or queued), so the UI can warn
    before a restart kills it. Combines the DB (catches queued jobs too) with the
    orchestrator's active_images (catches a running 3D job with no dedicated status)."""
    jobs = []
    try:
        conn = get_conn()
        def _cnt(table, where, label):
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
                if n:
                    jobs.append({"kind": label, "count": int(n)})
            except Exception:
                pass
        _cnt("videos",       "status IN ('queued','generating')",        "video")
        _cnt("video_chains", "status IN ('pending','generating')",       "video chain")
        _cnt("videos",       "audio_status IN ('queued','generating')",  "video sound")
        _cnt("audio_clips",  "status IN ('queued','generating')",        "audio")
        conn.close()
    except Exception:
        pass
    db_total = sum(j["count"] for j in jobs)
    gpu_active = 0
    try:
        gpu_active = int(orch.status().get("active_images", 0) or 0)
    except Exception:
        pass
    # A running 3D job bumps active_images but has no row above — surface it.
    if gpu_active > db_total:
        jobs.append({"kind": "3d / other", "count": gpu_active - db_total})
    total = max(db_total, gpu_active)
    return {"busy": total > 0, "total": total, "jobs": jobs}


@router.get("/api/system/gpu-status")
def system_gpu_status():
    return _active_gpu_jobs()


@router.get("/api/system/logs")
def system_logs(lines: int = 300, level: str = "", q: str = ""):
    """Tail the store log (rotating file at <data-dir>/logs/store.log). Optional level
    filter (ERROR/WARNING/INFO) and text search so you can pinpoint a failure fast."""
    logf = DATA_DIR / "logs" / "store.log"
    if not logf.exists():
        return {"lines": [], "file": str(logf), "note": "No log file yet — logs start on the next server restart."}
    try:
        data = logf.read_text(errors="replace").splitlines()
    except Exception as e:
        return {"lines": [], "file": str(logf), "error": str(e)}
    if level:
        lv = level.upper()
        # ERROR also surfaces WARNING+ ; WARNING surfaces WARNING+ ; else exact-ish
        wanted = {"ERROR": ("ERROR", "CRITICAL"), "WARNING": ("WARNING", "ERROR", "CRITICAL")}.get(lv, (lv,))
        data = [l for l in data if any(f" {w} " in l for w in wanted)]
    if q:
        ql = q.lower()
        data = [l for l in data if ql in l.lower()]
    n = max(10, min(3000, lines))
    # quick error/warn tally over the whole file for the header
    err = sum(1 for l in data[-2000:] if " ERROR " in l or " CRITICAL " in l)
    warn = sum(1 for l in data[-2000:] if " WARNING " in l)
    return {"lines": data[-n:], "file": str(logf), "total": len(data),
            "errors": err, "warnings": warn}


def _do_restart():
    """Restart the server. Runs in a short-delayed background thread so the HTTP
    response is flushed to the client first."""
    if RESTART_CMD:
        # Delegate to an external supervisor command (e.g. systemctl restart).
        subprocess.Popen(shlex.split(RESTART_CMD),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # Universal fallback: replace this process image with a fresh copy.
        # Same PID, no port race, works with or without a supervisor.
        os.execv(sys.argv[0], sys.argv)


@router.post("/api/system/restart")
def system_restart(body: dict = None):
    """Restart the server. Refuses (409) if GPU jobs are in flight unless force=true,
    so a restart doesn't silently kill a running generation (esp. with 2 people/agents)."""
    busy = _active_gpu_jobs()
    if busy["busy"] and not (body or {}).get("force"):
        raise HTTPException(
            status_code=409,
            detail=f"{busy['total']} GPU job(s) running or queued — a restart will kill them. "
                   "Wait for them to finish, or restart with force to override.")
    threading.Timer(0.5, _do_restart).start()
    return {"ok": True, "message": "Restarting…"}


@router.post("/api/system/browser-reset")
def system_browser_reset():
    """Recover the automation browser if Chrome didn't exit cleanly (stale profile lock)."""
    try:
        import browser
        return browser.browser.reset()
    except Exception as e:
        raise HTTPException(500, f"Reset failed: {e}")


# ─── UPDATES (GitHub) ─────────────────────────────────────────────────────────
# Update this install from GitHub. Pick a channel/branch (retail = stable, main =
# latest, dev = experimental), or turn updates off to pin the version. Safe: refuses
# if the working tree has local changes, and only fast-forwards (never clobbers).
_UPDATE_CHANNELS = ["retail", "master", "dev"]


def _git_repo(*args, timeout: int = 60):
    try:
        r = subprocess.run([GIT_BIN, "-C", str(BASE), *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def _updates_on() -> bool:
    return str(get_setting("updates_enabled", "1")).lower() in ("1", "true", "on", "yes")


def _update_remote() -> str:
    """Which remote updates come from: `upstream` when present (set by Settings →
    GitHub → "Make this install yours", which points origin at the USER'S own repo
    and keeps the repo they cloned as upstream), else `origin`."""
    remotes = (_git_repo("remote")[1] or "").split()
    return "upstream" if "upstream" in remotes else "origin"


def _channel_migrate(channel: str) -> str:
    """The 'main' channel never matched a real branch (the tree uses master) —
    remap a stale stored/checked-out value so old installs don't wedge."""
    return "master" if channel == "main" else channel


@router.get("/api/system/update-status")
def update_status(fetch: bool = False):
    branch = _git_repo("rev-parse", "--abbrev-ref", "HEAD")[1] or "?"
    commit = _git_repo("rev-parse", "--short", "HEAD")[1] or "?"
    subject = _git_repo("log", "-1", "--pretty=%s")[1]
    channel = _channel_migrate(get_setting("update_channel", "") or branch)
    remotes = (_git_repo("remote")[1] or "").split()
    remote = "upstream" if "upstream" in remotes else "origin"
    has_remote = bool(remotes)
    dirty = bool(_git_repo("status", "--porcelain")[1])
    behind = None
    if has_remote and fetch:
        _git_repo("fetch", remote, channel, timeout=90)
    if has_remote:
        rc, out = _git_repo("rev-list", "--count", f"HEAD..{remote}/{channel}")
        behind = int(out) if rc == 0 and out.isdigit() else None
    return {"branch": branch, "commit": commit, "subject": subject, "channel": channel,
            "enabled": _updates_on(), "behind": behind, "dirty": dirty,
            "has_remote": has_remote, "remote": remote, "channels": _UPDATE_CHANNELS}


class UpdateConfigIn(BaseModel):
    channel: Optional[str] = None
    enabled: Optional[bool] = None


@router.post("/api/system/update-config")
def update_config(cfg: UpdateConfigIn):
    conn = get_conn()
    if cfg.channel:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('update_channel',?)",
                     (_channel_migrate(cfg.channel.strip()),))
    if cfg.enabled is not None:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('updates_enabled',?)",
                     ("1" if cfg.enabled else "0",))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.post("/api/system/update-apply")
def update_apply():
    """Fetch + fast-forward to the tip of the selected channel, then restart. Refuses on
    local changes or a diverged branch — never clobbers work."""
    if not _updates_on():
        raise HTTPException(400, "Updates are turned off (pin lifted in Settings → Updates).")
    if not _git_repo("remote")[1]:
        raise HTTPException(400, "No git remote configured for this install.")
    channel = _channel_migrate(get_setting("update_channel", "")
                               or _git_repo("rev-parse", "--abbrev-ref", "HEAD")[1])
    if _git_repo("status", "--porcelain")[1]:
        raise HTTPException(409, "This install has local changes — commit or stash them before updating.")
    steps = []

    def st(name, rc, out):
        steps.append({"step": name, "ok": rc == 0, "detail": out[:200]})

    remote = _update_remote()
    rc, out = _git_repo("fetch", remote, channel, timeout=180); st("fetch", rc, out)
    if rc != 0:
        raise HTTPException(502, f"git fetch failed: {out[:200]}")
    cur = _git_repo("rev-parse", "--abbrev-ref", "HEAD")[1]
    if cur != channel:
        rc, out = _git_repo("checkout", channel)
        if rc != 0:  # no local branch yet (or ambiguous across remotes) — track the update remote's
            rc, out = _git_repo("checkout", "-b", channel, f"{remote}/{channel}")
        st(f"checkout {channel}", rc, out)
        if rc != 0:
            raise HTTPException(409, f"Could not switch to {channel}: {out[:200]}")
    rc, out = _git_repo("merge", "--ff-only", f"{remote}/{channel}"); st("fast-forward", rc, out)
    if rc != 0:
        raise HTTPException(409, f"Can't fast-forward {channel} (it diverged from {remote}). {out[:150]}")
    threading.Timer(1.0, _do_restart).start()
    return {"ok": True, "steps": steps, "message": f"Updated to latest {channel} — restarting…"}
