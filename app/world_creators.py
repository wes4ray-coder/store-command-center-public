"""
The Company — per-kind creators (extracted from world_auto).

The actual media makers: one image / audio / video / 3D piece per call, each
filing a publish PRAYER through the God Console (world_ops). Also the prompt +
agent pickers and the ACE-Step "sing" path. world_auto.run_cycle dispatches
here; nothing here is gated — the scheduler in world_auto owns the gating.
"""
import logging, random, time
import httpx
from deps import get_conn, _resolve_model
import services
import world_ops as wo

_LOCAL = "http://127.0.0.1:8787"   # internal calls ride the localhost auth-bypass

logger = logging.getLogger("store")

# prompt seeds tuned for a print-on-demand / art store aesthetic
IMAGE_IDEAS = [
    "a serene minimalist mountain landscape at dawn, flat vector art, muted pastels",
    "a cozy retro coffee shop interior, warm lighting, illustrative poster style",
    "a bold geometric mandala, symmetrical, high-contrast, printable wall art",
    "a whimsical astronaut floating among glowing jellyfish, dreamy nebula backdrop",
    "vintage botanical illustration of wildflowers, cream background, fine linework",
    "a lofi city skyline at sunset, synthwave palette, clean vector shapes",
    "a cute kawaii cat wearing headphones, sticker style, thick outlines",
    "an abstract fluid-art swirl of teal and gold, elegant modern canvas print",
    "a majestic mountain fox in a pine forest, low-poly geometric style",
    "a motivational typographic poster, bold sans-serif, sunrise gradient",
    "a surreal desert with floating crystals, vaporwave colors, poster art",
    "a hand-drawn constellation map of a fantasy zodiac, ink on parchment",
]

MUSIC_IDEAS = [
    "a calm lo-fi hip-hop beat for studying, warm vinyl crackle",
    "an upbeat 8-bit chiptune adventure theme, energetic",
    "a dreamy ambient synth pad, slow and cinematic",
    "a cozy acoustic guitar loop, gentle and hopeful",
    "a driving synthwave groove, retro 80s, neon",
    "a peaceful piano melody with soft strings",
    "a funky bass-driven groove, danceable",
    "a mysterious dungeon-crawl soundtrack, tense",
]

VIDEO_IDEAS = [
    "gentle ocean waves rolling onto a beach at golden sunset",
    "abstract colorful ink swirling and blooming in water",
    "a slow flythrough of soft glowing clouds at dawn",
    "neon geometric shapes pulsing to an unseen rhythm",
    "a cozy fireplace crackling in a dim cabin",
    "cherry blossom petals drifting on a spring breeze",
]

THREED_IDEAS = [
    "a cute low-poly potted succulent",
    "a stylized fantasy treasure chest",
    "a small decorative geometric planter",
    "a chunky retro robot figurine",
    "a low-poly mushroom house",
    "a minimalist desk organizer tray",
]


def _fresh_prompt(conn, ideas, table):
    """Pick an idea not used by the last few rows of `table`, weighted by the
    god-taste model — the studio leans toward what god has actually blessed
    (75% exploit / 25% explore so it keeps testing new directions)."""
    try:
        rows = conn.execute(f"SELECT prompt FROM {table} ORDER BY id DESC LIMIT 8").fetchall()
        used = {r["prompt"] for r in rows}
        pool = [p for p in ideas if p not in used]
    except Exception:
        pool = []
    pool = pool or list(ideas)
    try:
        import world_taste
        if random.random() < 0.75 and world_taste.stats(conn)["trained"]:
            scored = sorted(((world_taste.score(conn, p), p) for p in pool), reverse=True)
            logger.info("world_auto taste pick: %.2f %s", scored[0][0], scored[0][1][:50])
            return scored[0][1]
    except Exception:
        logger.exception("taste-weighted pick failed (random fallback)")
    return random.choice(pool)


def _pick_agent(conn, dept):
    row = conn.execute("SELECT name FROM world_agents WHERE dept=? ORDER BY RANDOM() LIMIT 1", (dept,)).fetchone()
    if row:
        return row["name"]
    row = conn.execute("SELECT name FROM world_agents ORDER BY RANDOM() LIMIT 1").fetchone()
    return row["name"] if row else "The Studio"


