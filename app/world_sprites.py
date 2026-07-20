"""
THE COMPANY — per-entity sprite-sheet registry (the "own look" system, done right).

Every agent / player / building / mob / thing owns a cached SET of sprite sheets:

    static/world_assets/entities/<entity_id>/<action>.png     64px horizontal sheet
                                                              (the pack's frame count for that action)
    static/world_assets/entities/<entity_id>/manifest.json    frames/size/QA/provenance per sheet
    static/world_assets/entities/<entity_id>/base.png         the single source sprite (transparent)

When an entity needs a new action (or acquires a new object), the sheet for
"that entity doing that action" is made ONCE — queued through the same GPU
discipline as every world render (orch.image_acquire, one at a time), gated,
then reused forever. Never regenerated per use.

Gates (all enforced before a sheet may land in a manifest):
  * TRANSPARENCY — the old system's core bug was picture-boxes: entities walking
    around as opaque squares with baked backgrounds. `alpha_ok` rejects any
    render whose cutout failed (opaque, or shredded); opaque outputs retry with
    a fresh seed and never install.
  * QA — world_vision.evaluate_asset scores the base sprite like any world prop
    (blind-permissive when no vision model is around, same as the builder).
  * PACK FIRST — the downloaded asset library (static/world_assets/packs) is
    consulted before spending GPU: an action the anokolisa Body_A pack already
    animates resolves to source='pack' for entities without an established own
    look, and a prop label matching an extracted pack sprite never renders.

Animation frames are REAL DRAWINGS, one GPU render per key pose (world_anim owns
the pose scripts, the splitter and the QA). The old system derived a "4-frame"
sheet from ONE still by rotating / nudging / brightening it, so a walk cycle was
the same sprite swaying and the legs never moved. That path is gone: an action
now renders 2-3 genuinely different poses, they are vetted for articulation and
character identity, and the keys are expanded through the action's cycle into a
sheet with the SAME frame count the anokolisa pack uses (walk 6, idle 4, work 8…)
so it stays drop-in for the renderer.

A sheet that cannot pass the gates is NOT installed — the entity keeps falling
back to the pack sheet and then to procedural art. Shipping a static "animation"
is the bug we are fixing, so it is never the fallback.

Toggles (world_settings — gates get a toggle):
  world_sprites_enabled   on-demand get-or-enqueue may spend GPU (default ON —
                          need-triggered generation is the point of the system).
                          NOTE: with the current local stack (SDXL txt2img, no
                          IP-Adapter/ControlNet wiring) frame QA rejects most
                          generated sets for identity drift, so the pack sheets
                          do the real work. Turn this OFF to stop spending GPU
                          on attempts until a character-consistency model is in.
  world_sprites_max_hour  cap on generated sheets per rolling hour
  world_sprites_auto      slow background backfill cadence (default OFF; bulk
                          backfill is otherwise the explicit API button only)
"""
import json
import logging
import random
import re
import subprocess
import threading
import time

from deps import get_conn, orch, GENERATE_SCRIPT, DEFAULT_IMAGE_MODEL
from world_defs import WORLD_ASSETS, mget, mset, pixel_prompt
import world_settings as ws

logger = logging.getLogger("store")

ENTITIES_DIR = WORLD_ASSETS / "entities"
PACKS_DIR = WORLD_ASSETS / "packs"
ANO_ANIM = (PACKS_DIR / "anokolisa-pixel-crawler" / "Pixel Crawler - Free Pack"
            / "Entities" / "Characters" / "Body_A" / "Animations")
EXTRACTED = PACKS_DIR / "_extracted"

CELL = 64            # frame size (px) — matches the prop pipeline output
FRAMES = 4           # the established horizontal 4-frame convention
STEPS = 20           # lightning model renders near-black at 8 steps (tileset lesson)
PENDING_STALE_SEC = 15 * 60      # a restart mid-render must not wedge an action forever
FAILED_COOLDOWN_SEC = 24 * 3600  # a frame-QA rejection is systematic — do not re-burn GPU on it
ATTRIBUTION = {"pack": "Anokolisa — Pixel Crawler (free pack; attribution optional) / Kenney (CC0)"}

