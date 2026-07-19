"""THE COMPANY — Layer 2: one-shot whole-world terrain image.

Instead of painting terrain tile-by-tile (world_tileset.py) or per-cell
procedural art (world-map.js `_tile`), this module generates ONE large top-down
image of the entire map's GROUND — grass fields, dirt roads, a central plaza,
ponds, forest edges, northern mountains — and the client blits it under the
buildings as the terrain.

Terrain LOGIC never moves off the logical grid: pathfinding / water animation /
desire-line wear all still read `grid[r][c]`. This image is a pure visual skin,
and it is OFF by default (`world_terrain_image_enabled` = "0"): procedural
terrain shows until you both enable the setting AND generate an image.

Mirrors world_tileset.py's lock / status / orch-hold structure. Import-safe:
no heavy work (PIL / subprocess) runs at import time.
"""
import base64
import json
import logging
import random
import subprocess
import re
import threading
import time

from deps import get_conn, orch, GENERATE_SCRIPT, DEFAULT_IMAGE_MODEL
from world_defs import WORLD_ASSETS, mget, mset
import world_settings as ws

log = logging.getLogger("world_terrain")

TERRAIN_DIR = WORLD_ASSETS / "terrain"
OUT_FILE = "world_terrain.png"
META_KEY = "terrain_image"          # world_meta blob: {"path", "v", "prompt"}

# Match the client map dimensions (world-map.js: TILE=20 * COLS=132 x ROWS=104).
# Render a 1024² square (not 1536²): the RTX 3060's 12GB is usually shared with a
# resident LLM (~8-9GB), so 1536² SDXL left almost no VRAM headroom → slow renders
# (~100s) and intermittent OOM/timeout that surfaced as the misleading "GPU box
# reachable?" note. 1024² halves the latent, renders fast, and is downscaled to
# MAP_W×MAP_H anyway so the visible quality of the background skin is unchanged.
GEN_SIZE = "1024"                   # one large square render (generate.sh W/H)
GEN_STEPS = "24"
MAP_W, MAP_H = 132 * 20, 104 * 20   # world-map.js TILE*COLS x TILE*ROWS = 2640x2080
                                    # (the render is downscaled to this to skin the ground)
# img2img (layout-guided) render size — matches the map's 2640x2080 = 1.269:1 aspect
# (1216x960 = 1.267:1) so the client-rendered roads/water/plaza stay aligned. Used
# only when a base_png layout image is supplied; text-only renders stay square.
I2I_W, I2I_H = 1216, 960

# layout-guided (img2img) prompt: preserve the supplied layout, only add texture.
LAYOUT_PROMPT = (
    "top-down orthographic pixel-art town ground, keep the existing road, water, "
    "plaza and field layout exactly, add rich grass, dirt, cobblestone and water "
    "texture, no buildings, no characters, no text, no grid lines"
)

_lock = threading.Lock()


# ── world_meta helpers (same table build.py's layout uses) ───────────────────
def _meta_get():
    conn = get_conn()
    try:
        raw = mget(conn.cursor(), META_KEY)
    finally:
        conn.close()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _meta_set(val):
    conn = get_conn()
    try:
        mset(conn.cursor(), META_KEY, json.dumps(val))
        conn.commit()
    finally:
        conn.close()


def _meta_clear():
    conn = get_conn()
    try:
        conn.execute("DELETE FROM world_meta WHERE key=?", (META_KEY,))
        conn.commit()
    finally:
        conn.close()


def _set_status(state, note=""):
    conn = get_conn()
    try:
        mset(conn.cursor(), "terrain_status",
             json.dumps({"state": state, "note": note, "t": time.time()}))
        conn.commit()
    finally:
        conn.close()


def _status_raw():
    conn = get_conn()
    try:
        raw = mget(conn.cursor(), "terrain_status", "") or ""
    finally:
        conn.close()
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


