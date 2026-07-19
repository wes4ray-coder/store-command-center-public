"""models3d — backlog config, folder scan/ingest, and the listing browse
(list + status counts)."""
import hashlib

from fastapi import HTTPException

from deps import *

from ._base import router, _effective_backlog, _public_dict


@router.get("/api/models3d/config")
def get_models3d_config():
    p = _effective_backlog()
    return {"backlog": str(p), "exists": p.exists(), "is_dir": p.is_dir() if p.exists() else False,
            "default": str(MODELS3D_BACKLOG), "extensions": list(MODELS3D_EXTS)}


class BacklogPath(BaseModel):
    backlog: str


@router.post("/api/models3d/config")
def set_models3d_config(body: BacklogPath):
    p = Path(body.backlog.strip()).expanduser()
    if not p.exists():
        raise HTTPException(400, f"Folder not found: {p}. Is the drive mounted?")
    if not p.is_dir():
        raise HTTPException(400, f"Not a folder: {p}")
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('models3d_backlog_path',?)", (str(p),))
    conn.commit(); conn.close()
    # quick count so the UI can show what it'll find
    n = sum(1 for f in p.rglob("*") if f.is_file() and f.suffix.lower() in MODELS3D_EXTS)
    return {"ok": True, "backlog": str(p), "found": n}


# ── backlog scan ─────────────────────────────────────────────────────────────

@router.post("/api/models3d/scan")
def scan_backlog():
    """Scan the backlog folder for new 3D files and ingest them (dedup by content hash)."""
    backlog = _effective_backlog()
    if not backlog.exists():
        raise HTTPException(400, f"Backlog folder not found: {backlog}. "
                                 "Set the correct path (is the drive mounted?).")
    conn = get_conn()
    added, skipped, backfilled = 0, 0, 0
    for p in sorted(backlog.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in MODELS3D_EXTS:
            continue
        try:
            fhash = hashlib.sha256(p.read_bytes()).hexdigest()
        except Exception:
            continue
        # Preserve the folder structure as reference/review context. Files stay put
        # on disk — we only record where each one lives, we never move them.
        rel = p.relative_to(backlog)
        rel_dir = "" if rel.parent == Path(".") else str(rel.parent)
        category = rel.parts[0] if len(rel.parts) > 1 else ""
        exists = conn.execute("SELECT id,rel_dir FROM models3d WHERE file_hash=?", (fhash,)).fetchone()
        if exists:
            skipped += 1
            # Backfill folder info onto rows imported before folder tracking existed.
            if rel_dir and not (exists["rel_dir"] or ""):
                conn.execute("UPDATE models3d SET rel_dir=?,category=? WHERE id=?",
                             (rel_dir, category, exists["id"]))
                backfilled += 1
            continue
        conn.execute(
            "INSERT INTO models3d (file_path,file_name,file_ext,file_size,file_hash,title,"
            "rel_dir,category,status,source) VALUES (?,?,?,?,?,?,?,?,'backlog','backlog')",
            (str(p), p.name, p.suffix.lower().lstrip("."), p.stat().st_size, fhash,
             p.stem.replace("_", " ").title(), rel_dir, category))
        added += 1
    conn.commit(); conn.close()
    return {"ok": True, "added": added, "skipped": skipped, "backfilled": backfilled, "backlog": str(backlog)}


@router.get("/api/models3d")
def list_models3d(status: Optional[str] = None):
    conn = get_conn()
    # nsfw-flagged models never appear here — /api/nsfw/library only.
    if status:
        rows = conn.execute("SELECT * FROM models3d WHERE status=? AND COALESCE(nsfw,0)=0 "
                            "ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM models3d WHERE COALESCE(nsfw,0)=0 "
                            "ORDER BY created_at DESC LIMIT 200").fetchall()
    conn.close()
    return [_public_dict(r) for r in rows]


@router.get("/api/models3d/counts")
def models3d_counts():
    conn = get_conn()
    rows = conn.execute("SELECT status, COUNT(*) c FROM models3d "
                        "WHERE COALESCE(nsfw,0)=0 GROUP BY status").fetchall()
    conn.close()
    return {r["status"]: r["c"] for r in rows}
