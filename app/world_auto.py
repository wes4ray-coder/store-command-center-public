"""
The Company — autonomous creation loop (Chunk 4).

The heart of "the game runs the store": creative agents periodically make media
on the local GPU (free) and file a PRAYER to publish it. Nothing goes live
without the God Console gate (world_ops.pray) — so you come back to real work
that's queued for your blessing (Review mode) or already published if free and
you flipped on Auto ≤budget.

OFF by default. Interval- and active-hour-gated so it never surprise-hammers the
GPU. One creation per cycle; one model in VRAM at a time is enforced by the
orchestrator (services.run_generation acquires the GPU).

Decoupled from the world sim (another agent's world_ticker/world_sim). Reads
world_agents read-only to attribute creations; writes only via world_ops.
"""
import base64, json, logging, os, random, threading, time
import httpx
from deps import get_conn, get_setting, _resolve_model
import services
import world_ops as wo

_LOCAL = "http://127.0.0.1:8787"   # internal calls ride the localhost auth-bypass

logger = logging.getLogger("store")

DEFAULTS = {
    "world_auto_enabled":      "0",     # master switch — off until you turn it on
    "world_auto_interval_min": "120",   # make something at most this often
    "world_auto_active_start": "8",     # only create between these hours (24h)
    "world_auto_active_end":   "22",
    "world_auto_kinds":        "image", # comma list; v1 ships image (GPU-cheap, core)
    "world_auto_govern_min":   "360",   # convene the Republic this often (0 = never)
}

# creative departments → who gets the credit
CREATIVE_DEPT = {"image": "image", "video": "video", "audio": "audio", "models3d": "models3d"}

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

_state = {"last_run": 0.0, "running": False, "thread": None, "last_result": None,
          "last_govern": 0.0, "last_sell": 0.0}

# don't create MORE media while this many publish prayers already wait — without
# backpressure the studio outruns the gallery and the queue grows forever.
BACKLOG_MAX = 6

# cadence timers survive restarts via these settings keys; otherwise every
# service restart reset last_run to 0 and fired an immediate creation burst.
_PERSIST = {"last_run": "world_auto_t_last_run", "last_govern": "world_auto_t_last_govern",
            "last_sell": "world_auto_t_last_sell"}


def _load_timers():
    for f, key in _PERSIST.items():
        try:
            _state[f] = float(get_setting(key, "0") or 0)
        except Exception:
            _state[f] = 0.0


def _stamp(field):
    _state[field] = time.time()
    try:
        conn = get_conn()
        try:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                         (_PERSIST[field], str(_state[field])))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


# ── config ───────────────────────────────────────────────────────────────────
def cfg(k):
    return get_setting(k, DEFAULTS.get(k))


def enabled():
    return str(cfg("world_auto_enabled")).lower() in ("1", "true", "yes", "on")


def _interval_sec():
    try:
        return max(5, int(cfg("world_auto_interval_min"))) * 60
    except Exception:
        return 7200


def _active_now():
    try:
        h = int(time.strftime("%H"))
        s, e = int(cfg("world_auto_active_start")), int(cfg("world_auto_active_end"))
        return s <= h < e if s < e else True
    except Exception:
        return True


SUPPORTED_KINDS = ("image", "music", "video", "3d")

THREED_IDEAS = [
    "a cute low-poly potted succulent",
    "a stylized fantasy treasure chest",
    "a small decorative geometric planter",
    "a chunky retro robot figurine",
    "a low-poly mushroom house",
    "a minimalist desk organizer tray",
]


def kinds():
    ks = [k.strip() for k in str(cfg("world_auto_kinds") or "image").split(",")
          if k.strip() in SUPPORTED_KINDS]
    return ks or ["image"]


def pick_kind():
    return random.choice(kinds())


def save_config(updates, conn=None):
    own = conn is None
    if own:
        conn = get_conn()
    try:
        for k, v in updates.items():
            if k in DEFAULTS:
                conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, str(v)))
        conn.commit()
    finally:
        if own:
            conn.close()