_gen_lock = threading.Lock()     # one sheet renders at a time (shared GPU)
_mem = {"pack_actions": None}


def _safe_id(entity_id):
    s = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(entity_id or "")).strip("._-")
    return s[:80] or None


def _dir(entity_id):
    return ENTITIES_DIR / entity_id


# ── manifest ──────────────────────────────────────────────────────────────────
def manifest(entity_id):
    """The entity's sprite set: {entity, look, seed, sheets{action: meta}, pending{action: t}}.
    Stale pending entries (server restarted mid-render) are dropped on read."""
    eid = _safe_id(entity_id)
    if not eid:
        return None
    path = _dir(eid) / "manifest.json"
    try:
        m = json.loads(path.read_text())
    except Exception:
        m = {}
    m.setdefault("entity", eid)
    m.setdefault("sheets", {})
    # Migration: sheets made before the real-pose pipeline were built by the
    # deleted transform trick (one still, rotated/nudged into "4 frames"). They
    # carry no frame-QA record, so they are dropped on read and the entity falls
    # back to the pack until a genuine sheet is rendered. Without this the world
    # keeps playing exactly the fake animations this change exists to remove.
    # NB: presence of the `qa` key, not its truthiness — with frame QA toggled
    # off the record is an empty dict, and treating that as "pre-QA" would drop
    # every sheet the owner just chose to accept, on the very next read.
    stale = [a for a, meta in (m.get("sheets") or {}).items()
             if meta.get("source") not in ("static", "pack")
             and "qa" not in (meta.get("provenance") or {})]
    if stale:
        for a in stale:
            m["sheets"].pop(a, None)
        logger.info("sprites %s: dropped %d pre-QA sheet(s) %s — they were derived, "
                    "not animated", eid, len(stale), stale)
        _save_manifest(eid, m)
    pend = m.get("pending") or {}
    now = time.time()
    fresh = {a: t for a, t in pend.items() if now - float(t or 0) < PENDING_STALE_SEC}
    if fresh != pend:
        m["pending"] = fresh
        _save_manifest(eid, m)
    else:
        m["pending"] = fresh
    return m


def _save_manifest(eid, m):
    d = _dir(eid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(m, indent=1))


def _url(eid, name):
    return f"/store/static/world_assets/entities/{eid}/{name}"


def index():
    """Every entity's ready sheets in one payload (the frontend registry poll).
    Compact: only what the renderer needs (url/frames/size/source)."""
    out = {}
    if not ENTITIES_DIR.exists():
        return out
    for d in sorted(ENTITIES_DIR.iterdir()):
        if not d.is_dir():
            continue
        m = manifest(d.name)
        sheets = {}
        for act, meta in (m.get("sheets") or {}).items():
            f = d / meta.get("file", "")
            if not meta.get("file") or not f.exists():
                continue
            sheets[act] = {"url": _url(d.name, meta["file"]),
                           "frames": meta.get("frames", FRAMES),
                           "fw": meta.get("fw", CELL), "fh": meta.get("fh", CELL),
                           # ms per frame — actions have different natural speeds
                           # (a walk is not a watering can), matching the pack
                           "spd": meta.get("spd"),
                           "source": meta.get("source", "generated"),
                           "v": (meta.get("provenance") or {}).get("t", 0)}
        if sheets or m.get("pending") or m.get("failed"):
            out[d.name] = {"sheets": sheets, "pending": sorted(m.get("pending") or {}),
                           # why an action has no own sheet — surfaced so a bad
                           # roll is visible instead of silently falling back
                           "failed": {a: f.get("reason") for a, f in (m.get("failed") or {}).items()}}
    return out


