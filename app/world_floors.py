"""THE COMPANY — Layer 2b: ONE shared generated interior-floor texture.

Near-clone of world_terrain.py, but for the INSIDE of buildings: instead of the
flat per-kind FLOOR_TINT painted under each building interior (world-map.js
`_building`), this module generates ONE seamless tileable top-down interior-floor
image (warm planks/tiles) that the client blits under EVERY building interior. The
existing per-kind tint is then washed over it at low alpha so buildings still read
distinct.

Like the whole-world terrain image this is a pure visual skin and OFF by default
(`world_floor_image_enabled` = "0"): the procedural/tint floor shows until you both
enable the setting AND generate a floor. Mirrors world_terrain.py's lock / status /
meta / orch-hold structure. Import-safe: no heavy work runs at import time.
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

log = logging.getLogger("world_floors")

FLOOR_DIR = WORLD_ASSETS / "terrain" / "floors"
OUT_FILE = "floor.png"
META_KEY = "floor_image"            # world_meta blob: {"path", "v", "prompt"}

# A single square tileable texture — smaller than the terrain skin because it is
# repeated under interiors, not stretched over the whole map. 1024² renders fast
# and shares VRAM politely with a resident LLM.
GEN_SIZE = "1024"
GEN_STEPS = "24"

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
        mset(conn.cursor(), "floor_status",
             json.dumps({"state": state, "note": note, "t": time.time()}))
        conn.commit()
    finally:
        conn.close()


def _status_raw():
    conn = get_conn()
    try:
        raw = mget(conn.cursor(), "floor_status", "") or ""
    finally:
        conn.close()
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


# ── public status ────────────────────────────────────────────────────────────
def status():
    """{generating, has_image, url, v, enabled, state, note}.

    `enabled` reflects the `world_floor_image_enabled` setting so the client can
    gate the blit without a second request; the feature is OFF by default so the
    procedural per-kind tint floor always wins unless you both enable it AND
    generate a floor image."""
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
    has_image = bool(meta) and (FLOOR_DIR / OUT_FILE).exists()
    return {
        "generating": generating,
        "has_image": has_image,
        "enabled": ws.b("world_floor_image_enabled"),
        "url": f"world_assets/terrain/floors/{OUT_FILE}?v={v}" if has_image else None,
        "v": v,
        "prompt": meta.get("prompt") or "",
        "state": st.get("state") or ("done" if has_image else "none"),
        "note": st.get("note") or "",
    }


# ── prompt ───────────────────────────────────────────────────────────────────
def _prompt(theme):
    theme = (theme or "").strip()
    base = (
        "seamless tileable top-down interior floor texture, "
        "warm wooden planks and tiles, cozy pixel-art game, "
        "soft even lighting, no walls, no furniture, no characters, "
        "no people, no text, no grid lines, flat top-down floor texture only"
    )
    p = f"{theme} {base}".strip() if theme else base
    # generate.sh embeds the prompt into a Python heredoc via bash ${PROMPT@Q},
    # which mangles apostrophes/quotes/backslashes into invalid Python. Strip the
    # chars that trip that so any theme/prompt is safe.
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
    """Worker body. Renders ONE tileable interior-floor texture, QA-gates it,
    installs it. Never raises out of the thread — logs + sets a failed status
    instead."""
    try:
        theme = (theme or ws.s("world_theme") or "cozy fantasy").strip()
        FLOOR_DIR.mkdir(parents=True, exist_ok=True)
        _set_status("generating", "rendering shared interior-floor texture")
        model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
        lora = ws.s("world_prop_lora")
        prompt = _prompt(theme)
        raw = FLOOR_DIR / "_raw_floor.png"
        ok = False
        orch.image_acquire()
        try:
            try:
                cmd = [str(GENERATE_SCRIPT), prompt, str(raw), GEN_SIZE, GEN_SIZE,
                       GEN_STEPS, str(random.randint(1, 2**31 - 1)), model, lora]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except subprocess.TimeoutExpired:
                log.error("floor render timed out after 600s (model=%s %sx%s)",
                          model, GEN_SIZE, GEN_SIZE)
                _set_status("failed",
                            f"render timed out after 600s (model={model}, {GEN_SIZE}x{GEN_SIZE})")
                return
            ok = res.returncode == 0 and raw.exists()
            if not ok:
                # Surface the REAL failure — the generator's own stderr/stdout —
                # instead of a generic "is the GPU box reachable?" guess.
                raw_err = (res.stderr or res.stdout or "").strip()
                last = raw_err.splitlines()[-1] if raw_err else "(no output from generator)"
                log.error("floor render failed (rc=%s model=%s): %s",
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
        # normalise to a square texture and install as the shared floor
        try:
            from PIL import Image
            Image.open(raw).convert("RGB").resize((512, 512)).save(FLOOR_DIR / OUT_FILE)
        finally:
            try:
                raw.unlink()
            except Exception:
                pass
        v = int((_meta_get() or {}).get("v") or 0) + 1
        _meta_set({"path": f"world_assets/terrain/floors/{OUT_FILE}", "v": v,
                   "prompt": prompt})
        _set_status("done", f"interior-floor texture v{v} installed")
    except Exception as e:
        log.exception("world floor generation crashed: %s", e)
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
    """Back to the procedural per-kind tint floor: drop the meta blob + the file."""
    _meta_clear()
    try:
        (FLOOR_DIR / OUT_FILE).unlink()
    except Exception:
        pass
    _set_status("removed")
    return True
