"""3D models pipeline for Cults3D — backlog → review → propose → approve → publish.

Drop raw 3D files (STL/OBJ/3MF/GLB/ZIP) into MODELS3D_BACKLOG. `scan` ingests them,
`render` makes turntable thumbnails, `propose` has the LLM draft the listing, you
approve, and `publish` pushes to Cults3D via createCreation. Assets are served to
Cults from a token-guarded public route (no session needed, that's how Cults pulls).
"""
import hashlib
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from deps import *
from services import (render_model3d, generate_model3d_hero, publish_model3d,
                      generate_model3d_mesh)

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
    if status:
        rows = conn.execute("SELECT * FROM models3d WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM models3d ORDER BY created_at DESC LIMIT 200").fetchall()
    conn.close()
    return [_public_dict(r) for r in rows]


@router.get("/api/models3d/counts")
def models3d_counts():
    conn = get_conn()
    rows = conn.execute("SELECT status, COUNT(*) c FROM models3d GROUP BY status").fetchall()
    conn.close()
    return {r["status"]: r["c"] for r in rows}


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


@router.get("/api/models3d/{model_id}")
def get_model3d(model_id: int):
    conn = get_conn()
    row = _row(conn, model_id)
    conn.close()
    d = _public_dict(row)
    # cheap mesh facts for the review card
    try:
        import render3d
        d["mesh"] = render3d.mesh_stats(row["file_path"])
    except Exception:
        d["mesh"] = None
    return d


class Model3dPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    category_id: Optional[str] = None
    price_cents: Optional[int] = None
    currency: Optional[str] = None
    license_code: Optional[str] = None
    made_with_ai: Optional[bool] = None
    primary_image: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


@router.patch("/api/models3d/{model_id}")
def patch_model3d(model_id: int, patch: Model3dPatch):
    conn = get_conn()
    _row(conn, model_id)
    fields, vals = [], []
    for k, v in patch.dict(exclude_none=True).items():
        col = k
        if k == "made_with_ai":
            v = 1 if v else 0
        fields.append(f"{col}=?"); vals.append(v)
    if fields:
        vals.append(model_id)
        conn.execute(f"UPDATE models3d SET {','.join(fields)},updated_at=datetime('now') WHERE id=?", vals)
        conn.commit()
    row = _row(conn, model_id)
    conn.close()
    return _public_dict(row)


@router.delete("/api/models3d/{model_id}")
def delete_model3d(model_id: int):
    conn = get_conn()
    _row(conn, model_id)
    conn.execute("DELETE FROM models3d WHERE id=?", (model_id,))
    conn.commit(); conn.close()
    return {"ok": True}


# ── render / hero / propose ──────────────────────────────────────────────────

@router.post("/api/models3d/{model_id}/render")
def render_model3d_ep(model_id: int, background_tasks: BackgroundTasks):
    conn = get_conn(); _row(conn, model_id); conn.close()
    background_tasks.add_task(render_model3d, model_id)
    return {"ok": True, "queued": True}


class HeroRequest(BaseModel):
    prompt: str
    model: Optional[str] = None


@router.post("/api/models3d/{model_id}/hero")
def hero_model3d_ep(model_id: int, req: HeroRequest, background_tasks: BackgroundTasks):
    conn = get_conn(); _row(conn, model_id); conn.close()
    if not req.prompt.strip():
        raise HTTPException(400, "prompt required")
    background_tasks.add_task(generate_model3d_hero, model_id, req.prompt, req.model)
    return {"ok": True, "queued": True}


_PROPOSE_SYSTEM = (
    "You are a Cults3D listing copywriter for 3D-printable models. Given a model's "
    "file name and facts, write a compelling marketplace listing. Respond ONLY with valid JSON:\n"
    '{"title": "<catchy, <=60 chars>", "description": "<2-4 vivid sentences: what it is, '
    'print notes, uses>", "tags": "<8-12 comma-separated lowercase tags>", '
    '"suggested_price": <USD number, 0 for free>}'
)


