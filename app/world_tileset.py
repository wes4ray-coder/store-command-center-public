"""THE COMPANY — GENERATED terrain tilesets (the parked "pixel-art tilesets" item).

Generates one 64px seamless texture per terrain kind with the same pixel-art
pipeline the world props use (GENERATE_SCRIPT + the world_prop_model/LoRA
settings, GPU serialized via the orchestrator), packs them into a single
atlas PNG, and wires them into `static/world_assets/tilesets/manifest.json`
— the exact hook `world-assets.js` (WA.tile) already reads. Anything missing
or removed falls back to the procedural terrain automatically, so this can
never break the map.

Seamlessness: SDXL can't be trusted to tile, so we make it tile — the render
is half-offset (seams move to a center cross) and the seam cross is blended
from a blurred copy, then NEAREST-downscaled to 64px pixel-art.

Remove = delete the generated atlas + null the manifest's tile entries
(user-added sprite packs in the same manifest are preserved).
"""
import json
import random
import subprocess
import threading
import time

from deps import get_conn, orch, GENERATE_SCRIPT, DEFAULT_IMAGE_MODEL
from world_defs import WORLD_ASSETS, mget, mset
import world_settings as ws

TILESET_DIR = WORLD_ASSETS / "tilesets"
ATLAS_ID = "gen"
CELL = 64

# terrain key (world-map _TKEY) → what the texture should look like
KINDS = [
    ("grass", "lush green grass lawn, tiny blades and clover specks"),
    ("path",  "grey cobblestone pavement, small rounded stones with dark grout"),
    ("floor", "warm wooden plank flooring, straight boards with visible grain"),
    ("wall",  "weathered brick wall, staggered bricks with light mortar lines"),
    ("plaza", "light stone plaza paving, large smooth square slabs"),
    ("water", "deep blue water surface with subtle ripple highlights"),
]

_lock = threading.Lock()


def status(c=None):
    own = c is None
    conn = get_conn() if own else None
    cc = conn.cursor() if own else c
    try:
        raw = mget(cc, "tileset_status", "") or ""
        try:
            st = json.loads(raw) if raw else {}
        except Exception:
            st = {}
        st["installed"] = _installed()
        return st
    finally:
        if own:
            conn.close()


def _installed():
    try:
        m = json.loads((TILESET_DIR / "manifest.json").read_text())
        return any((m.get("tiles") or {}).get(k) for k, _ in KINDS)
    except Exception:
        return False


def _set_status(state, note=""):
    conn = get_conn()
    try:
        mset(conn.cursor(), "tileset_status",
             json.dumps({"state": state, "note": note, "t": time.time()}))
        conn.commit()
    finally:
        conn.close()


def _seamless(src_path):
    """Half-offset the image so the tile seams land on a center cross, then blend
    that cross from a blurred copy — cheap, reliable tileability."""
    from PIL import Image, ImageChops, ImageFilter, ImageDraw
    im = Image.open(src_path).convert("RGB")
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2,
                  (im.width + s) // 2, (im.height + s) // 2))
    rolled = ImageChops.offset(im, s // 2, s // 2)
    smooth = rolled.filter(ImageFilter.GaussianBlur(s // 42))
    band = max(6, s // 16)
    mask = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle([s // 2 - band, 0, s // 2 + band, s], fill=255)
    d.rectangle([0, s // 2 - band, s, s // 2 + band], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(band // 2))
    out = Image.composite(smooth, rolled, mask)
    return out.resize((CELL, CELL), Image.NEAREST)


def _write_manifest(theme, made):
    """Merge our atlas + tile entries into the existing manifest, preserving any
    user-mapped sprite packs."""
    path = TILESET_DIR / "manifest.json"
    try:
        m = json.loads(path.read_text())
    except Exception:
        m = {}
    atl = [a for a in (m.get("atlases") or []) if a.get("id") != ATLAS_ID]
    atl.append({"id": ATLAS_ID, "src": f"gen_{theme}.png"})
    m["atlases"] = atl
    tiles = m.get("tiles") or {}
    for i, (key, _d) in enumerate(KINDS):
        tiles[key] = ({"atlas": ATLAS_ID, "x": i * CELL, "y": 0, "w": CELL, "h": CELL}
                      if key in made else tiles.get(key))
    m["tiles"] = tiles
    path.write_text(json.dumps(m, indent=2))


def remove():
    """Back to procedural terrain: drop our atlas + null our tile entries."""
    path = TILESET_DIR / "manifest.json"
    try:
        m = json.loads(path.read_text())
        m["atlases"] = [a for a in (m.get("atlases") or []) if a.get("id") != ATLAS_ID]
        for k, _d in KINDS:
            if isinstance((m.get("tiles") or {}).get(k), dict) and m["tiles"][k].get("atlas") == ATLAS_ID:
                m["tiles"][k] = None
        path.write_text(json.dumps(m, indent=2))
    except Exception:
        pass
    for f in TILESET_DIR.glob("gen_*.png"):
        try:
            f.unlink()
        except Exception:
            pass
    _set_status("removed")
    return True


def generate(theme=None):
    """Render every terrain texture (serialized on the GPU), pack the atlas, wire
    the manifest. Runs in the caller's thread — start via start_generate()."""
    from PIL import Image
    if not _lock.acquire(blocking=False):
        return False
    try:
        theme = (theme or ws.s("world_theme") or "cozy fantasy").strip()
        safe_theme = "".join(ch for ch in theme if ch.isalnum() or ch in "-_ ").replace(" ", "-")[:24] or "theme"
        _set_status("generating", f"0/{len(KINDS)}")
        TILESET_DIR.mkdir(parents=True, exist_ok=True)
        model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
        lora = ws.s("world_prop_lora")
        atlas = Image.new("RGB", (CELL * len(KINDS), CELL), (20, 24, 34))
        made = set()
        orch.image_acquire()
        try:
            for i, (key, desc) in enumerate(KINDS):
                prompt = (f"seamless tileable pixel art texture, top-down orthographic game "
                          f"terrain tile of {desc}, {theme} style, uniform repeating pattern "
                          f"filling the whole frame edge to edge, flat lighting, no objects, "
                          f"no borders, no text")
                raw = TILESET_DIR / f"_raw_{key}.png"
                try:
                    res = subprocess.run(
                        [str(GENERATE_SCRIPT), prompt, str(raw), "512", "512", "8",
                         str(random.randint(1, 2**31 - 1)), model, lora],
                        capture_output=True, text=True, timeout=300)
                    if res.returncode == 0 and raw.exists():
                        atlas.paste(_seamless(raw), (i * CELL, 0))
                        made.add(key)
                    _set_status("generating", f"{i + 1}/{len(KINDS)}")
                except Exception:
                    pass
                finally:
                    try:
                        raw.unlink()
                    except Exception:
                        pass
        finally:
            orch.image_release()
        if not made:
            _set_status("failed", "no tiles rendered — is the GPU box reachable?")
            return False
        atlas.save(TILESET_DIR / f"gen_{safe_theme}.png")
        _write_manifest(safe_theme, made)
        _set_status("done", f"{len(made)}/{len(KINDS)} tiles ({', '.join(sorted(made))})")
        return True
    finally:
        _lock.release()


def start_generate(theme=None):
    if _lock.locked():
        return False
    threading.Thread(target=generate, args=(theme,), daemon=True).start()
    return True
