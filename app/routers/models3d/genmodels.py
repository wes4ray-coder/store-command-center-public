"""models3d — the 3D-generation model catalog (install/test like image/video models).

NOTE: these specific ``/api/models3d/gen-models...`` (and the sibling static paths in
``backlog``) MUST be registered before the ``/api/models3d/{model_id}`` route in
``listings``, or FastAPI matches "gen-models" as a model_id and 422s. ``__init__``
imports the submodules in that order — do not reorder.
"""
from fastapi import HTTPException, BackgroundTasks

from deps import *

from ._base import router, _dl_3d_jobs, _m3d_test_jobs


# ── 3D generation model catalog (install like image/video models) ────────────
# NOTE: these specific paths MUST be declared before the /{model_id} route below,
# or FastAPI matches "gen-models" as a model_id and 422s.

@router.get("/api/models3d/gen-models")
def list_gen_models():
    """3D-gen models with installed status (checks the marker path on the box)."""
    out = []
    for m in RECOMMENDED_3D_MODELS:
        installed = False
        try:
            r = subprocess.run(BOX_SSH + [f"test -e {m['marker']} && echo yes || echo no"],
                               capture_output=True, text=True, timeout=8)
            installed = "yes" in (r.stdout or "")
        except Exception:
            pass
        entry = {k: v for k, v in m.items() if k not in ("install", "script")}
        entry["installed"] = installed
        job = _dl_3d_jobs.get(m["key"], {})
        if job.get("status"):
            entry["dl_status"] = job["status"]
            entry["dl_error"] = job.get("error")
        tjob = _m3d_test_jobs.get(m["key"], {})
        if tjob.get("status"):
            entry["test_status"] = tjob["status"]           # running | pass | fail
            entry["test_detail"] = tjob.get("detail")
        out.append(entry)
    return out


@router.post("/api/models3d/gen-models/{key}/test")
def test_gen_model_ep(key: str, background_tasks: BackgroundTasks):
    """Run a REAL one-shot generation and report pass/fail (true readiness, not just
    'venv exists'). Returns immediately; poll /test-status."""
    from services import test_gen_model
    cat = {m["key"]: m for m in RECOMMENDED_3D_MODELS}
    if key not in cat:
        raise HTTPException(404, "Unknown 3D model")
    if _m3d_test_jobs.get(key, {}).get("status") == "running":
        return {"ok": True, "status": "running"}
    _m3d_test_jobs[key] = {"status": "running"}

    def _work():
        try:
            res = test_gen_model(key)
        except Exception as e:
            res = {"ok": False, "error": str(e)[:260]}
        _m3d_test_jobs[key] = {"status": "pass" if res.get("ok") else "fail", "detail": res}

    background_tasks.add_task(_work)
    return {"ok": True, "status": "running"}


@router.get("/api/models3d/gen-models/{key}/test-status")
def test_gen_model_status(key: str):
    return _m3d_test_jobs.get(key, {"status": "idle"})


@router.post("/api/models3d/gen-models/{key}/install")
def install_gen_model(key: str):
    """Install a 3D-gen model on the box (git clone + venv + pip), tracked in the background."""
    cat = {m["key"]: m for m in RECOMMENDED_3D_MODELS}
    if key not in cat:
        raise HTTPException(404, "Unknown 3D model")
    if _dl_3d_jobs.get(key, {}).get("status") == "installing":
        return {"ok": True, "status": "already_installing"}
    proc = subprocess.Popen(BOX_SSH + [cat[key]["install"]],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    _dl_3d_jobs[key] = {"status": "installing", "error": None, "proc": proc}

    def _mon(k, p):
        out, _ = p.communicate()
        if p.returncode == 0:
            _dl_3d_jobs[k] = {"status": "done", "error": None, "proc": None}
        else:
            _dl_3d_jobs[k] = {"status": "error", "error": (out or "")[-400:], "proc": None}
    threading.Thread(target=_mon, args=(key, proc), daemon=True).start()
    return {"ok": True, "status": "installing"}


@router.get("/api/models3d/gen-models/{key}/install-status")
def install_gen_model_status(key: str):
    job = _dl_3d_jobs.get(key)
    if not job:
        return {"status": "idle"}
    return {"status": job["status"], "error": job.get("error")}