# The Company makes a MIX of product types (weighted) so it exercises the specialty
# models — run_generation picks the matching LoRA/upscaler/cutout per type (gen_models).
_WORLD_PRODUCTS = ([("Poster", 3), ("Sticker", 3), ("T-Shirt", 3),
                    ("Tote Bag", 1), ("Coloring Book", 1), ("Art", 2)])


def _pick_product_type():
    import random as _r
    pool = [t for t, wt in _WORLD_PRODUCTS for _ in range(wt)]
    return _r.choice(pool)


def _create_image():
    conn = get_conn()
    try:
        model = _resolve_model(conn, None)
        prompt = _fresh_prompt(conn, IMAGE_IDEAS, "generations")
        ptype = _pick_product_type()
        agent = _pick_agent(conn, "image")
        cur = conn.execute(
            "INSERT INTO generations (prompt,product_type,width,height,steps,model,source) "
            "VALUES (?,?,?,?,?,?,?)",
            (prompt, ptype, 1024, 1024, 20, model, "world_auto"))
        gid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    services.run_generation(gid)   # blocks on the GPU; orchestrator serializes

    conn = get_conn()
    try:
        row = conn.execute("SELECT status,image_path FROM generations WHERE id=?", (gid,)).fetchone()
    finally:
        conn.close()

    if not row or row["status"] != "done" or not row["image_path"]:
        wo.note(f"{agent} reached for the muse but the canvas stayed blank (generation {gid} failed).",
                kind="warning", from_agent=agent)
        return {"ok": False, "gen_id": gid, "error": "generation did not complete"}

    wo.pray("publish_wordpress",
            f"Publish new artwork: {prompt[:48]}",
            detail=f"{agent} created a fresh piece. Publishing to example.com is free.",
            cost_cents=0,
            payload={"type": "image", "gen_id": gid, "path": row["image_path"], "prompt": prompt},
            agent_name=agent)
    wo.note(f"🎨 {agent} finished a new piece and prays for it to reach the gallery.",
            kind="need", from_agent=agent)
    return {"ok": True, "gen_id": gid, "agent": agent, "prompt": prompt}


def rework_image(base_prompt, ptype="Art", agent=None, reason=""):
    """Regenerate a REJECTED image with god's feedback baked in, then re-file it for
    judging. This is the reject → tweak loop (called from world_ops._maybe_rework in a
    background thread). Keeps the same product type so a rejected sticker stays a sticker.
    """
    reason = (reason or "").strip()
    # strip any prior feedback suffix so notes don't accumulate across re-rejections
    base = (base_prompt or "").split("  [feedback:")[0].strip()
    fix = (f"  [feedback: {reason}]" if reason
           else "  [feedback: try a fresh take — different subject or composition]")
    prompt = base + fix
    ptype = ptype or "Art"
    conn = get_conn()
    try:
        if not agent:
            agent = _pick_agent(conn, "image")
        model = _resolve_model(conn, None)
        cur = conn.execute(
            "INSERT INTO generations (prompt,product_type,width,height,steps,model,source) "
            "VALUES (?,?,?,?,?,?,?)",
            (prompt, ptype, 1024, 1024, 20, model, "world_auto"))
        gid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    services.run_generation(gid)

    conn = get_conn()
    try:
        row = conn.execute("SELECT status,image_path FROM generations WHERE id=?", (gid,)).fetchone()
    finally:
        conn.close()
    if not row or row["status"] != "done" or not row["image_path"]:
        wo.note(f"{agent} tried to rework the rejected piece, but the render failed.",
                kind="warning", from_agent=agent)
        return {"ok": False, "gen_id": gid}

    wo.pray("publish_wordpress",
            f"Reworked artwork: {base[:44]}",
            detail=f"{agent} took your note to heart and reworked the piece. Free to publish.",
            cost_cents=0,
            payload={"type": "image", "gen_id": gid, "path": row["image_path"], "prompt": prompt},
            agent_name=agent)
    wo.note(f"🖌️ {agent} reworked a rejected piece with your feedback — take another look.",
            kind="need", from_agent=agent)
    return {"ok": True, "gen_id": gid, "agent": agent}


