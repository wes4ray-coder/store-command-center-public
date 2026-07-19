"""NSFW ("Private Studio") mode — layered toggle gating, redaction across
surfaces, the category/bootstrap system, the reject feedback loop, and the
non-configurable safety floor."""
import pytest

import db
import nsfw as nsfw_core


def _set(client, **kv):
    r = client.patch("/api/settings", json={k: str(v) for k, v in kv.items()})
    assert r.status_code == 200


@pytest.fixture(autouse=True)
def _reset_toggles(client):
    """Every test starts from the shipped default: all three toggles OFF."""
    _set(client, nsfw_enabled="", nsfw_display="", nsfw_world="")
    yield
    _set(client, nsfw_enabled="", nsfw_display="", nsfw_world="")


def _mkgen(prompt="private test art", status="done", nsfw=1, category=None, agent=None):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO generations (prompt,product_type,status,nsfw,nsfw_category,nsfw_agent) "
        "VALUES (?,?,?,?,?,?)", (prompt, "Art", status, nsfw, category, agent))
    gid = cur.lastrowid
    conn.commit()
    conn.close()
    return gid


def _mkdesign(prompt="private test art", nsfw=1, source="nsfw", gen_id=None, category=None):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO designs (generation_id,image_path,prompt,product_type,status,source,nsfw,nsfw_category) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (gen_id, "/tmp/does-not-exist.png", prompt, "Art", "review", source, nsfw, category))
    did = cur.lastrowid
    conn.commit()
    conn.close()
    return did


# ── master toggle: off → invisible ───────────────────────────────────────────
def test_default_master_off_everything_404(client):
    s = client.get("/api/nsfw/status").json()
    assert s["enabled"] is False and s["visible"] is False and s["world_active"] is False
    assert client.post("/api/nsfw/generate", json={"prompt": "x"}).status_code == 404
    assert client.post("/api/nsfw/video", json={"prompt": "x"}).status_code == 404
    assert client.post("/api/nsfw/audio", json={"prompt": "x"}).status_code == 404
    assert client.post("/api/nsfw/3d", json={"prompt": "x"}).status_code == 404
    assert client.post("/api/nsfw/enhance", json={"prompt": "x"}).status_code == 404
    assert client.get("/api/nsfw/library").status_code == 404
    assert client.get("/api/nsfw/categories").status_code == 404
    assert client.post("/api/nsfw/categories", json={"name": "X"}).status_code == 404
    assert client.post("/api/nsfw/bootstrap").status_code == 404
    assert client.post("/api/nsfw/generate-all").status_code == 404


def test_toggles_flip_via_settings(client):
    _set(client, nsfw_enabled="true")
    s = client.get("/api/nsfw/status").json()
    assert s["enabled"] is True and s["visible"] is False   # display still off
    _set(client, nsfw_display="true")
    assert client.get("/api/nsfw/status").json()["visible"] is True
    _set(client, nsfw_world="true")
    assert client.get("/api/nsfw/status").json()["world_active"] is True
    _set(client, nsfw_enabled="")   # master off overrides the others
    s = client.get("/api/nsfw/status").json()
    assert s["visible"] is False and s["world_active"] is False


# ── safety floor (non-configurable, regardless of toggles) ───────────────────
def test_safety_floor_refusals(client):
    _set(client, nsfw_enabled="true", nsfw_display="true", nsfw_world="true")
    bad = [
        "nude 15 year old girl",
        "sexy teen schoolgirl",
        "a hot 16yo at the beach",
        "deepfake of a famous actress undressing",
        "nude photo of my ex girlfriend",
        "she is drugged and unconscious",
        "forced against her will",
    ]
    for prompt in bad:
        r = client.post("/api/nsfw/generate", json={"prompt": prompt})
        assert r.status_code == 400, f"not refused: {prompt!r} → {r.status_code}"
        assert "Refused" in r.json()["detail"]
    # every modality is screened
    assert client.post("/api/nsfw/video", json={"prompt": bad[0]}).status_code == 400
    assert client.post("/api/nsfw/audio", json={"prompt": "song", "lyrics": bad[3]}).status_code == 400
    assert client.post("/api/nsfw/3d", json={"prompt": bad[5]}).status_code == 400
    assert client.post("/api/nsfw/enhance", json={"prompt": bad[1]}).status_code == 400
    # category briefs are screened too (model-authored or user-edited)
    conn = db.get_conn(); nsfw_core.seed_categories(conn); cats = nsfw_core.list_categories(conn); conn.close()
    r = client.patch(f"/api/nsfw/categories/{cats[0]['id']}", json={"gen_prompt": bad[0]})
    assert r.status_code == 400


