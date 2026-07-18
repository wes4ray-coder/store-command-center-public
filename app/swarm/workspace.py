"""Dev Swarm — git sandboxing + file scoping in the dev worktree.

All edits happen in config.REPO_DEV; scoped jobs may only touch their listed paths.
Parsing the coder's strict fenced FILE format and reading real code for context also
lives here.

No intra-package dependencies.
"""
import json
import re
import subprocess
from pathlib import Path

from config import REPO_DEV, GIT_BIN


# ─────────────────────────────────────────────────────────────────────────────
# dev worktree helpers
# ─────────────────────────────────────────────────────────────────────────────
def _git_dev(*args, timeout=60) -> tuple[int, str]:
    try:
        r = subprocess.run([GIT_BIN, "-C", REPO_DEV, *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def _scoped_paths(job: dict) -> list[str]:
    try:
        return json.loads(job.get("paths") or "[]")
    except Exception:
        return []


def _path_allowed(rel: str, job: dict) -> bool:
    """For scoped jobs, only allow writes within the listed files/folders."""
    scope = job.get("scope") or "project"
    if scope == "project":
        return True
    paths = _scoped_paths(job)
    rel = rel.lstrip("/")
    for p in paths:
        p = p.strip().lstrip("/")
        if scope == "file" and rel == p:
            return True
        if scope == "folder" and (rel == p or rel.startswith(p.rstrip("/") + "/")):
            return True
    return False


_FILE_RE = re.compile(r"<<<FILE\s+(.+?)>>>\s*\n(.*?)\n?<<<END>>>", re.DOTALL)


def _parse_files(text: str) -> list[tuple[str, str]]:
    out = []
    for m in _FILE_RE.finditer(text):
        path = m.group(1).strip()
        content = m.group(2)
        # strip a leading ```lang fence and trailing ``` if the model added them
        content = re.sub(r"^```[\w.-]*\n", "", content)
        content = re.sub(r"\n```\s*$", "", content)
        out.append((path, content))
    return out


def _read_scoped_context(job: dict, limit_bytes=12000) -> str:
    """Current contents of the scoped files (so the coder edits the real code)."""
    scope = job.get("scope") or "project"
    if scope == "project":
        return "(whole-project scope — no specific files preloaded)"
    chunks = []
    for p in _scoped_paths(job):
        fp = Path(REPO_DEV) / p.strip().lstrip("/")
        if fp.is_file():
            try:
                txt = fp.read_text(errors="replace")[:limit_bytes]
                chunks.append(f"<<<FILE {p}>>>\n{txt}\n<<<END>>>")
            except Exception:
                pass
    return "\n\n".join(chunks) or "(scoped files not found in dev worktree)"


def _fallback_single_file(out: str, job: dict) -> list[tuple[str, str]]:
    """When a coder ignores the FILE format but the job targets ONE file, salvage the
    content: prefer a fenced code block, else the cleaned output."""
    paths = _scoped_paths(job)
    if (job.get("scope") == "file") and len(paths) == 1:
        m = re.search(r"```[\w.-]*\n(.*?)```", out, re.DOTALL)
        content = (m.group(1) if m else out).strip()
        if content and len(content) < 20000:
            return [(paths[0].strip().lstrip("/"), content)]
    return []


def _repo_tree() -> str:
    """A compact map of the dev worktree's real layout so the architect scopes subtasks
    to paths that actually exist (not invented src/… paths)."""
    rc, out = _git_dev("ls-files")
    files = out.split()
    if not files:
        return "(repo layout unavailable)"
    top_dirs = sorted({f.split("/")[0] for f in files if "/" in f})
    root_files = [f for f in files if "/" not in f][:20]
    app_sub = sorted({"/".join(f.split("/")[:2]) for f in files if f.startswith("app/")})[:40]
    static_sub = sorted({"/".join(f.split("/")[:3]) for f in files if f.startswith("static/js/")})[:30]
    return ("Top-level dirs: " + ", ".join(top_dirs) +
            "\nRoot files: " + ", ".join(root_files) +
            "\napp/ layout: " + ", ".join(app_sub) +
            "\nstatic/js: " + ", ".join(static_sub))


def _read_files(paths: list, per: int = 2500, total: int = 12000) -> tuple[str, list]:
    """Read a few existing files from the dev worktree (truncated) so the architect plans
    against the REAL code. Returns (bundle_text, actually_read_paths)."""
    chunks, read, used = [], [], 0
    for p in paths[:6]:
        fp = Path(REPO_DEV) / p.strip().lstrip("/")
        if not fp.is_file():
            continue
        try:
            t = fp.read_text(errors="replace")[:per]
        except Exception:
            continue
        if used + len(t) > total:
            break
        used += len(t)
        chunks.append(f"=== {p} ===\n{t}")
        read.append(p)
    return ("\n\n".join(chunks), read)