_acestep = {"ok": None, "t": 0.0}


def _acestep_ok():
    """Is ACE-Step (vocal songs) installed on the GPU node? Cached 10 min — it's
    an ssh round-trip. Any failure = not available (fall back to instrumental)."""
    now = time.time()
    if _acestep["ok"] is not None and now - _acestep["t"] < 600:
        return _acestep["ok"]
    try:
        import subprocess
        from config import BOX_SSH
        r = subprocess.run(BOX_SSH + ["[ -f ~/ACE-Step/acestep/pipeline_ace_step.py ] "
                                      "&& [ -x ~/ace-venv/venv/bin/python3 ]"],
                           capture_output=True, timeout=15)
        _acestep["ok"] = r.returncode == 0
    except Exception:
        _acestep["ok"] = False
    _acestep["t"] = now
    return _acestep["ok"]


def _write_lyrics(agent, theme):
    """The agent writes its own short lyrics via the store LLM proxy (rides the
    GPU queue). Returns lyrics text or None — any failure means instrumental."""
    try:
        from prompts import get_prompt
        sysp = get_prompt("world_music_lyrics").format(agent=agent, theme=theme)
        import model_registry
        body = {"model": model_registry.for_task("world_music_lyrics")
                         or model_registry.resolve("enhance_model"),
                "messages": [{"role": "system", "content": sysp},
                             {"role": "user", "content": f"Write the song now. Theme: {theme}"}],
                "max_tokens": 400, "temperature": 0.9, "stream": False}
        r = httpx.post(f"{_LOCAL}/api/llm/v1/chat/completions", json=body, timeout=300)
        txt = (r.json()["choices"][0]["message"]["content"] or "").strip()
        txt = txt.strip("`").removeprefix("Lyrics:").strip()
        return txt if 30 <= len(txt) <= 1200 else None
    except Exception:
        logger.exception("agent lyrics failed — falling back to instrumental")
        return None


def _create_audio():
    conn = get_conn()
    try:
        prompt = _fresh_prompt(conn, MUSIC_IDEAS, "audio_clips")
        agent = _pick_agent(conn, "audio")
    finally:
        conn.close()

    # The agent may choose to SING: own lyrics + a full vocal song via ACE-Step
    # (Company Settings toggle; needs ACE-Step installed on the node). Roughly
    # half take the mic when allowed; everything else stays instrumental.
    lyrics, engine, model_id, duration = None, "musicgen", "facebook/musicgen-small", 8
    try:
        import world_settings as WSET
        if WSET.b("world_music_lyrics") and random.random() < 0.5 and _acestep_ok():
            lyrics = _write_lyrics(agent, prompt)
            if lyrics:
                engine, model_id, duration = "acestep", "ACE-Step/ACE-Step-v1-3.5B", 60
    except Exception:
        logger.exception("lyrics decision failed — instrumental")

    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO audio_clips (kind,prompt,engine,model_id,duration,lyrics,status) "
            "VALUES ('music',?,?,?,?,?, 'queued')",
            (prompt, engine, model_id, duration, lyrics))
        cid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    services.run_audio_clip(cid)   # blocks on GPU; orchestrator serializes

    conn = get_conn()
    try:
        row = conn.execute("SELECT status,audio_path FROM audio_clips WHERE id=?", (cid,)).fetchone()
    finally:
        conn.close()
    if not row or row["status"] != "done" or not row["audio_path"]:
        wo.note(f"{agent} reached for a melody but the studio fell silent (clip {cid} failed).",
                kind="warning", from_agent=agent)
        return {"ok": False, "clip_id": cid, "error": "audio did not complete"}

    sang = " — with their own lyrics, sung" if lyrics else ""
    wo.pray("publish_wordpress",
            f"Publish new track: {prompt[:44]}",
            detail=f"{agent} composed a fresh track{sang}. Publishing to example.com is free.",
            cost_cents=0,
            payload={"type": "audio", "clip_id": cid, "path": row["audio_path"], "prompt": prompt,
                     "lyrics": lyrics},
            agent_name=agent)
    wo.note(f"🎵 {agent} {'wrote and SANG an original song' if lyrics else 'finished a new track'} "
            "and prays for it to be heard.", kind="need", from_agent=agent)
    return {"ok": True, "clip_id": cid, "agent": agent, "prompt": prompt, "lyrics": bool(lyrics)}