@router.post("/api/models3d/{model_id}/propose")
def propose_model3d(model_id: int):
    """Have the LLM draft the listing (title/desc/tags/price) and write it to the row.
    Returns {task_id} to poll via /api/tasks/{task_id}."""
    conn = get_conn()
    row = _row(conn, model_id)
    conn.close()
    facts = f"File name: {row['file_name']}\nFormat: {row['file_ext']}\n"
    if row["rel_dir"]:
        facts += (f"Source folder: {row['rel_dir']}\n"
                  f"Category (top folder): {row['category'] or row['rel_dir']}\n"
                  "Use the folder name as a strong hint for what this model is and who wants it.\n")
    try:
        import render3d
        st = render3d.mesh_stats(row["file_path"])
        if st and not st.get("error"):
            facts += f"Mesh: {st.get('faces')} faces, dims {st.get('dims_mm')} mm, watertight={st.get('watertight')}\n"
    except Exception:
        pass

    def _work():
        raw = _call_lmstudio(get_prompt('threed_listing'), facts, max_tokens=1200, json_mode=True)
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        try:
            data = json.loads(clean)
        except Exception:
            import re as _re
            m = _re.search(r'\{.*\}', clean, _re.DOTALL)
            data = json.loads(m.group(0)) if m else {"title": row["file_name"], "description": clean, "tags": ""}
        price_cents = int(round(float(data.get("suggested_price") or 0) * 100))
        c = get_conn()
        c.execute(
            "UPDATE models3d SET title=?,description=?,tags=?,price_cents=?,"
            "status=CASE WHEN status='backlog' THEN 'review' ELSE status END,"
            "updated_at=datetime('now') WHERE id=?",
            (str(data.get("title") or row["file_name"])[:150], data.get("description") or "",
             data.get("tags") or "", price_cents, model_id))
        c.commit(); c.close()
        return {"model_id": model_id, **data, "price_cents": price_cents}

    tid = orch.submit_llm(_work, desc=f"Propose 3D listing: {row['file_name'][:40]}", task="threed_listing")
    return {"task_id": tid, "model_id": model_id}


# ── approve / reject / publish ───────────────────────────────────────────────

@router.patch("/api/models3d/{model_id}/approve")
def approve_model3d(model_id: int):
    conn = get_conn(); _row(conn, model_id)
    conn.execute("UPDATE models3d SET status='approved',updated_at=datetime('now') WHERE id=?", (model_id,))
    conn.commit(); conn.close()
    return {"ok": True}


@router.patch("/api/models3d/{model_id}/reject")
def reject_model3d(model_id: int):
    conn = get_conn(); _row(conn, model_id)
    conn.execute("UPDATE models3d SET status='rejected',updated_at=datetime('now') WHERE id=?", (model_id,))
    conn.commit(); conn.close()
    return {"ok": True}


@router.post("/api/models3d/{model_id}/publish")
def publish_model3d_ep(model_id: int, background_tasks: BackgroundTasks):
    conn = get_conn()
    row = _row(conn, model_id)
    conn.close()
    if row["cults3d_id"]:
        raise HTTPException(409, f"Already published: {row['cults3d_url']}")
    imgs = json.loads(row["render_paths"] or "[]") + json.loads(row["hero_paths"] or "[]")
    if not imgs:
        raise HTTPException(400, "No images yet — render the mesh or generate a hero image first")
    # mark publishing so the UI reflects it immediately
    conn = get_conn()
    conn.execute("UPDATE models3d SET status='approved',publish_error=NULL,updated_at=datetime('now') WHERE id=?", (model_id,))
    conn.commit(); conn.close()
    background_tasks.add_task(publish_model3d, model_id, _asset_base(model_id))
    return {"ok": True, "queued": True}


# ── local 3D generation (text/image → mesh via TripoSR on the box) ───────────

class Generate3dRequest(BaseModel):
    prompt: Optional[str] = None       # if set: SDXL image first, then image→3D
    image_path: Optional[str] = None   # or point at an existing image on disk
    title: Optional[str] = None
    image_model: Optional[str] = None
    generator: str = "triposr"         # which image→3D model (key in RECOMMENDED_3D_MODELS)


def _resolve_generator(key: str) -> dict:
    """Return the catalog entry for a generator key; raise if unknown."""
    cat = {m["key"]: m for m in RECOMMENDED_3D_MODELS}
    if key not in cat:
        raise HTTPException(400, f"Unknown 3D generator '{key}'")
    return cat[key]