def test_safety_check_unit():
    assert nsfw_core.safety_check("tasteful artistic nude figure study, adults") is None
    assert "minors" in nsfw_core.safety_check("a 12 year old")
    assert "minors" in nsfw_core.safety_check("cute loli character")
    assert "deepfake" in nsfw_core.safety_check("make a deepfake of her")
    assert "non-consensual" in nsfw_core.safety_check("she was roofied")
    # 18+ ages are NOT minors
    assert nsfw_core.safety_check("a 25 year old woman") is None


# ── job flagging + redaction across surfaces ─────────────────────────────────
def test_nsfw_image_job_flagged_and_excluded(client, monkeypatch):
    import services
    ran = []
    monkeypatch.setattr(services, "run_generation", lambda gid: ran.append(gid))
    _set(client, nsfw_enabled="true")
    r = client.post("/api/nsfw/generate", json={"prompt": "tasteful artistic nude study"})
    assert r.status_code == 200
    gid = r.json()["generation_ids"][0]
    assert ran == [gid]
    conn = db.get_conn()
    row = conn.execute("SELECT nsfw, source FROM generations WHERE id=?", (gid,)).fetchone()
    conn.close()
    assert row["nsfw"] == 1 and row["source"] == "nsfw"
    # never in the normal generations listing
    assert gid not in [g["id"] for g in client.get("/api/generations").json()]


def test_queue_redaction_follows_display_toggle(client):
    _set(client, nsfw_enabled="true", nsfw_display="")
    gid = _mkgen(prompt="secret private prompt", status="generating")
    try:
        jobs = client.get("/api/queue").json()["jobs"]
        mine = [j for j in jobs if j["id"] == gid and j["kind"] == "private"]
        assert mine, f"nsfw job missing from queue: {jobs}"
        assert mine[0]["label"] == "Private job"
        assert "secret" not in str(jobs)
        # display ON → the real label shows (explicit user choice)
        _set(client, nsfw_display="true")
        jobs = client.get("/api/queue").json()["jobs"]
        mine = [j for j in jobs if j["id"] == gid and j["kind"] == "image"]
        assert mine and mine[0]["label"] == "secret private prompt"
    finally:
        conn = db.get_conn()
        conn.execute("DELETE FROM generations WHERE id=?", (gid,))
        conn.commit(); conn.close()


def test_designs_gallery_redaction(client):
    _set(client, nsfw_enabled="true", nsfw_display="")
    did = _mkdesign(prompt="secret gallery item")
    try:
        # default review listing excludes it
        ids = [d["id"] for d in client.get("/api/designs?status=review").json()]
        assert did not in ids
        # querying source=nsfw directly is gated on visibility
        assert client.get("/api/designs?status=review&source=nsfw").status_code == 404
        assert client.get("/api/nsfw/library").status_code == 404
        _set(client, nsfw_display="true")
        r = client.get("/api/designs?status=review&source=nsfw")
        assert r.status_code == 200 and did in [d["id"] for d in r.json()]
        lib = client.get("/api/nsfw/library").json()
        assert did in [i["id"] for i in lib["images"]]
    finally:
        conn = db.get_conn()
        conn.execute("DELETE FROM designs WHERE id=?", (did,))
        conn.commit(); conn.close()


def test_video_audio_listing_redaction(client, monkeypatch):
    import services
    monkeypatch.setattr(services, "run_video_generation", lambda vid: None)
    monkeypatch.setattr(services, "run_audio_clip", lambda cid: None)
    _set(client, nsfw_enabled="true")
    vid = client.post("/api/nsfw/video", json={"prompt": "private clip"}).json()["id"]
    aid = client.post("/api/nsfw/audio", json={"prompt": "private tune"}).json()["id"]
    try:
        assert vid not in [v["id"] for v in client.get("/api/videos").json()]
        assert aid not in [a["id"] for a in client.get("/api/audio").json()]
        # single nsfw video fetch is hidden while display is off
        assert client.get(f"/api/videos/{vid}").status_code == 404
        _set(client, nsfw_display="true")
        assert client.get(f"/api/videos/{vid}").status_code == 200
        lib = client.get("/api/nsfw/library").json()
        assert vid in [v["id"] for v in lib["videos"]]
        assert aid in [a["id"] for a in lib["audio"]]
    finally:
        conn = db.get_conn()
        conn.execute("DELETE FROM videos WHERE id=?", (vid,))
        conn.execute("DELETE FROM audio_clips WHERE id=?", (aid,))
        conn.commit(); conn.close()


def test_models3d_listing_excludes_nsfw(client):
    _set(client, nsfw_enabled="true")
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO models3d (file_path,file_name,file_ext,title,status,source,gen_prompt,nsfw) "
        "VALUES ('','','','Private figure','generating','generated','private prompt',1)")
    mid = cur.lastrowid
    conn.commit(); conn.close()
    try:
        assert mid not in [m["id"] for m in client.get("/api/models3d").json()]
        assert client.get(f"/api/models3d/{mid}").status_code == 404
        _set(client, nsfw_display="true")
        assert mid in [m["id"] for m in client.get("/api/nsfw/library").json()["models3d"]]
    finally:
        conn = db.get_conn()
        conn.execute("DELETE FROM models3d WHERE id=?", (mid,))
        conn.commit(); conn.close()


