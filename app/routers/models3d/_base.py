"""Shared base for the models3d package: the single router, the in-flight box-side
job registries, the asset-token / public-URL / backlog-path helpers, and the row
loader + serializer.

Imported first by ``__init__`` so these exist before any route submodule registers
on the shared ``router``. The submodules are imported in an order that preserves the
original route registration order (specific ``/api/models3d/...`` paths BEFORE the
``/api/models3d/{model_id}`` param routes — see the note in ``genmodels``).
"""
from fastapi import APIRouter, HTTPException

from deps import *

router = APIRouter()

# In-flight box-side install jobs for 3D-gen models (key -> {status,error,proc}).
_dl_3d_jobs: dict = {}
# In-flight real-generation test jobs (key -> {status: running|pass|fail, detail}).
_m3d_test_jobs: dict = {}

# ── helpers ──────────────────────────────────────────────────────────────────

def _asset_token() -> str:
    """Stable random token guarding the public asset route (persisted in settings)."""
    if MODELS3D_ASSET_TOKEN:
        return MODELS3D_ASSET_TOKEN
    conn = get_conn()
    r = conn.execute("SELECT value FROM settings WHERE key='models3d_asset_token'").fetchone()
    if r and r["value"]:
        conn.close()
        return _dec(r["value"])
    tok = _secrets.token_urlsafe(24)
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('models3d_asset_token',?)", (_enc(tok),))
    conn.commit(); conn.close()
    return tok


def _asset_base(model_id: int) -> str:
    """Public URL prefix Cults3D fetches assets from for this model."""
    return f"{PUBLIC_BASE_URL}{STORE_BASE}/api/public/m3d/{_asset_token()}/{model_id}"


def _effective_backlog() -> Path:
    """Backlog folder to scan: DB setting (editable in the UI) > config default."""
    conn = get_conn()
    r = conn.execute("SELECT value FROM settings WHERE key='models3d_backlog_path'").fetchone()
    conn.close()
    if r and (r["value"] or "").strip():
        return Path(r["value"].strip()).expanduser()
    return MODELS3D_BACKLOG


def _row(conn, model_id: int):
    row = conn.execute("SELECT * FROM models3d WHERE id=?", (model_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "3D model not found")
    return row


def _public_dict(row) -> dict:
    d = dict(row)
    d["render_urls"] = [f"{STORE_BASE}/api/public/m3d/{_asset_token()}/{row['id']}/img/{Path(p).name}"
                        for p in json.loads(row["render_paths"] or "[]")]
    d["hero_urls"] = [f"{STORE_BASE}/api/public/m3d/{_asset_token()}/{row['id']}/img/{Path(p).name}"
                      for p in json.loads(row["hero_paths"] or "[]")]
    if row["primary_image"]:
        d["primary_url"] = f"{STORE_BASE}/api/public/m3d/{_asset_token()}/{row['id']}/img/{Path(row['primary_image']).name}"
    d["price_dollars"] = (row["price_cents"] or 0) / 100.0
    return d