# ── the downloaded pack library, consulted before any GPU spend ──────────────
def pack_actor_actions():
    """Action modes the anokolisa Body_A pack already animates (renderer mode
    names, matching world-assets.js CHAR). Cached — it's a directory scan."""
    if _mem["pack_actions"] is not None:
        return _mem["pack_actions"]
    folder_of = {"walk": "Walk_Base", "idle": "Idle_Base", "work": "Crush_Base",
                 "slice": "Slice_Base", "collect": "Collect_Base", "fishing": "Fishing_Base",
                 "water": "Watering_Base", "carrywalk": "Carry_Walk", "carryidle": "Carry_Idle",
                 "lying": "Death_Base", "run": "Run_Base", "pierce": "Pierce_Base", "hit": "Hit_Base"}
    have = set()
    try:
        for mode, folder in folder_of.items():
            if (ANO_ANIM / folder).is_dir():
                have.add(mode)
    except Exception:
        pass
    _mem["pack_actions"] = have
    return have


def pack_match(label):
    """A prop/thing label matching an extracted pack sprite → its served URL
    (word-level match against the _extracted/ filenames; conservative on
    purpose — 'lava lamp' must NOT hijack 'prop_banner')."""
    words = set(re.findall(r"[a-z]{3,}", (label or "").lower()))
    if not words or not EXTRACTED.is_dir():
        return None
    for f in sorted(EXTRACTED.glob("*.png")):
        toks = set(re.findall(r"[a-z]{3,}", f.stem.lower())) - {"prop", "gear", "station", "bld"}
        if toks and toks <= words:
            return f"/store/static/world_assets/packs/_extracted/{f.name}"
    return None


# ── gates ────────────────────────────────────────────────────────────────────
def alpha_ok(im):
    """The picture-box gate: a real cutout sprite has transparent surroundings
    AND an opaque subject. Rejects opaque squares (background baked in) and
    shredded cutouts (flood-fill ate the art)."""
    try:
        rgba = im.convert("RGBA")
        a = rgba.getchannel("A").tobytes()
        w, h = rgba.size
        n = len(a) or 1
        opaque = sum(1 for v in a if v > 128) / n
        if not (0.04 <= opaque <= 0.90):
            return False
        # the border must be mostly transparent — an opaque frame is a baked bg
        border = ([a[x] for x in range(w)] + [a[(h - 1) * w + x] for x in range(w)]
                  + [a[y * w] for y in range(h)] + [a[y * w + w - 1] for y in range(h)])
        return sum(1 for v in border if v > 128) / max(1, len(border)) < 0.20
    except Exception:
        return False


def _qa(sprite_path, label):
    """(ok, score, issues) via world_vision — blind-permissive like the builder."""
    try:
        import world_vision
        ev = world_vision.evaluate_asset(sprite_path, label)
        sc = ev.get("score")
        if sc is None:
            return True, None, ""
        return sc >= ws.i("world_vision_min_score"), sc, ev.get("issues", "")
    except Exception:
        logger.exception("sprite QA failed (accepting blind)")
        return True, None, ""


