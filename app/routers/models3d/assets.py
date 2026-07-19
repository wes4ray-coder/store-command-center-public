"""models3d — the PUBLIC token-guarded asset route (auth-bypassed: this is how
Cults3D pulls the model files + images). The path-traversal guard here is
security-critical and kept VERBATIM.
"""
from fastapi import HTTPException
from fastapi.responses import FileResponse

from deps import *

from ._base import router, _asset_token


# ── PUBLIC asset route (auth-bypassed — this is how Cults3D pulls files) ──────

def _serve_asset(token: str, model_id: int, kind: str, filename: str):
    if not _secrets.compare_digest(token, _asset_token()):
        raise HTTPException(403, "bad token")
    conn = get_conn()
    row = conn.execute("SELECT * FROM models3d WHERE id=?", (model_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "not found")
    base = Path(filename).name  # prevent traversal
    if kind == "file":
        if base != (row["file_name"] or Path(row["file_path"]).name):
            raise HTTPException(404, "file mismatch")
        target = Path(row["file_path"])
    else:  # img — must be one of this model's known images
        allowed = {Path(p).name for p in
                   json.loads(row["render_paths"] or "[]") + json.loads(row["hero_paths"] or "[]")}
        if base not in allowed:
            raise HTTPException(404, "image not part of this model")
        # resolve to whichever dir it lives in
        target = None
        for p in json.loads(row["render_paths"] or "[]") + json.loads(row["hero_paths"] or "[]"):
            if Path(p).name == base:
                target = Path(p); break
    if not target or not target.exists():
        raise HTTPException(404, "asset missing on disk")
    return FileResponse(str(target), filename=base)


@router.get("/api/public/m3d/{token}/{model_id}/{kind}/{filename}")
def public_asset(token: str, model_id: int, kind: str, filename: str):
    return _serve_asset(token, model_id, kind, filename)
