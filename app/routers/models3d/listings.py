"""models3d — per-model listing CRUD: get / patch / delete, render + hero image,
LLM-drafted listing proposal, and approve / reject / publish (to Cults3D).
"""
from fastapi import HTTPException, BackgroundTasks

from deps import *
from services import render_model3d, generate_model3d_hero, publish_model3d

from ._base import router, _row, _public_dict, _asset_base


@router.get("/api/models3d/{model_id}")
def get_model3d(model_id: int):
    conn = get_conn()
    row = _row(conn, model_id)
    conn.close()
    if row["nsfw"]:
        import nsfw as _nsfw
        if not _nsfw.visible():
            raise HTTPException(404, "3D model not found")
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