# ── action sheets: real pose renders, expanded through the action's cycle ────
def make_static_sheet(base_im, action, dst):
    """A single-pose HOLD sheet for actions that are meant to be still (`lying`
    is drawn frozen by the renderer).

    This is deliberately NOT an animation and is never used to fake one: the old
    bug was exactly this image dressed up as four frames. It writes one frame,
    declares `frames: 1`, and the renderer simply draws it.
    """
    from PIL import Image
    im = base_im.convert("RGBA")
    if im.size != (CELL, CELL):
        im = im.resize((CELL, CELL), Image.NEAREST)
    if action == "lying":                       # laid out flat on the ground
        laid = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
        rot = im.rotate(90, expand=False, resample=Image.NEAREST)
        laid.paste(rot, (0, CELL // 6), rot)
        im = laid
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst)
    return dst


def install_sheet_image(entity_id, action, sheet_im, source="dropped-in", score=None):
    """Install an existing multi-frame SHEET image for an entity/action.

    Used for a generation that returns a contact sheet rather than single frames,
    and for an owner dropping in their own art. The image is split into cells
    (world_anim.split_sheet infers the grid from the dimensions and/or the
    transparent gutters), every cell is validated, the frames are vetted for real
    articulation + character identity, and only then is a normalized sheet in the
    pack layout written. Returns (ok, reason, meta_or_None).
    """
    import world_anim
    eid = _safe_id(entity_id)
    if not eid:
        return False, "bad entity id", None
    spec = world_anim.script_for(action)
    # split on the geometry (square cells / gutters), then only accept the
    # `expect` reading if the natural one did not work
    frames = world_anim.split_sheet(sheet_im) or world_anim.split_sheet(sheet_im,
                                                                       expect=spec["frames"])
    if not frames:
        return False, "could not split that image into frames", None
    if ws.b("world_sprites_frame_qa"):
        ok, why, metrics = world_anim.vet_frames(
            frames, action, base=_base_sprite(eid, manifest(eid)),
            gate=world_anim.gate_for(action, ws.i("world_sprites_qa_strict")))
        if not ok:
            return False, why, None
    else:
        metrics = {"note": "frame QA off (owner setting)"}
    # a drop-in that supplies exactly the KEY poses is expanded through the
    # action's cycle, so it lands in the pack's frame count like a generated one
    if len(frames) == len(spec["keys"]):
        frames = world_anim.expand(frames, action)
    d = _dir(eid)
    world_anim.build_sheet(frames, d / f"{action}.png", cell=CELL, count=len(frames))
    m = manifest(eid)
    m["sheets"][action] = {"file": f"{action}.png", "frames": len(frames), "fw": CELL,
                           "fh": CELL, "spd": spec.get("spd"), "score": score, "source": source,
                           "provenance": {"t": int(time.time()), "qa": metrics}}
    m["pending"].pop(action, None)
    _save_manifest(eid, m)
    return True, "ok", m["sheets"][action]


# ── generation (one render → gates → sheet; GPU via the orchestrator) ────────
def _matte_and_lora():
    try:
        import world_build
        return world_build._matte_model(), ws.s("world_prop_lora")
    except Exception:
        return "", ws.s("world_prop_lora")


def _render_sprite(prompt, out_raw, seed=None):
    """One ComfyUI render (caller holds the GPU via orch). True on file present."""
    matte, lora = _matte_and_lora()
    model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
    seed = str(seed or random.randint(1, 2**31 - 1))
    try:
        res = subprocess.run(
            [str(GENERATE_SCRIPT), prompt, str(out_raw), "768", "768", str(STEPS),
             seed, model, lora, "", matte],
            capture_output=True, text=True, timeout=300)
        return res.returncode == 0 and out_raw.exists()
    except Exception as ex:
        logger.error("sprite render error: %s", ex)
        return False


def _hour_budget_ok(c=None):
    """Rolling-hour cap on GPU sheet generations (world_sprites_max_hour)."""
    own = c is None
    conn = get_conn() if own else None
    cc = conn.cursor() if own else c
    try:
        raw = mget(cc, "sprites_gen_times", "[]") or "[]"
        try:
            times = [t for t in json.loads(raw) if time.time() - t < 3600]
        except Exception:
            times = []
        return len(times) < max(1, ws.i("world_sprites_max_hour"))
    finally:
        if own:
            conn.close()


def _hour_budget_spend():
    conn = get_conn()
    try:
        c = conn.cursor()
        try:
            times = [t for t in json.loads(mget(c, "sprites_gen_times", "[]") or "[]")
                     if time.time() - t < 3600]
        except Exception:
            times = []
        times.append(time.time())
        mset(c, "sprites_gen_times", json.dumps(times))
        conn.commit()
    finally:
        conn.close()


def _base_sprite(eid, m):
    """The entity's vetted transparent base sprite image, if it has one."""
    from PIL import Image
    p = _dir(eid) / "base.png"
    if not p.exists():
        return None
    try:
        im = Image.open(p).convert("RGBA")
        return im if alpha_ok(im) else None
    except Exception:
        return None


def install_base(entity_id, sprite_im, look, seed=None, score=None, actions=("idle",)):
    """Register a vetted transparent sprite as the entity's own look.

    `sprite_im` MUST already pass alpha_ok — callers (makeover, generation
    worker) gate before installing. `actions` are the sheets this entity WANTS:
    they are recorded, not fabricated. Real sheets only ever come from pose
    renders (`_generate`); the only thing installed straight from the base is a
    genuinely-static action such as `lying`. Returns the manifest.
    """
    import world_anim
    eid = _safe_id(entity_id)
    m = manifest(eid)
    d = _dir(eid)
    d.mkdir(parents=True, exist_ok=True)
    im = sprite_im.convert("RGBA")
    if im.size != (CELL, CELL):
        from PIL import Image
        im = im.resize((CELL, CELL), Image.NEAREST)
    im.save(d / "base.png")
    m["look"] = look or m.get("look") or ""
    if seed:
        m["seed"] = seed
    wanted = []
    for act in actions:
        if world_anim.script_for(act).get("static"):
            make_static_sheet(im, act, d / f"{act}.png")
            m["sheets"][act] = {"file": f"{act}.png", "frames": 1, "fw": CELL, "fh": CELL,
                                "score": score, "source": "static",
                                "provenance": {"prompt": look, "seed": seed, "t": int(time.time())}}
            m["pending"].pop(act, None)
        else:
            wanted.append(act)                 # needs real pose renders — never faked
    if wanted:
        m["wanted"] = sorted(set((m.get("wanted") or []) + wanted))
    _save_manifest(eid, m)
    return m


def _pose_prompt(look, phrase):
    """Pose FIRST, look second.

    Measured, not guessed: with the look first and the pose tacked on the end
    (`{look}, {phrase}`, what the old code did) the pose phrase is essentially
    ignored — three "different" walk frames came back as the same standing figure
    (articulation 0.015 against a 0.105 gate). Leading with the pose and pinning
    the framing produces genuinely articulated frames (0.60).
    """
    return (f"side view of a single game character, {phrase}, {look}, "
            f"full body, side profile, one character only, animation frame")


def _render_pose(eid, action, key, phrase, look, seed, d):
    """One key pose → a vetted transparent 64px frame, or None.

    Renders, pixelates and applies the picture-box gate; an opaque/shredded
    output retries once with a fresh seed. GPU is already held by the caller.
    """
    import world_build
    from PIL import Image
    raw = d / f"_raw_{action}_{key}.png"
    cand = d / f"_cand_{action}_{key}.png"
    try:
        for attempt in range(2):
            use_seed = seed if attempt == 0 else None
            if not _render_sprite(_pose_prompt(look, phrase), raw, seed=use_seed):
                continue
            world_build._pixelate(raw, cand, cells=CELL, colors=28)
            im = Image.open(cand).convert("RGBA")
            if alpha_ok(im):
                return im
            logger.warning("sprite %s/%s pose '%s' attempt %d: opaque/shredded — rejected",
                           eid, action, key, attempt)
    except Exception:
        logger.exception("sprite pose render %s/%s/%s failed", eid, action, key)
    finally:
        for f in (raw, cand):
            try:
                f.unlink()
            except Exception:
                pass
    return None


def _generate(entity_id, action, label):
    """Worker: render every KEY pose → gate each → vet the set → install.

    One GPU render per key pose (2-3 for most actions), each conditioned on the
    entity's look with a pose-specific prompt and the entity's seed so the
    character stays as close to itself as the local stack allows. The set then
    has to pass `world_anim.vet_frames`:

      * articulation — the frames must differ by more than a rigid transform can
        explain (this is the gate the old fake sheets fail);
      * identity — no frame's palette may wander off the base sprite.

    A failed set is retried once with fresh seeds. If it still fails NOTHING is
    installed: the entity falls back to the pack sheet and then to procedural
    art, which is the whole point — a static "animation" is the bug, not a
    fallback. The reason is recorded on the manifest so the owner can see it.
    """
    import world_anim
    if not _gen_lock.acquire(blocking=False):
        return {"ok": False, "reason": "busy"}
    eid = _safe_id(entity_id)
    try:
        m = manifest(eid)
        if action in (m.get("sheets") or {}):
            return {"ok": True, "cached": True}
        look = m.get("look") or pixel_prompt(label or eid.replace("_", " "),
                                             ws.s("world_theme") or "futuristic")
        spec = world_anim.script_for(action)
        keys = world_anim.keys_for(action)
        d = _dir(eid)
        d.mkdir(parents=True, exist_ok=True)
        base = _base_sprite(eid, m)
        spent = False
        frames, ok, why, metrics = [], False, "no render", {}
        try:
            orch.image_acquire()
            try:
                for attempt in range(2):               # a failed VET gets one fresh-seed retry
                    seed = m.get("seed") if attempt == 0 else None
                    frames = []
                    for key, phrase in keys:
                        im = _render_pose(eid, action, key, phrase, look, seed, d)
                        if im is None:
                            break
                        frames.append(im)
                    if len(frames) != len(keys):
                        continue
                    spent = True
                    # frame QA is a gate, so it gets a toggle (world_sprites_frame_qa)
                    # and a strictness dial (world_sprites_qa_strict, % of the pack's
                    # own articulation). Off = install whatever rendered.
                    if not ws.b("world_sprites_frame_qa"):
                        ok, why, metrics = True, "frame QA off (owner setting)", {}
                        break
                    ok, why, metrics = world_anim.vet_frames(
                        frames, action, base=base,
                        gate=world_anim.gate_for(action, ws.i("world_sprites_qa_strict")))
                    if ok:
                        break
                    logger.warning("sprite %s/%s frame QA failed (attempt %d): %s",
                                   eid, action, attempt, why)
                    # A fresh seed can rescue a weak pose spread, but it cannot
                    # rescue "the model drew a different person for each prompt"
                    # — that is a property of the stack, not of the roll. Stop
                    # rather than burn a second full set of renders on it.
                    if metrics.get("identity_spread", 0) > world_anim.IDENTITY_MAX:
                        break
            finally:
                orch.image_release()
        except Exception:
            logger.exception("sprite generation %s/%s failed", eid, action)
        if spent:
            _hour_budget_spend()
        m = manifest(eid)
        if not ok:
            # nothing installs — the render chain keeps the pack/procedural sheet
            m["pending"].pop(action, None)
            m.setdefault("failed", {})[action] = {"reason": why, "t": int(time.time()),
                                                  "metrics": metrics}
            _save_manifest(eid, m)
            return {"ok": False, "reason": why, "metrics": metrics}
        # QA the representative pose like any other world asset (blind-permissive).
        # Retried once: the vision model's reply occasionally fails to parse and
        # scores 1 on art it otherwise rates 8, and by this point three renders
        # have already been paid for — a re-ask is far cheaper than binning them.
        tmp = d / f"_qa_{action}.png"
        frames[0].save(tmp)
        qa_ok, score, issues = _qa(tmp, label or eid.replace("_", " "))
        if not qa_ok:
            logger.warning("sprite %s/%s vision QA said %s (%s) — asking once more",
                           eid, action, score, issues)
            qa_ok, score, issues = _qa(tmp, label or eid.replace("_", " "))
        try:
            tmp.unlink()
        except Exception:
            pass
        if not qa_ok:
            m["pending"].pop(action, None)
            m.setdefault("failed", {})[action] = {"reason": f"vision QA {score}: {issues}",
                                                  "t": int(time.time()), "metrics": metrics}
            _save_manifest(eid, m)
            return {"ok": False, "reason": f"vision QA rejected it ({score}: {issues})"}
        full = world_anim.expand(frames, action)
        world_anim.build_sheet(full, d / f"{action}.png", cell=CELL, count=len(full))
        if not (d / "base.png").exists():
            frames[0].save(d / "base.png")       # first vetted render = the entity's base look
            m["look"] = m.get("look") or look
        m["sheets"][action] = {"file": f"{action}.png", "frames": len(full), "fw": CELL,
                               "fh": CELL, "spd": spec.get("spd"),
                               "score": score, "source": "generated",
                               "provenance": {"prompt": look, "keys": [k for k, _ in keys],
                                              "t": int(time.time()), "qa": metrics}}
        m["pending"].pop(action, None)
        (m.get("failed") or {}).pop(action, None)
        m["wanted"] = [a for a in (m.get("wanted") or []) if a != action]
        _save_manifest(eid, m)
        return {"ok": True, "source": "generated", "frames": len(full), "metrics": metrics}
    finally:
        _gen_lock.release()


def regenerate(entity_id, action, label=""):
    """Owner-facing re-roll of ONE action sheet for ONE entity.

    Drops the cached sheet (and any recorded failure) and runs the normal gated
    generation again with fresh seeds. Deliberately synchronous-by-request but
    threaded like every other render, and still subject to the toggles and the
    hourly budget — re-rolling is not a way around them.
    """
    eid = _safe_id(entity_id)
    act = re.sub(r"[^a-z0-9_]", "", str(action or "").lower())[:24]
    if not eid or not act:
        return {"status": "unavailable", "reason": "bad id/action"}
    if not ws.b("world_sprites_enabled"):
        return {"status": "disabled"}
    if not _hour_budget_ok():
        return {"status": "capped"}
    if _gen_lock.locked():
        return {"status": "busy"}
    m = manifest(eid)
    meta = (m.get("sheets") or {}).pop(act, None)
    if meta:
        try:
            (_dir(eid) / meta.get("file", "")).unlink()
        except Exception:
            pass
    (m.get("failed") or {}).pop(act, None)
    m["pending"][act] = time.time()
    _save_manifest(eid, m)
    threading.Thread(target=_generate, args=(eid, act, label), daemon=True).start()
    return {"status": "queued", "entity": eid, "action": act}


def get_or_enqueue(entity_id, action, label="", kind="agent", force=False, _runner=None):
    """The registry's core: resolve an (entity, action) to a sheet — own cache →
    pack library → (need-gated, budget-capped) one-time generation.

      ready    the entity's own sheet exists (url in payload)
      pack     the downloaded pack already covers it — no GPU spent. Entities
               WITH an established own look (a base.png) skip this and get own
               action sheets, so their look stays consistent.
      pending  a render for it is in flight
      queued   a generation was just enqueued (one at a time, orch-serialized)
      disabled / capped / unavailable — gated off; the frontend keeps its
               procedural fallback and may ask again later.
    """
    eid = _safe_id(entity_id)
    act = re.sub(r"[^a-z0-9_]", "", str(action or "").lower())[:24]
    if not eid or not act:
        return {"status": "unavailable", "reason": "bad id/action"}
    m = manifest(eid)
    meta = (m.get("sheets") or {}).get(act)
    if meta:
        return {"status": "ready", "url": _url(eid, meta["file"]),
                "frames": meta.get("frames", FRAMES), "fw": meta.get("fw", CELL),
                "fh": meta.get("fh", CELL), "source": meta.get("source", "generated")}
    own_look = (_dir(eid) / "base.png").exists()
    if not own_look and not force:                     # pack library first — free
        if kind == "agent" and act in pack_actor_actions():
            return {"status": "pack", "attribution": ATTRIBUTION["pack"]}
        if kind != "agent":
            url = pack_match(label)
            if url:
                return {"status": "pack", "url": url, "attribution": ATTRIBUTION["pack"]}
    if act in (m.get("pending") or {}):
        return {"status": "pending"}
    # A refused action must not be re-attempted on every render tick. Frame QA
    # rejections are mostly systematic (the model cannot hold the character
    # across poses), so retrying immediately just burns the hourly budget on the
    # same answer; the owner's Re-roll button bypasses this deliberately.
    failed = (m.get("failed") or {}).get(act)
    if failed and time.time() - float(failed.get("t") or 0) < FAILED_COOLDOWN_SEC and not force:
        return {"status": "failed", "reason": failed.get("reason"),
                "metrics": failed.get("metrics")}
    if not ws.b("world_sprites_enabled"):
        return {"status": "disabled"}
    if not _hour_budget_ok():
        return {"status": "capped"}
    if _gen_lock.locked():
        return {"status": "busy"}
    m["pending"][act] = time.time()
    _save_manifest(eid, m)
    runner = _runner or (lambda: threading.Thread(
        target=_generate, args=(eid, act, label), daemon=True).start())
    runner()
    return {"status": "queued"}


# ── bulk backfill (explicit button / OFF-by-default cadence — never automatic) ─
def backfill(limit=None):
    """Give every own-look entity its core sheets, and every custom-sprite agent
    a proper transparent sheet set (their legacy static picture becomes a real
    base if it passes the gates; opaque legacy pictures are queued for a fresh
    gated render). Runs serially in the caller's thread — start via start_backfill.
    Returns a summary dict."""
    from PIL import Image
    done, queued, skipped = [], [], []
    conn = get_conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, key, name, dept, sprite_path FROM world_agents "
            "WHERE sprite_path IS NOT NULL AND sprite_path != ''").fetchall()]
    finally:
        conn.close()
    for a in rows:
        eid = _safe_id(f"agent_{a['key']}")
        m = manifest(eid)
        if "idle" in m["sheets"] and "walk" in m["sheets"]:
            skipped.append(eid)
            continue
        # legacy static picture → base, if it's genuinely transparent
        src = WORLD_ASSETS / (a["sprite_path"] or "").split("/world_assets/")[-1]
        im = None
        if src.is_file():
            try:
                cand = Image.open(src).convert("RGBA")
                if alpha_ok(cand):
                    im = cand
            except Exception:
                pass
        if im is None:
            im = _base_sprite(eid, m)
        if im is not None:
            # register the look, then ask for the CORE action sheets through the
            # normal gated path — sheets are rendered, never derived from the still
            install_base(eid, im, m.get("look") or f"pixel art villager, {a['name']}",
                         actions=("idle", "walk"))
            got = [get_or_enqueue(eid, act, label=f"full-body villager {a['name']}",
                                  kind="agent").get("status") for act in ("idle", "walk")]
            (done if "ready" in got else queued if "queued" in got else skipped).append(eid)
        else:
            # they OWN a look (paid for a makeover) but the legacy picture is an
            # opaque box — force a fresh gated render (pack shortcut skipped)
            r = get_or_enqueue(eid, "idle", label=f"full-body villager {a['name']}",
                               kind="agent", force=True)
            (queued if r.get("status") == "queued" else skipped).append(eid)
        if limit and len(done) + len(queued) >= limit:
            break
    fixed = fix_opaque_props()
    return {"ok": True, "done": done, "queued": queued, "skipped": skipped,
            "props_fixed": fixed}