def _m3d_progress(model_id: int, msg: str):
    """Surface a human progress line on the model row so the UI isn't a black box."""
    try:
        c = get_conn()
        c.execute("UPDATE models3d SET progress_msg=?,updated_at=datetime('now') WHERE id=?", (msg, model_id))
        c.commit(); c.close()
    except Exception:
        pass


@router.post("/api/models3d/generate")
def generate_model3d_ep(req: Generate3dRequest, background_tasks: BackgroundTasks):
    """Create a generated 3D model. From a prompt (SDXL→mesh) or an existing image."""
    if not req.prompt and not req.image_path:
        raise HTTPException(400, "Provide a prompt or an image_path")
    gen = _resolve_generator(req.generator)
    gen_script = gen["script"]
    gen_label = gen["label"].split(" (")[0]
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO models3d (file_path,file_name,file_ext,title,status,source,gen_prompt,"
        "rel_dir,category,progress_msg) VALUES ('','','',?,'generating','generated',?,"
        "'generated','Generated','⏳ Queued…')",
        (req.title or (req.prompt or "Generated model")[:80], req.prompt or f"from {req.image_path}"))
    model_id = cur.lastrowid
    conn.commit(); conn.close()

    def _pipeline():
        img = req.image_path
        if req.prompt and not img:
            # 1. render a clean product image with SDXL, 2. TripoSR it into a mesh
            MODELS3D_HERO.mkdir(parents=True, exist_ok=True)
            out = MODELS3D_HERO / f"gensrc_{model_id}_{int(datetime.now().timestamp())}.png"
            _m3d_progress(model_id, "🎨 Rendering a source image with SDXL…")
            orch.image_acquire()
            try:
                seed = str(random.randint(1, 2**31 - 1))
                mdl = req.image_model or DEFAULT_IMAGE_MODEL
                sd_prompt = (f"{req.prompt}, single centered object, plain white background, "
                             "studio product shot, full object visible, no shadows")
                r = subprocess.run([str(GENERATE_SCRIPT), sd_prompt, str(out), "1024", "1024", "20", seed, mdl],
                                   capture_output=True, text=True, timeout=300)
            finally:
                orch.image_release()
            if not out.exists():
                err = (r.stderr or r.stdout or "")[-200:] if 'r' in dir() else ""
                c = get_conn()
                c.execute("UPDATE models3d SET status='error',progress_msg='❌ Source image failed',"
                          "publish_error=? WHERE id=?", (f"source image gen failed: {err}", model_id))
                c.commit(); c.close(); return
            img = str(out)
            c = get_conn()
            c.execute("UPDATE models3d SET hero_paths=?,primary_image=? WHERE id=?",
                      (json.dumps([img]), img, model_id)); c.commit(); c.close()
        _m3d_progress(model_id, f"🧊 Building 3D mesh on the GPU box ({gen_label})…")
        generate_model3d_mesh(model_id, img, gen_script)

    background_tasks.add_task(_pipeline)
    return {"ok": True, "model_id": model_id, "generator": req.generator}


class EnhanceReq(BaseModel):
    prompt: str


@router.post("/api/models3d/enhance")
def enhance_3d(req: EnhanceReq):
    """3D-tuned prompt enhancement. Returns {task_id}; poll /api/task/{id} → {enhanced}."""
    idea = req.prompt.strip()
    if not idea:
        raise HTTPException(400, "prompt required")
    SYS = ("You improve short ideas into prompts for image-to-3D generation of a SINGLE "
           "printable object. Return ONE vivid line (30-60 words): the object, its form, "
           "style, and surface — centered, full object visible, clean silhouette, no scene, "
           "no background, no text. Output ONLY the prompt line, nothing else.")
    def _work():
        out = _call_lmstudio(get_prompt('threed_enhance'), idea, max_tokens=400)
        import re as _re
        out = _re.sub(r'<think>.*?</think>', '', out, flags=_re.DOTALL).strip().strip('"')
        return {"enhanced": out, "original": idea}
    tid = orch.submit_llm(_work, desc=f"Enhance 3D: {idea[:40]}", task="threed_enhance")
    return {"task_id": tid}




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