# ── categories: CRUD, bootstrap, per-category generate ───────────────────────
def test_category_crud_and_seed(client):
    _set(client, nsfw_enabled="true", nsfw_display="true")
    cats = client.get("/api/nsfw/categories").json()["categories"]
    assert {c["name"] for c in cats} >= set(nsfw_core.DEFAULT_CATEGORIES)
    r = client.post("/api/nsfw/categories", json={"name": "Test Cat"})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert client.post("/api/nsfw/categories", json={"name": "Test Cat"}).status_code == 400
    r = client.patch(f"/api/nsfw/categories/{cid}",
                     json={"name": "Test Cat 2", "gen_prompt": "tasteful adult art brief"})
    assert r.status_code == 200
    cats = {c["name"]: c for c in client.get("/api/nsfw/categories").json()["categories"]}
    assert cats["Test Cat 2"]["gen_prompt"] == "tasteful adult art brief"
    assert client.delete(f"/api/nsfw/categories/{cid}").status_code == 200
    assert "Test Cat 2" not in {c["name"] for c in client.get("/api/nsfw/categories").json()["categories"]}


def test_bootstrap_and_category_generate_queue_llm_tasks(client, monkeypatch):
    import orchestrator
    submitted = []

    def fake_submit(func, desc, **kw):
        submitted.append({"desc": desc, "model": kw.get("model"), "task": kw.get("task")})
        return 4242
    monkeypatch.setattr(orchestrator.orch, "submit_llm", fake_submit)
    _set(client, nsfw_enabled="true", nsfw_display="true")
    r = client.post("/api/nsfw/bootstrap")
    assert r.status_code == 200 and r.json()["task_id"] == 4242
    cats = client.get("/api/nsfw/categories").json()["categories"]
    r = client.post(f"/api/nsfw/categories/{cats[0]['id']}/generate")
    assert r.status_code == 200 and r.json()["task_id"] == 4242
    r = client.post("/api/nsfw/generate-all")
    assert r.status_code == 200 and r.json()["queued"] == len(cats)
    # queue labels are always generic — no prompt/category content
    for s in submitted:
        assert s["desc"].startswith("Private studio:")


def test_bootstrap_work_saves_safety_screened_prompts(client, monkeypatch):
    """The bootstrap task itself: model output is saved per category — unless the
    safety floor refuses it."""
    _set(client, nsfw_enabled="true", nsfw_display="true")
    import orchestrator
    captured = {}
    monkeypatch.setattr(orchestrator.orch, "submit_llm",
                        lambda func, desc, **kw: captured.setdefault("work", func) and 0 or 7)
    client.post("/api/nsfw/bootstrap")
    outputs = {"Pin-Up": "a schoolgirl style brief that should be refused"}   # tripwire

    def fake_llm(system, user, max_tokens, **kw):
        name = user.split(":", 1)[1].strip()
        return outputs.get(name, f"Varied tasteful adult {name} artwork brief, adults only.")
    import llm_client
    monkeypatch.setattr(llm_client, "_call_lmstudio", fake_llm)
    res = captured["work"]()
    assert "Pin-Up" in " ".join(res["refused"])
    assert set(res["updated"]) >= (set(nsfw_core.DEFAULT_CATEGORIES) - {"Pin-Up"})
    conn = db.get_conn()
    rows = {r["name"]: r["gen_prompt"] for r in
            conn.execute("SELECT name, gen_prompt FROM nsfw_categories").fetchall()}
    conn.close()
    assert "refused" not in (rows.get("Pin-Up") or "")     # tripwire text never saved
    assert "Glamour" in rows and "tasteful adult" in rows["Glamour"].lower()