def _govern_sec():
    try:
        return max(0, int(cfg("world_auto_govern_min"))) * 60
    except Exception:
        return 21600


def status():
    gsec = _govern_sec()
    return {
        "enabled": enabled(),
        "interval_min": int(cfg("world_auto_interval_min")),
        "active_start": int(cfg("world_auto_active_start")),
        "active_end": int(cfg("world_auto_active_end")),
        "kinds": kinds(),
        "govern_min": int(cfg("world_auto_govern_min")),
        "running": _state["running"],
        "last_run": _state["last_run"],
        "next_due_sec": max(0, int(_state["last_run"] + _interval_sec() - time.time())) if _state["last_run"] else 0,
        "next_govern_sec": (max(0, int(_state["last_govern"] + gsec - time.time())) if (gsec and _state["last_govern"]) else 0),
        "last_result": _state["last_result"],
    }


# ── helpers ──────────────────────────────────────────────────────────────────
def _publish_backlog():
    """How many publish prayers already await — the creation backpressure gate."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM world_prayers "
                           "WHERE status='pending' AND kind LIKE 'publish_%'").fetchone()
        return int(row["n"] or 0)
    except Exception:
        return 0
    finally:
        conn.close()


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


# ── the creation cycle ───────────────────────────────────────────────────────
def run_cycle(kind="image", manual=False):
    """Run one creation. Returns a result dict. Serialized by _state['running']."""
    if _state["running"]:
        return {"ok": False, "skipped": "a creation is already in progress"}
    _state["running"] = True
    try:
        if kind == "image":
            res = _create_image()
        elif kind in ("music", "audio"):
            res = _create_audio()
        elif kind == "video":
            res = _create_video()
        elif kind == "3d":
            res = _create_3d()
        else:
            res = {"ok": False, "error": f"kind '{kind}' not supported"}
        _state["last_result"] = res
        return res
    except Exception as e:
        logger.exception("world_auto.run_cycle failed")
        _state["last_result"] = {"ok": False, "error": str(e)}
        return _state["last_result"]
    finally:
        _stamp("last_run")
        _state["running"] = False


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


def _create_audio():
    conn = get_conn()
    try:
        prompt = _fresh_prompt(conn, MUSIC_IDEAS, "audio_clips")
        agent = _pick_agent(conn, "audio")
        cur = conn.execute(
            "INSERT INTO audio_clips (kind,prompt,engine,model_id,duration,lyrics,status) "
            "VALUES ('music',?,?,?,?,?, 'queued')",
            (prompt, "musicgen", "facebook/musicgen-small", 8, None))
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

    wo.pray("publish_wordpress",
            f"Publish new track: {prompt[:44]}",
            detail=f"{agent} composed a fresh track. Publishing to example.com is free.",
            cost_cents=0,
            payload={"type": "audio", "clip_id": cid, "path": row["audio_path"], "prompt": prompt},
            agent_name=agent)
    wo.note(f"🎵 {agent} finished a new track and prays for it to be heard.",
            kind="need", from_agent=agent)
    return {"ok": True, "clip_id": cid, "agent": agent, "prompt": prompt}


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


def _publish_cults3d(conn, prayer):
    """Blessed 3D model → propose listing (LLM metadata) then publish to Cults3D,
    reusing the proven internal endpoints. Resilient: reports rather than crashes."""
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    mid = payload.get("model_id")
    if not mid:
        return "no model_id"
    try:
        # 1) draft the listing (title/desc/tags/price) — async task, poll it
        pr = httpx.post(f"{_LOCAL}/api/models3d/{mid}/propose", timeout=30)
        tid = (pr.json() or {}).get("task_id")
        if tid:
            for _ in range(40):
                time.sleep(3)
                ts = httpx.get(f"{_LOCAL}/api/tasks/{tid}", timeout=15).json()
                if ts.get("status") in ("done", "error", "cancelled", "not_found"):
                    break
        # 2) publish to Cults3D (async background on success)
        pub = httpx.post(f"{_LOCAL}/api/models3d/{mid}/publish", timeout=30)
        if pub.status_code >= 400:
            msg = (pub.json() or {}).get("detail") or pub.text[:150]
            wo.note(f"Couldn’t publish model {mid} to Cults3D: {msg}", kind="warning",
                    from_agent=prayer.get("agent_name"), conn=conn)
            return f"publish rejected: {msg}"
        wo.note(f"🧊 Model {mid} is being offered on Cults3D.", kind="praise",
                from_agent=prayer.get("agent_name"), conn=conn)
        return "publishing to Cults3D underway"
    except Exception as e:
        logger.exception("cults3d publish failed")
        wo.note(f"Tried to publish model {mid} to Cults3D but hit an error ({e}).", kind="warning",
                from_agent=prayer.get("agent_name"), conn=conn)
        return f"error: {e}"


wo.register_executor("publish_cults3d", _publish_cults3d)


# ── executor: publish an approved piece to WordPress (free) ──────────────────
def _wp_mcp():
    ep = get_setting("wp_mcp_url", "")
    tok = get_setting("wp_mcp_token", "")
    if not (ep and tok):
        return None
    from wc_client import WPMcpClient
    return WPMcpClient(ep, tok)


def _web_bytes(path, max_bytes=1_900_000):
    """(filename, bytes) sized for the web media library (≤~2 MB). The print-res
    upscales (4096px) blow past WordPress's 2 MB limit, so downscale for the gallery
    while KEEPING the full-res file on disk for Printify/Etsy. Transparency preserved."""
    import os as _os
    try:
        raw = open(path, "rb").read()
        if len(raw) <= max_bytes:
            return _os.path.basename(path), raw
        from PIL import Image
        import io
        im = Image.open(path)
        transp = im.mode in ("RGBA", "LA", "P")
        base = _os.path.splitext(_os.path.basename(path))[0]
        name, out = _os.path.basename(path), raw
        for px in (1600, 1280, 1024, 800, 640, 512):
            w = im.copy()
            w.thumbnail((px, px), Image.LANCZOS)
            buf = io.BytesIO()
            if transp:
                w.save(buf, "PNG", optimize=True); name = base + ".png"
            else:
                w.convert("RGB").save(buf, "JPEG", quality=85, optimize=True); name = base + ".jpg"
            out = buf.getvalue()
            if len(out) <= max_bytes:
                break
        return name, out
    except Exception:
        return _os.path.basename(path), open(path, "rb").read()


def _publish_wordpress(conn, prayer):
    """Blessed → upload the generated media to the WordPress media library.
    Resilient: if WP isn't configured or the upload fails, the piece stays saved
    locally and we say so — the prayer still resolves 'done'."""
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    path = payload.get("path")
    # titles arrive as "Publish new artwork/track/clip: <subject>" — keep the subject
    title = prayer["title"].split(": ", 1)[-1].strip() or "Company artwork"

    if not path or not os.path.exists(path):
        wo.note(f"Wanted to publish “{title}” but the file was missing.", kind="warning",
                from_agent=prayer.get("agent_name"), conn=conn)
        return "file missing — nothing published"

    mcp = _wp_mcp()
    if not mcp:
        wo.note(f"“{title}” is ready but WordPress isn't connected — saved locally for now.",
                kind="info", from_agent=prayer.get("agent_name"), conn=conn)
        return "saved locally (WordPress MCP not configured)"

    try:
        up_name, data = _web_bytes(path)   # downscale big print-res renders for the 2 MB WP limit
        att = mcp.upload_media_base64(up_name, data, title=title,
                                      alt_text=payload.get("prompt", title))
        wp_id = att.get("id") or att.get("attachment_id")
        wp_link = att.get("source_url") or att.get("url") or ""
        conn.execute(
            "INSERT INTO portal_pushes (source,source_ref,kind,wp_id,wp_link,title) VALUES (?,?,?,?,?,?)",
            ("world_auto", str(payload.get("gen_id") or ""), "media", str(wp_id or ""), wp_link, title))
        conn.commit()
        wo.note(f"🌐 “{title}” is now live on example.com.", kind="praise",
                from_agent=prayer.get("agent_name"), conn=conn)
        return f"published to WordPress (id {wp_id})"
    except Exception as e:
        logger.exception("world_auto publish failed")
        wo.note(f"Tried to publish “{title}” but WordPress refused ({e}). Saved locally.",
                kind="warning", from_agent=prayer.get("agent_name"), conn=conn)
        return f"publish failed: {e}"


wo.register_executor("publish_wordpress", _publish_wordpress)


# ── background loop ──────────────────────────────────────────────────────────
def _govern_tick():
    """Let the Republic self-convene: assess → vote → act. Lazy import avoids the
    world_strategy ↔ world_auto import cycle. Only ever yields free actions or
    gated prayers, so it's safe to run unattended."""
    try:
        import world_strategy
        world_strategy.run_cycle()
        wo.note("🏛️ The assembly convened on its own and set the nation's course.",
                kind="info", from_agent="The Republic")
    except Exception:
        logger.exception("world_auto govern tick failed")