def _create_video():
    conn = get_conn()
    try:
        prompt = _fresh_prompt(conn, VIDEO_IDEAS, "videos")
        agent = _pick_agent(conn, "video")
        cur = conn.execute(
            "INSERT INTO videos (prompt,width,height,num_frames,steps,fps,seed,status,model_id) "
            "VALUES (?,?,?,?,?,?,?, 'queued', ?)",
            (prompt, 832, 480, 49, 20, 16, 0, "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"))
        vid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    services.run_video_generation(vid)   # heavy; orchestrator serializes

    conn = get_conn()
    try:
        row = conn.execute("SELECT status,video_path FROM videos WHERE id=?", (vid,)).fetchone()
    finally:
        conn.close()
    if not row or row["status"] != "done" or not row["video_path"]:
        wo.note(f"{agent} tried to film a scene but the reel jammed (video {vid} failed).",
                kind="warning", from_agent=agent)
        return {"ok": False, "video_id": vid, "error": "video did not complete"}

    wo.pray("publish_wordpress",
            f"Publish new clip: {prompt[:44]}",
            detail=f"{agent} produced a fresh clip. Publishing to example.com is free.",
            cost_cents=0,
            payload={"type": "video", "video_id": vid, "path": row["video_path"], "prompt": prompt},
            agent_name=agent)
    wo.note(f"🎬 {agent} wrapped a new clip and prays for its premiere.",
            kind="need", from_agent=agent)
    return {"ok": True, "video_id": vid, "agent": agent, "prompt": prompt}


def _create_3d():
    """Text→mesh via the proven 3D pipeline (SDXL→TripoSR on the GPU box), then a
    publish_cults3d prayer. Reuses the /api/models3d/generate endpoint so there's
    no duplicated pipeline logic."""
    conn = get_conn()
    try:
        agent = _pick_agent(conn, "models3d")
    finally:
        conn.close()
    prompt = random.choice(THREED_IDEAS)
    try:
        r = httpx.post(f"{_LOCAL}/api/models3d/generate",
                       json={"prompt": prompt, "generator": "triposr", "title": prompt[:60]},
                       timeout=30)
        mid = (r.json() or {}).get("model_id")
    except Exception as e:
        wo.note(f"{agent} tried to sculpt but the kiln wouldn't start ({e}).", kind="warning", from_agent=agent)
        return {"ok": False, "error": str(e)}
    if not mid:
        return {"ok": False, "error": "no model_id from generate"}

    # 3D is slow (image render + mesh on the box) — poll until it has renders or errors
    ready = False
    for _ in range(90):        # up to ~9 min
        time.sleep(6)
        conn = get_conn()
        try:
            row = conn.execute("SELECT status,render_paths,hero_paths FROM models3d WHERE id=?", (mid,)).fetchone()
        finally:
            conn.close()
        if not row:
            break
        if row["status"] == "error":
            wo.note(f"{agent}'s sculpture cracked in the kiln (model {mid} failed).", kind="warning", from_agent=agent)
            return {"ok": False, "model_id": mid, "error": "3d generation failed"}
        imgs = (row["render_paths"] or "[]") != "[]" or (row["hero_paths"] or "[]") != "[]"
        if imgs and row["status"] != "generating":
            ready = True
            break
    if not ready:
        wo.note(f"{agent}'s sculpture is still curing (model {mid}) — will offer it once ready.",
                kind="info", from_agent=agent)
        return {"ok": False, "model_id": mid, "error": "not ready in time"}

    wo.pray("publish_cults3d",
            f"Publish 3D model to Cults3D: {prompt[:40]}",
            detail=f"{agent} sculpted a new model. Cults3D publishing is free.",
            cost_cents=0,
            payload={"type": "3d", "model_id": mid, "prompt": prompt},
            agent_name=agent)
    wo.note(f"🧊 {agent} finished a 3D model and prays to offer it on Cults3D.", kind="need", from_agent=agent)
    return {"ok": True, "model_id": mid, "agent": agent, "prompt": prompt}