# ── public status ────────────────────────────────────────────────────────────
def status():
    """{generating, has_image, url, v, enabled, state, note}.

    `enabled` reflects the `world_terrain_image_enabled` setting so the client can
    gate the swap without a second request; the feature is OFF by default so the
    procedural map always wins unless you both enable it AND generate an image."""
    st = _status_raw()
    generating = _lock.locked()
    # restart-reconcile: a crash mid-render leaves a stale "generating" note; the
    # worker thread is gone, so surface it as failed once the lock is free.
    if st.get("state") == "generating" and not generating \
            and time.time() - float(st.get("t") or 0) > 900:
        st = {"state": "failed", "note": "interrupted by a restart — generate again"}
        _set_status(st["state"], st["note"])
    meta = _meta_get() or {}
    v = int(meta.get("v") or 0)
    has_image = bool(meta) and (TERRAIN_DIR / OUT_FILE).exists()
    return {
        "generating": generating,
        "has_image": has_image,
        "enabled": ws.b("world_terrain_image_enabled"),
        "url": f"world_assets/terrain/{OUT_FILE}?v={v}" if has_image else None,
        "v": v,
        "prompt": meta.get("prompt") or "",
        "mode": meta.get("mode") or "",
        "state": st.get("state") or ("done" if has_image else "none"),
        "note": st.get("note") or "",
    }


# ── prompt ───────────────────────────────────────────────────────────────────
def _prompt(theme):
    theme = (theme or "").strip()
    base = (
        "top-down orthographic map of a whole cozy town, the GROUND, "
        "lush green grass fields, winding dirt and cobblestone roads, "
        "a central stone plaza, small ponds and a lake with blue water, "
        "forest edges with clusters of trees, a rugged mountain range along the "
        "north edge, gentle countryside, warm cozy pixel-art game world, "
        "seamless natural terrain, soft even lighting, "
        "no buildings, no houses, no characters, no people, no text, no grid lines, "
        "flat top-down ground texture only"
    )
    p = f"{theme} {base}".strip() if theme else base
    # generate.sh embeds the prompt into a Python heredoc via bash ${PROMPT@Q},
    # which mangles apostrophes/quotes/backslashes into invalid Python ('town'\''s'
    # -> "unexpected character after line continuation character"). Strip the chars
    # that trip that so any theme/prompt is safe.
    return re.sub(r"['\"\\`]", "", p)


def _image_ok(path):
    """Loose QA: reject a near-black / empty render (reuse the tilegate check)."""
    try:
        from PIL import Image
        from world_tilegate import _tile_ok
        im = Image.open(path).convert("RGB")
        # sample a downscaled copy so the brightness/spread check is cheap
        return _tile_ok(im.resize((128, 128)))
    except Exception:
        return False


# ── generation ───────────────────────────────────────────────────────────────
def _prep_base(base_png):
    """Decode a base_png (dataURL string or a saved path) → an init PNG under
    TERRAIN_DIR resized to the map aspect (I2I_W×I2I_H) so roads align. Returns the
    init path (str) on success, or None if nothing usable was supplied / decode
    failed (caller then falls back to text-only generic terrain)."""
    if not base_png:
        return None
    try:
        from PIL import Image
        import io
        raw_bytes = None
        s = base_png.strip() if isinstance(base_png, str) else base_png
        if isinstance(s, str) and s.startswith("data:"):
            # data:image/png;base64,....  → strip the header, decode the payload
            _, _, b64 = s.partition(",")
            raw_bytes = base64.b64decode(b64)
        elif isinstance(s, str):
            # treat as a filesystem path to an existing PNG
            with open(s, "rb") as fh:
                raw_bytes = fh.read()
        if not raw_bytes:
            return None
        im = Image.open(io.BytesIO(raw_bytes)).convert("RGB").resize((I2I_W, I2I_H))
        init_path = TERRAIN_DIR / "_init_layout.png"
        im.save(init_path)
        return str(init_path)
    except Exception as e:
        log.warning("terrain base_png decode failed, falling back to generic: %s", e)
        return None


