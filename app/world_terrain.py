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
def _generate(theme):
    """Worker body. Renders ONE large terrain image, QA-gates it, installs it.
    Never raises out of the thread — logs + sets a failed status instead."""
    try:
        theme = (theme or ws.s("world_theme") or "cozy fantasy").strip()
        _set_status("generating", "rendering whole-world terrain image")
        TERRAIN_DIR.mkdir(parents=True, exist_ok=True)
        model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
        lora = ws.s("world_prop_lora")
        prompt = _prompt(theme)
        raw = TERRAIN_DIR / "_raw_terrain.png"
        ok = False
        orch.image_acquire()
        try:
            try:
                res = subprocess.run(
                    [str(GENERATE_SCRIPT), prompt, str(raw), GEN_SIZE, GEN_SIZE, GEN_STEPS,
                     str(random.randint(1, 2**31 - 1)), model, lora],
                    capture_output=True, text=True, timeout=600)
            except subprocess.TimeoutExpired:
                log.error("terrain render timed out after 600s (model=%s %sx%s)",
                          model, GEN_SIZE, GEN_SIZE)
                _set_status("failed",
                            f"render timed out after 600s (model={model}, {GEN_SIZE}x{GEN_SIZE})")
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
        _meta_set({"path": f"world_assets/terrain/{OUT_FILE}", "v": v, "prompt": prompt})
        _set_status("done", f"terrain image v{v} installed")
    except Exception as e:
        log.exception("world terrain generation crashed: %s", e)
        try:
            _set_status("failed", "generation crashed (see logs)")
        except Exception:
            pass


def start_generate(theme=None):
    """Kick a background render. Returns False if one is already running."""
    if not _lock.acquire(blocking=False):
        return False

    def _run():
        try:
            _generate(theme)
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