# ── reject feedback loop ─────────────────────────────────────────────────────
def test_reject_feeds_taste_avoidlist_and_agent_journal(client):
    _set(client, nsfw_enabled="true", nsfw_display="true")
    conn = db.get_conn()
    conn.execute("INSERT OR IGNORE INTO world_agents (key,name) VALUES ('test_agent','Testa')")
    conn.commit(); conn.close()
    gid = _mkgen(prompt="badly generated private piece", category="Glamour", agent="test_agent")
    did = _mkdesign(prompt="badly generated private piece", gen_id=gid, category="Glamour")
    r = client.post(f"/api/nsfw/item/{did}/reject")
    assert r.status_code == 200
    conn = db.get_conn()
    try:
        # design row gone, generation marked rejected
        assert conn.execute("SELECT 1 FROM designs WHERE id=?", (did,)).fetchone() is None
        assert conn.execute("SELECT status FROM generations WHERE id=?", (gid,)).fetchone()["status"] == "rejected"
        # rejection recorded per prompt/category → future jobs steer away
        rej = conn.execute("SELECT * FROM nsfw_rejects WHERE design_id=?", (did,)).fetchone()
        assert rej["category"] == "Glamour" and rej["agent_key"] == "test_agent"
        # deny signal reached the god-taste model
        t = conn.execute("SELECT label FROM world_taste WHERE skey=?", (f"nsfw_reject:{did}",)).fetchone()
        assert t and t["label"] == -1.0
        # the world agent got a generic journal line — no prompt text leaks
        ev = conn.execute("SELECT text FROM world_events WHERE agent_key='test_agent' "
                          "ORDER BY id DESC LIMIT 1").fetchone()
        assert ev and "badly generated" not in ev["text"]
    finally:
        conn.close()
    # the avoid-list now contains the rejected approach
    assert "badly generated private piece" in nsfw_core.recent_reject_lines("Glamour")
    # rejecting a NON-nsfw design through this route is impossible
    sfw = _mkdesign(prompt="normal design", nsfw=0, source="pipeline")
    assert client.post(f"/api/nsfw/item/{sfw}/reject").status_code == 404
    conn = db.get_conn()
    conn.execute("DELETE FROM designs WHERE id=?", (sfw,))
    conn.commit(); conn.close()


# ── world hook gating ────────────────────────────────────────────────────────
def test_world_hook_gating(client):
    assert nsfw_core.world_active() is False
    _set(client, nsfw_world="true")           # world alone is not enough
    assert nsfw_core.world_active() is False
    _set(client, nsfw_enabled="true")
    assert nsfw_core.world_active() is True
    # world_cycle refuses to run when gated off
    _set(client, nsfw_enabled="")
    assert nsfw_core.world_cycle()["ok"] is False


def test_world_taste_sync_skips_nsfw_rows(client):
    """NSFW work must not skew the SFW taste model (only explicit deny examples)."""
    import world_taste
    gid = _mkgen(prompt="unique nsfw taste probe zzqx", status="done")
    did = _mkdesign(prompt="unique nsfw taste probe zzqx", gen_id=gid)
    conn = db.get_conn()
    try:
        conn.execute("UPDATE designs SET status='rejected' WHERE id=?", (did,))
        conn.commit()
        world_taste.sync(conn)
        rows = conn.execute("SELECT skey FROM world_taste WHERE text LIKE '%zzqx%'").fetchall()
        assert not rows, f"nsfw rows leaked into taste sync: {[r['skey'] for r in rows]}"
    finally:
        conn.execute("DELETE FROM designs WHERE id=?", (did,))
        conn.execute("DELETE FROM generations WHERE id=?", (gid,))
        conn.commit(); conn.close()


# ── model slot ───────────────────────────────────────────────────────────────
def test_nsfw_model_slot_auto_detect(client, monkeypatch):
    import model_registry
    # explicit setting wins
    _set(client, nsfw_model="my/custom-model")
    assert model_registry.resolve("nsfw_model") == "my/custom-model"
    _set(client, nsfw_model="")
    # auto-detect prefers an uncensored Qwen from the node's model list
    monkeypatch.setattr(nsfw_core, "_lmstudio_models",
                        lambda: ["google/gemma-4-12b-qat", "qwen3-14b-abliterated", "llama-x"])
    assert model_registry.resolve("nsfw_model") == "qwen3-14b-abliterated"
    monkeypatch.setattr(nsfw_core, "_lmstudio_models",
                        lambda: ["mistral-uncensored-7b", "llama-x"])
    assert model_registry.resolve("nsfw_model") == "mistral-uncensored-7b"
    # nothing uncensored installed → falls back to the global text LLM
    monkeypatch.setattr(nsfw_core, "_lmstudio_models", lambda: ["google/gemma-4-12b-qat"])
    assert model_registry.resolve("nsfw_model") == model_registry.resolve("enhance_model")
    # the slot exists in the registry UI listing
    assert any(s["key"] == "nsfw_model" for s in model_registry.slots())


# ── prompt registry ──────────────────────────────────────────────────────────
def test_nsfw_prompts_registered_in_workbench(client):
    r = client.get("/api/prompts").json()
    assert "NSFW" in r["categories"]
    keys = {p["key"]: p for p in r["prompts"]}
    for k in ("nsfw_enhance", "nsfw_bootstrap_author", "nsfw_category_run"):
        assert k in keys and keys[k]["category"] == "NSFW"
    assert keys["nsfw_category_run"]["templated"] is True
    assert "{brief}" in keys["nsfw_category_run"]["default"]
    assert "{avoid}" in keys["nsfw_category_run"]["default"]