def _loop():
    time.sleep(30)   # let the app settle
    while True:
        try:
            now = time.time()
            # drain the prayer queue (no-op unless budget mode; a couple per
            # minute). Deliberately NOT gated on enabled()/active hours —
            # publishing is a cheap upload decoupled from GPU creation, and the
            # auto-publish toggle is the mode itself.
            try:
                wo.sweep_pending(limit=2)
            except Exception:
                logger.exception("world_auto prayer sweep failed")
            # harvest god's latest verdicts into the taste model (~5 min cadence)
            if now - _state.get("last_taste_sync", 0) >= 300:
                _state["last_taste_sync"] = now
                try:
                    import world_taste
                    conn = get_conn()
                    try:
                        world_taste.sync(conn)
                    finally:
                        conn.close()
                except Exception:
                    logger.exception("taste sync failed")
            # pull REAL sales into the treasury (~15 min) — the missing half of the loop.
            # Not gated on enabled(): money should always be tracked, even paused.
            if now - _state.get("last_revenue_sync", 0) >= 900:
                _state["last_revenue_sync"] = now
                try:
                    import world_sell
                    r = world_sell.sync_revenue()
                    if r.get("added"):
                        logger.info("revenue sync: +%d Etsy sale(s), $%.2f to treasury",
                                    r["added"], r["revenue_cents"] / 100)
                except Exception:
                    logger.exception("revenue sync failed")
            if enabled() and _active_now():
                if (not _state["running"] and (now - _state["last_run"]) >= _interval_sec()
                        and _publish_backlog() < BACKLOG_MAX):
                    run_cycle(random.choice(kinds()))
                gsec = _govern_sec()
                if gsec and (now - _state["last_govern"]) >= gsec:
                    _stamp("last_govern")
                    _govern_tick()
                # autonomous listing — cascaded on only when master + sell toggle are on
                if str(get_setting("world_sell_auto", "0")).lower() in ("1", "true", "on"):
                    ssec = max(1, int(get_setting("world_sell_interval_min", "180") or 180)) * 60
                    if (now - _state["last_sell"]) >= ssec:
                        _stamp("last_sell")
                        try:
                            import world_sell
                            threading.Thread(target=world_sell.list_design,
                                             args=(get_setting("world_sell_channel", "etsy"),), daemon=True).start()
                        except Exception:
                            logger.exception("world_auto sell tick failed")
        except Exception:
            logger.exception("world_auto loop tick failed")
        time.sleep(60)


def start():
    if _state["thread"]:
        return
    _load_timers()
    t = threading.Thread(target=_loop, daemon=True, name="world-auto")
    _state["thread"] = t
    t.start()
    logger.info("world_auto started (enabled=%s)", enabled())
