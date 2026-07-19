"""THE COMPANY — the moon's generated pixel-art texture.

Near-clone of world_floors.py / world_terrain.py, but for the MOON that drifts across
the night sky (world-sky.js `drawMoon`). Instead of the procedural cratered disc the
client draws by default, this generates ONE square top-down lunar-surface texture that
the client clips to a circle for the moon. The SAME texture becomes the ground of the
zoomable moon MAP in Phase 4 — so it's a full square surface (no background matte).

Pure visual enhancement: the procedural moon always shows at night; a generated texture
just swaps in when present. Mirrors the floor/terrain lock / status / meta / orch-hold
structure. Import-safe: no heavy work at import time.
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

log = logging.getLogger("world_moon")

MOON_DIR = WORLD_ASSETS / "sky" / "moon"
OUT_FILE = "moon.png"
META_KEY = "moon_image"             # world_meta blob: {"path", "v", "prompt"}

# A square lunar-surface texture. 1024² renders fast and shares VRAM politely; it's
# displayed small (clipped to a disc) but doubles as the moon-map ground, so keep detail.
GEN_SIZE = "1024"
GEN_STEPS = "24"

_lock = threading.Lock()


# ── world_meta helpers ───────────────────────────────────────────────────────
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
        mset(conn.cursor(), "moon_status",
             json.dumps({"state": state, "note": note, "t": time.time()}))
        conn.commit()
    finally:
        conn.close()


def _status_raw():
    conn = get_conn()
    try:
        raw = mget(conn.cursor(), "moon_status", "") or ""
    finally:
        conn.close()
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


# ── public status ────────────────────────────────────────────────────────────
def status():
    """{generating, has_image, url, v, enabled, daytime, state, note}.

    `enabled` mirrors `world_moon_enabled` (the whole moon layer on/off) and `daytime`
    mirrors `world_moon_daytime` (show the moon in daylight too — a preview), so the
    client can gate without extra requests. The moon is a sky object, so it's ON by
    default; a generated texture just replaces the procedural disc when present."""
    st = _status_raw()
    generating = _lock.locked()
    if st.get("state") == "generating" and not generating \
            and time.time() - float(st.get("t") or 0) > 900:
        st = {"state": "failed", "note": "interrupted by a restart — generate again"}
        _set_status(st["state"], st["note"])
    meta = _meta_get() or {}
    v = int(meta.get("v") or 0)
    has_image = bool(meta) and (MOON_DIR / OUT_FILE).exists()
    return {
        "generating": generating,
        "has_image": has_image,
        "enabled": ws.b("world_moon_enabled"),
        "daytime": ws.b("world_moon_daytime"),
        "url": f"world_assets/sky/moon/{OUT_FILE}?v={v}" if has_image else None,
        "v": v,
        "prompt": meta.get("prompt") or "",
        "state": st.get("state") or ("done" if has_image else "none"),
        "note": st.get("note") or "",
    }


# ── prompt ───────────────────────────────────────────────────────────────────
def _prompt(theme):
    theme = (theme or "").strip()
    base = (
        "top-down full moon surface texture, grey lunar regolith with round craters "
        "and maria, soft rim shading, pixel-art game moon, no background, no stars, "
        "no people, no text, no grid lines, fills the whole frame"
    )
    p = f"{theme} {base}".strip() if theme else base
    # generate.sh embeds the prompt via bash ${PROMPT@Q}; strip chars that break its heredoc.
    return re.sub(r"['\"\\`]", "", p)


def _image_ok(path):
    """Loose QA: reject a near-black / empty render (reuse the tilegate check)."""
    try:
        from PIL import Image
        from world_tilegate import _tile_ok
        im = Image.open(path).convert("RGB")
        return _tile_ok(im.resize((128, 128)))
    except Exception:
        return False


# ── generation ───────────────────────────────────────────────────────────────
def _generate(theme):
    """Worker body. Renders ONE lunar-surface texture, QA-gates it, installs it.
    Never raises out of the thread — logs + sets a failed status instead."""
    try:
        theme = (theme or ws.s("world_theme") or "").strip()
        MOON_DIR.mkdir(parents=True, exist_ok=True)
        _set_status("generating", "rendering the moon texture")
        model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
        lora = ws.s("world_prop_lora")
        prompt = _prompt(theme)
        raw = MOON_DIR / "_raw_moon.png"
        ok = False
        orch.image_acquire()
        try:
            try:
                cmd = [str(GENERATE_SCRIPT), prompt, str(raw), GEN_SIZE, GEN_SIZE,
                       GEN_STEPS, str(random.randint(1, 2**31 - 1)), model, lora]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except subprocess.TimeoutExpired:
                log.error("moon render timed out after 600s (model=%s %sx%s)",
                          model, GEN_SIZE, GEN_SIZE)
                _set_status("failed",
                            f"render timed out after 600s (model={model}, {GEN_SIZE}x{GEN_SIZE})")
                return
            ok = res.returncode == 0 and raw.exists()
            if not ok:
                raw_err = (res.stderr or res.stdout or "").strip()
                last = raw_err.splitlines()[-1] if raw_err else "(no output from generator)"
                log.error("moon render failed (rc=%s model=%s): %s",
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
        # normalise to a square texture and install as the moon skin
        try:
            from PIL import Image
            Image.open(raw).convert("RGB").resize((512, 512)).save(MOON_DIR / OUT_FILE)
        finally:
            try:
                raw.unlink()
            except Exception:
                pass
        v = int((_meta_get() or {}).get("v") or 0) + 1
        _meta_set({"path": f"world_assets/sky/moon/{OUT_FILE}", "v": v, "prompt": prompt})
        _set_status("done", f"moon texture v{v} installed")
    except Exception as e:
        log.exception("world moon generation crashed: %s", e)
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
    """Back to the procedural cratered disc: drop the meta blob + the file."""
    _meta_clear()
    try:
        (MOON_DIR / OUT_FILE).unlink()
    except Exception:
        pass
    _set_status("removed")
    return True