def _generate(theme, base_png=None, denoise=0.55):
    """Worker body. Renders ONE large terrain image, QA-gates it, installs it.
    When base_png is supplied, runs layout-guided img2img (the init image's
    roads/water/plaza are preserved, only texture is added); otherwise the classic
    text-only generic terrain. Never raises out of the thread — logs + sets a
    failed status instead."""
    try:
        theme = (theme or ws.s("world_theme") or "cozy fantasy").strip()
        TERRAIN_DIR.mkdir(parents=True, exist_ok=True)
        init_path = _prep_base(base_png)
        layout_mode = bool(init_path)
        _set_status("generating",
                    "rendering layout-guided terrain image" if layout_mode
                    else "rendering whole-world terrain image")
        model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
        lora = ws.s("world_prop_lora")
        # layout-guided: preserve the client-rendered layout, only add texture.
        prompt = _prompt(LAYOUT_PROMPT) if layout_mode else _prompt(theme)
        # img2img takes its W/H from the init image → use the map-aspect size so the
        # roads align; text-only stays the square GEN_SIZE.
        gen_w = str(I2I_W) if layout_mode else GEN_SIZE
        gen_h = str(I2I_H) if layout_mode else GEN_SIZE
        raw = TERRAIN_DIR / "_raw_terrain.png"
        ok = False
        orch.image_acquire()
        try:
            try:
                cmd = [str(GENERATE_SCRIPT), prompt, str(raw), gen_w, gen_h, GEN_STEPS,
                       str(random.randint(1, 2**31 - 1)), model, lora]
                if layout_mode:
                    # args 9 (upscale) + 10 (matte) stay empty; 11 = init, 12 = denoise
                    cmd += ["", "", init_path, str(denoise)]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except subprocess.TimeoutExpired:
                log.error("terrain render timed out after 600s (model=%s %sx%s)",
                          model, gen_w, gen_h)
                _set_status("failed",
                            f"render timed out after 600s (model={model}, {gen_w}x{gen_h})")
                return
            ok = res.returncode == 0 and raw.exists()
            if not ok:
                # Surface the REAL failure — the generator's own stderr/stdout — instead
                # of a generic "is the GPU box reachable?" guess. generate.sh emits lines
                # like "ERROR: Generation timed out", "ERROR: Could not start ComfyUI",
                # or a ComfyUI validation/OOM error; keep the last, most-specific line.
                raw_err = (res.stderr or res.stdout or "").strip()
                last = raw_err.splitlines()[-1] if raw_err else "(no output from generator)"
                log.error("terrain render failed (rc=%s model=%s): %s",
                          res.returncode, model, raw_err[-600:])
                _set_status("failed",
                            f"render failed (rc={res.returncode}, model={model}): {last[:220]}")
        finally:
            orch.image_release()
        if not ok:
            return
        if not _image_ok(raw):
            _set_status("failed", "render was near-black / empty — try again")
            try:
                raw.unlink()
            except Exception:
                pass
            return
        # downscale/normalise to the map dimensions and install as the ground
        try:
            from PIL import Image
            Image.open(raw).convert("RGB").resize((MAP_W, MAP_H)).save(TERRAIN_DIR / OUT_FILE)
        finally:
            try:
                raw.unlink()
            except Exception:
                pass
        v = int((_meta_get() or {}).get("v") or 0) + 1
        mode = "layout" if layout_mode else "generic"
        _meta_set({"path": f"world_assets/terrain/{OUT_FILE}", "v": v,
                   "prompt": prompt, "mode": mode})
        _set_status("done", f"{mode} terrain image v{v} installed")
    except Exception as e:
        log.exception("world terrain generation crashed: %s", e)
        try:
            _set_status("failed", "generation crashed (see logs)")
        except Exception:
            pass


def start_generate(theme=None, base_png=None, denoise=0.55):
    """Kick a background render. Returns False if one is already running.

    base_png (a dataURL or a saved PNG path) enables layout-guided img2img: the
    client-rendered town layout is fed to the generator as the init image so the
    output terrain matches the real roads/water/plaza. No base_png → the classic
    text-only generic terrain (backward compatible)."""
    try:
        denoise = float(denoise)
    except (TypeError, ValueError):
        denoise = 0.55
    if not _lock.acquire(blocking=False):
        return False

    def _run():
        try:
            _generate(theme, base_png=base_png, denoise=denoise)
        finally:
            _lock.release()
    threading.Thread(target=_run, daemon=True).start()
    return True


def remove():
    """Back to procedural terrain: drop the meta blob + the image file."""
    _meta_clear()
    try:
        (TERRAIN_DIR / OUT_FILE).unlink()
    except Exception:
        pass
    _set_status("removed")
    return True