def fix_opaque_props():
    """No-GPU repair for the legacy opaque prop squares: aggressive flood-fill
    knockout in place + rebuild their idle sheet. Props whose art genuinely
    fills the frame (knockout would shred it) are left for a re-render."""
    from PIL import Image
    import world_build
    fixed = []
    conn = get_conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, image_path FROM world_props WHERE status='done' "
            "AND image_path IS NOT NULL").fetchall()]
    finally:
        conn.close()
    for p in rows:
        f = WORLD_ASSETS / (p["image_path"] or "").split("/world_assets/")[-1]
        if not f.is_file():
            continue
        try:
            im = Image.open(f).convert("RGBA")
            if alpha_ok(im):
                continue
            cut = world_build._knockout_bg(im.convert("RGB"), tol=40)
            if not alpha_ok(cut):
                continue
            cut.save(f)
            world_build._make_sheet(f)
            fixed.append(f.name)
        except Exception:
            logger.exception("prop knockout repair failed for %s", f)
    return fixed


def start_backfill():
    if _gen_lock.locked():
        return False
    threading.Thread(target=backfill, daemon=True).start()
    return True


def auto_tick(conn, _run=None):
    """world_ticker hook: when `world_sprites_auto` is ON, every
    `world_sprites_auto_min` minutes backfill ONE missing sheet. OFF by default —
    on-demand need (get_or_enqueue) is the primary trigger, this cadence only
    slowly completes the sets."""
    if not ws.b("world_sprites_auto", conn):
        return None
    c = conn.cursor()
    every = max(15, ws.i("world_sprites_auto_min", conn) or 240) * 60
    now = time.time()
    last = float(mget(c, "sprites_auto_last", 0) or 0)
    if not last:
        mset(c, "sprites_auto_last", now)
        return None
    if now - last < every or _gen_lock.locked():
        return None
    mset(c, "sprites_auto_last", now)
    runner = _run or (lambda: threading.Thread(
        target=backfill, kwargs={"limit": 1}, daemon=True).start())
    runner()
    return True
