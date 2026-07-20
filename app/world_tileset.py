"""THE COMPANY — PROGRESSIVE agent-filled terrain tilesets.

The classic procedural textures are the PERMANENT defaults. Instead of one
all-at-once "whole atlas from a theme" swap (which produced style-clashing
results), individual terrain tiles are generated ONE at a time — by you from
the 🧱 panel, or slowly by a world agent when the `world_tileset_auto` toggle
is on. Every candidate must pass BOTH:
  • the `_tile_ok()` QA gate (no near-black / flat-slab renders), and
  • a deterministic STYLE gate (`_style_check`): per-kind palette anchors
    (grass must read green, water blue, …) plus a brightness-harmony band
    against the tiles already live — so a gray concrete slab can never join
    a lush green set.
Only a passing tile lands in the shared atlas (`gen_atlas.png`) + manifest —
the exact hook `world-assets.js` (WA.tile) already reads, with its own client
re-validation and procedural fallback, so a partial fill can never break the
map. 👎 Reject reverts a tile to procedural, logs the rejection (fed to the
god-taste model as a deny example, and into future tile prompts as avoid
context). FLOOR/WALL stay procedural by design (crafted structural interiors;
the client vets them out anyway).

Seamlessness: SDXL can't be trusted to tile, so we make it tile — the render
is half-offset (seams move to a center cross) and the seam cross is blended
from a blurred copy, then NEAREST-downscaled to 64px pixel-art.
"""
import colorsys
import json
import logging
import random
import subprocess
import threading
import time

from deps import get_conn, orch, GENERATE_SCRIPT, DEFAULT_IMAGE_MODEL
from world_defs import WORLD_ASSETS, mget, mset, log_agent, level_for
import world_settings as ws

# The deterministic tile QA + style gate lives in a sibling module; re-export
# its full public surface so world_tileset keeps its historical API. (_live_tiles
# stays here — the gate lazy-imports it — so there is no import cycle.)
from world_tilegate import (  # noqa: E402
    STYLE_ANCHORS, HARMONY_LUMA_BAND, STRIPE_SD_MAX,
    _seamless, _seamless_im, _tile_ok, _tile_stats, _stripe_sd, _style_check,
)

TILESET_DIR = WORLD_ASSETS / "tilesets"
ATLAS_ID = "gen"
ATLAS_FILE = "gen_atlas.png"     # ONE persistent atlas; tiles land in it one at a time
CELL = 64
STEPS = 20   # the default lightning model renders near-BLACK at the old 8 steps
             # (verified live — the source of the original dark clashing atlas)

# terrain key (world-map _TKEY) → what the texture should look like
KINDS = [
    ("grass", "lush green grass lawn, tiny blades and clover specks"),
    ("path",  "grey cobblestone pavement, small rounded stones with dark grout"),
    ("floor", "warm wooden plank flooring, straight boards with visible grain"),
    ("wall",  "weathered brick wall, staggered bricks with light mortar lines"),
    ("plaza", "light stone plaza paving, large smooth square slabs"),
    ("water", "deep blue water surface with subtle ripple highlights"),
]
KIND_DESC = dict(KINDS)
# structural tiles keep the crafted procedural interior art — the client's
# _vetTiles() unconditionally unmaps gen floor/wall, so generating them would
# only waste GPU time and confuse the panel.
LOCKED = {"floor", "wall"}


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
        # restart-reconcile: a server restart mid-generation leaves the persisted
        # status at "generating" forever (the worker thread is gone). If nobody
        # holds the lock and the record is stale, surface it as failed.
        if st.get("state") == "generating" and not _lock.locked() \
                and time.time() - float(st.get("t") or 0) > 600:
            st = {"state": "failed", "note": "interrupted by a restart — generate again",
                  "t": time.time()}
            _set_status(st["state"], st["note"])
        st["installed"] = _installed()
        st.update(tiles_state())
        return st
    finally:
        if own:
            conn.close()


def _manifest():
    try:
        return json.loads((TILESET_DIR / "manifest.json").read_text())
    except Exception:
        return {}


def _gen_keys(m=None):
    """Keys currently mapped into OUR atlas."""
    tiles = (m if m is not None else _manifest()).get("tiles") or {}
    return {k for k, _ in KINDS
            if isinstance(tiles.get(k), dict) and tiles[k].get("atlas") == ATLAS_ID}


def _installed():
    return bool(_gen_keys())


# ── COMPLETENESS: a PARTIAL tileset must never read as a healthy install ─────
# The world lost every road for DAYS because a transient generation failure left
# the installed manifest with `path: null`, and an unmapped terrain key rendered
# as NOTHING. So "installed" is not enough state — completeness is first-class.
# REQUIRED = every KINDS key that is NOT structural; `LOCKED` is the single
# source of truth for "deliberately procedural" (floor/wall keep their crafted
# interior art and the API refuses to generate them), so there is never a second
# hand-maintained list to drift out of sync.
def required_keys():
    """Terrain keys a COMPLETE tileset must map (structural LOCKED keys excluded)."""
    return [k for k, _d in KINDS if k not in LOCKED]


def _atlas_sizes(m):
    """{atlas id: (w, h)} for every declared atlas whose file is actually on disk."""
    out = {}
    for a in (m.get("atlases") or []):
        aid, src = a.get("id"), a.get("src")
        if not aid or not src:
            continue
        p = TILESET_DIR / src
        if not p.exists():
            continue
        try:
            from PIL import Image
            with Image.open(p) as im:
                out[aid] = im.size
        except Exception:
            pass
    return out


def _cell_ok(sizes, t):
    """Is this manifest tile entry a REAL, loadable atlas cell? Mirrors the client's
    own re-validation: the atlas must be declared + on disk, and the crop rect must
    lie inside it. `None`, a missing key, or a cell pointing outside the atlas all
    mean 'no art' — exactly the states that used to render nothing."""
    if not isinstance(t, dict):
        return False
    wh = sizes.get(t.get("atlas"))
    if not wh:
        return False
    return (t.get("x", 0) >= 0 and t.get("y", 0) >= 0
            and t.get("x", 0) + (t.get("w") or CELL) <= wh[0]
            and t.get("y", 0) + (t.get("h") or CELL) <= wh[1])


def _terrain_image_live():
    """Is the whole-world terrain image (Layer 2) enabled AND rendered? That's the
    client's FIRST per-tile fallback when an atlas cell is missing."""
    try:
        import world_terrain
        st = world_terrain.status()
        return bool(st.get("enabled") and st.get("has_image"))
    except Exception:
        return False


def missing_keys(m=None):
    """REQUIRED terrain keys with no usable atlas cell — the degraded set."""
    m = m if m is not None else _manifest()
    sizes = _atlas_sizes(m)
    tiles = m.get("tiles") or {}
    return [k for k in required_keys() if not _cell_ok(sizes, tiles.get(k))]


def resolve_tile(key, m=None, terrain_image=None):
    """What the renderer ACTUALLY paints for `key`, in the same order the client's
    world-map `_tile()` fallback uses:
        'atlas' → 'terrain_image' → 'procedural'
    It never resolves to nothing. Structural keys are always 'procedural' by design."""
    m = m if m is not None else _manifest()
    if key in LOCKED:
        return "procedural"
    if _cell_ok(_atlas_sizes(m), (m.get("tiles") or {}).get(key)):
        return "atlas"
    if terrain_image is None:
        terrain_image = _terrain_image_live()
    return "terrain_image" if terrain_image else "procedural"


def tiles_state():
    """Per-tile view for the 🧱 panel: procedural vs generated + atlas crop info,
    plus the COMPLETENESS verdict (complete / missing / degraded) and what each key
    actually resolves to."""
    m = _manifest()
    gen = _gen_keys(m)
    sizes = _atlas_sizes(m)
    tiles = m.get("tiles") or {}
    ti = _terrain_image_live()
    missing = [k for k in required_keys() if not _cell_ok(sizes, tiles.get(k))]
    return {
        "tiles": [{"key": k, "desc": d, "generated": k in gen, "locked": k in LOCKED,
                   "missing": k in missing,
                   "source": resolve_tile(k, m, ti), "x": i * CELL}
                  for i, (k, d) in enumerate(KINDS)],
        "atlas": f"world_assets/tilesets/{ATLAS_FILE}",
        "v": m.get("v") or 0, "cell": CELL,
        "required": required_keys(),
        "missing": missing,
        "complete": not missing,
        # installed-but-incomplete: report DEGRADED, never a healthy install
        "degraded": bool(gen) and bool(missing),
        "fallback": "terrain_image" if ti else "procedural",
        "rejects": _recent_rejects(limit=6),
    }


def _set_status(state, note="", extra=None):
    rec = {"state": state, "note": note, "t": time.time()}
    if extra:
        rec.update(extra)
    conn = get_conn()
    try:
        mset(conn.cursor(), "tileset_status", json.dumps(rec))
        conn.commit()
    finally:
        conn.close()


def _live_tiles(exclude=None):
    """PIL images of the tiles currently live in our atlas (for harmony checks)."""
    from PIL import Image
    out = []
    path = TILESET_DIR / ATLAS_FILE
    if not path.exists():
        return out
    try:
        atlas = Image.open(path).convert("RGB")
    except Exception:
        return out
    idx = {k: i for i, (k, _) in enumerate(KINDS)}
    for k in _gen_keys():
        if k == exclude or k not in idx:
            continue
        x = idx[k] * CELL
        if x + CELL <= atlas.width:
            out.append(atlas.crop((x, 0, x + CELL, CELL)))
    return out


# ── rejection memory (mirrors the NSFW reject → avoid loop) ──────────────────
def _recent_rejects(key=None, limit=12):
    conn = get_conn()
    try:
        raw = mget(conn.cursor(), "tileset_rejects", "[]") or "[]"
        try:
            lst = json.loads(raw)
        except Exception:
            lst = []
        if key:
            lst = [r for r in lst if r.get("key") == key]
        return lst[-limit:]
    finally:
        conn.close()


def _avoid_text(key):
    """Recent user rejections for this tile kind → CORRECTIVE steering for the
    prompt. Diffusion models latch onto whatever a prompt describes (verified
    live: 'avoid … brightness 44' produced near-black renders), so instead of
    describing the rejected look we append positive phrases that push the next
    attempt the other way."""
    rej = _recent_rejects(key, limit=4)
    if not rej:
        return ""
    fixes = []
    for r in rej:
        st = r.get("stats") or {}
        if not st:
            continue
        if st.get("stripe", 0) > STRIPE_SD_MAX:
            fixes.append("perfectly uniform micro-texture with no bands, rows or gradients")
        if st.get("sat", 1) < 0.15:
            fixes.append("rich vivid natural color")
        if st.get("luma", 128) < 70:
            fixes.append("bright, evenly lit")
        elif st.get("luma", 128) > 185:
            fixes.append("deeper, richer tones")
    seen, out = set(), []
    for f in fixes:
        if f not in seen:
            seen.add(f)
            out.append(f)
    if not out:
        out = ["a noticeably different pattern and palette than previous attempts"]
    return ", " + ", ".join(out)


def reject_tile(key):
    """👎 on a generated tile: revert it to procedural, log the rejection (avoid
    context for future prompts) and feed a deny example into the god-taste model
    — the same loop the NSFW reject uses."""
    if key not in KIND_DESC:
        return {"ok": False, "reason": "unknown tile key"}
    # capture what the rejected tile looked like BEFORE unmapping it
    stats = None
    try:
        idx = {k: i for i, (k, _) in enumerate(KINDS)}[key]
        from PIL import Image
        atlas = Image.open(TILESET_DIR / ATLAS_FILE).convert("RGB")
        cell = atlas.crop((idx * CELL, 0, idx * CELL + CELL, CELL))
        stats = _tile_stats(cell)
        stats["stripe"] = _stripe_sd(cell)
    except Exception:
        pass
    path = TILESET_DIR / "manifest.json"
    reverted = False
    try:
        m = json.loads(path.read_text())
        t = (m.get("tiles") or {}).get(key)
        if isinstance(t, dict) and t.get("atlas") == ATLAS_ID:
            m["tiles"][key] = None
            m["v"] = int(time.time())          # cache-buster: the map re-fetches
            path.write_text(json.dumps(m, indent=2))
            reverted = True
    except Exception:
        pass
    theme = (ws.s("world_theme") or "").strip()
    conn = get_conn()
    try:
        c = conn.cursor()
        try:
            lst = json.loads(mget(c, "tileset_rejects", "[]") or "[]")
        except Exception:
            lst = []
        lst.append({"key": key, "theme": theme, "t": time.time(),
                    "stats": {k: round(v, 3) for k, v in (stats or {}).items()} or None})
        mset(c, "tileset_rejects", json.dumps(lst[-24:]))
        try:
            import world_taste
            world_taste.add_example(
                conn, f"tile_reject:{key}:{int(time.time())}", "world_tile",
                f"terrain tile '{key}' ({KIND_DESC[key]}), {theme or 'default'} style"
                + (f", brightness {stats['luma']:.0f}, saturation {stats['sat']:.2f}"
                   if stats else ""),
                -1.0, "god_verdict")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()
    _set_status("rejected", f"{key} reverted to procedural")
    return {"ok": True, "reverted": reverted}


# ── manifest / atlas plumbing ────────────────────────────────────────────────
def _write_manifest(made):
    """Point `made` keys (plus any already-live gen keys) at our atlas cells,
    preserving user-mapped sprite packs. Always bumps the `v` cache-buster."""
    path = TILESET_DIR / "manifest.json"
    m = _manifest()
    keep = _gen_keys(m) | set(made)
    atl = [a for a in (m.get("atlases") or []) if a.get("id") != ATLAS_ID]
    atl.append({"id": ATLAS_ID, "src": ATLAS_FILE})
    m["atlases"] = atl
    tiles = m.get("tiles") or {}
    for i, (key, _d) in enumerate(KINDS):
        if key in keep:
            tiles[key] = {"atlas": ATLAS_ID, "x": i * CELL, "y": 0, "w": CELL, "h": CELL}
        else:
            # a key we never rendered must not point into our atlas — its cell
            # is empty background and would draw BLACK.
            old = tiles.get(key)
            tiles[key] = None if isinstance(old, dict) and old.get("atlas") == ATLAS_ID else old
    m["tiles"] = tiles
    m["v"] = int(time.time())          # cache-buster: the atlas filename never changes
    TILESET_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, indent=2))
    # drop superseded legacy whole-theme atlases (gen_<theme>.png)
    for f in TILESET_DIR.glob("gen_*.png"):
        if f.name != ATLAS_FILE:
            try:
                f.unlink()
            except Exception:
                pass


def _open_atlas():
    """The persistent atlas image (migrating a legacy gen_<theme>.png if the
    manifest still points at one, so already-approved tiles survive)."""
    from PIL import Image
    size = (CELL * len(KINDS), CELL)
    path = TILESET_DIR / ATLAS_FILE
    src = None
    if path.exists():
        src = path
    else:
        m = _manifest()
        legacy = next((a.get("src") for a in (m.get("atlases") or [])
                       if a.get("id") == ATLAS_ID and a.get("src")), None)
        if legacy and (TILESET_DIR / legacy).exists():
            src = TILESET_DIR / legacy
    if src:
        try:
            atlas = Image.open(src).convert("RGB")
            if atlas.size != size:
                base = Image.new("RGB", size, (20, 24, 34))
                base.paste(atlas, (0, 0))
                atlas = base
            return atlas
        except Exception:
            pass
    return Image.new("RGB", size, (20, 24, 34))


def _install_tile(key, tile):
    """Land ONE passed tile in the atlas + manifest (with `v` bump)."""
    TILESET_DIR.mkdir(parents=True, exist_ok=True)
    atlas = _open_atlas()
    idx = {k: i for i, (k, _) in enumerate(KINDS)}[key]
    atlas.paste(tile, (idx * CELL, 0))
    atlas.save(TILESET_DIR / ATLAS_FILE)
    _write_manifest({key})


def remove():
    """Back to procedural terrain: drop our atlas + null our tile entries."""
    path = TILESET_DIR / "manifest.json"
    try:
        m = json.loads(path.read_text())
        m["atlases"] = [a for a in (m.get("atlases") or []) if a.get("id") != ATLAS_ID]
        for k, _d in KINDS:
            if isinstance((m.get("tiles") or {}).get(k), dict) and m["tiles"][k].get("atlas") == ATLAS_ID:
                m["tiles"][k] = None
        m["v"] = int(time.time())
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


# ── generation ───────────────────────────────────────────────────────────────
def _tile_prompt(key, theme):
    from prompts import get_prompt
    return get_prompt("world_tileset_tile").format(
        desc=KIND_DESC[key], theme=theme, avoid=_avoid_text(key))


def _best_crop_tile(raw_path, key):
    """The pixel-art model often paints a SPRITE SHEET (objects on white) instead
    of a filling texture. Scan a grid of candidate crops, seamless-ize each, and
    keep the most texture-like one (passes QA + anchors, lowest stripe profile).
    Falls back to the plain center-crop; the normal gates still have final say."""
    from PIL import Image
    im = Image.open(raw_path).convert("RGB")
    s = min(im.size)
    boxes = set()
    for frac in (1.0, 0.55, 0.38):
        cs = int(s * frac)
        for cx in (0.25, 0.5, 0.75):
            for cy in (0.25, 0.5, 0.75):
                x0 = int(min(max(cx * im.width - cs / 2, 0), im.width - cs))
                y0 = int(min(max(cy * im.height - cs / 2, 0), im.height - cs))
                boxes.add((x0, y0, x0 + cs, y0 + cs))
    best, best_sd = None, None
    for b in sorted(boxes):
        tile = _seamless_im(im.crop(b))
        if not _tile_ok(tile):
            continue
        if not _style_check(key, tile, live=[])[0]:      # anchors + stripe only
            continue
        sd = _stripe_sd(tile)
        if best_sd is None or sd < best_sd:
            best, best_sd = tile, sd
    return best if best is not None else _seamless_im(im)


def _render_tile(key, theme, model, lora):
    """One GPU render → seamless 64px tile (or None). Caller holds the GPU."""
    prompt = _tile_prompt(key, theme)
    raw = TILESET_DIR / f"_raw_{key}.png"
    try:
        res = subprocess.run(
            [str(GENERATE_SCRIPT), prompt, str(raw), "512", "512", str(STEPS),
             str(random.randint(1, 2**31 - 1)), model, lora],
            capture_output=True, text=True, timeout=300)
        if res.returncode == 0 and raw.exists():
            return _best_crop_tile(raw, key)
    except Exception:
        pass
    finally:
        try:
            raw.unlink()
        except Exception:
            pass
    return None


RENDER_ATTEMPTS = 2      # the lightning model flakes to black renders — one cheap in-hold retry


def _render_tile_checked(key, theme, model, lora):
    """Render with an in-hold retry: (tile, ok, why) — the gates have final say."""
    tile, ok, why = None, False, "render failed"
    for _ in range(RENDER_ATTEMPTS):
        tile = _render_tile(key, theme, model, lora)
        ok, why = _check_tile(key, tile)
        if ok:
            break
    return tile, ok, why


def _check_tile(key, tile):
    """(ok, reason) through BOTH gates."""
    if tile is None:
        return False, "render failed"
    if not _tile_ok(tile):
        return False, "failed QA (flat or near-black render)"
    return _style_check(key, tile)


def generate_tile(key, theme=None):
    """Generate ONE terrain tile through the QA + style gates. Blocking (call
    via start_generate_tile for the API). Returns {ok, key, reason?}."""
    if key not in KIND_DESC:
        return {"ok": False, "key": key, "reason": "unknown tile key"}
    if key in LOCKED:
        return {"ok": False, "key": key,
                "reason": "structural tile — the renderer keeps its crafted procedural art"}
    if not _lock.acquire(blocking=False):
        return {"ok": False, "key": key, "reason": "a generation is already running"}
    try:
        theme = (theme or ws.s("world_theme") or "cozy fantasy").strip()
        _set_status("generating", f"tile: {key}")
        TILESET_DIR.mkdir(parents=True, exist_ok=True)
        model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
        lora = ws.s("world_prop_lora")
        orch.image_acquire()
        try:
            tile, ok, why = _render_tile_checked(key, theme, model, lora)
        finally:
            orch.image_release()
        if not ok:
            # a failure must never quietly leave a hole: record what is still unmapped
            _set_status("failed", f"{key}: {why}", {"missing_at_failure": missing_keys()})
            return {"ok": False, "key": key, "reason": why}
        _install_tile(key, tile)
        _set_status("done", f"tile '{key}' installed")
        return {"ok": True, "key": key}
    finally:
        _lock.release()


def start_generate_tile(key, theme=None):
    if _lock.locked():
        return False
    threading.Thread(target=generate_tile, args=(key, theme), daemon=True).start()
    return True


def generate(theme=None):
    """Fill ALL pending tiles — the batch path runs the SAME per-tile QA+style
    gates sequentially on one GPU hold. Runs in the caller's thread — start via
    start_generate()."""
    if not _lock.acquire(blocking=False):
        return False
    try:
        theme = (theme or ws.s("world_theme") or "cozy fantasy").strip()
        todo = [k for k, _ in KINDS if k not in LOCKED and k not in _gen_keys()]
        if not todo:
            _set_status("done", "nothing pending — every paintable tile is already generated")
            return True
        _set_status("generating", f"0/{len(todo)}")
        TILESET_DIR.mkdir(parents=True, exist_ok=True)
        model = ws.s("world_prop_model") or DEFAULT_IMAGE_MODEL
        lora = ws.s("world_prop_lora")
        made = set()
        orch.image_acquire()
        try:
            for i, key in enumerate(todo):
                try:
                    tile, ok, _why = _render_tile_checked(key, theme, model, lora)
                    if ok:
                        _install_tile(key, tile)
                        made.add(key)
                except Exception:
                    pass
                _set_status("generating", f"{i + 1}/{len(todo)}")
        finally:
            orch.image_release()
        if not made:
            # THE roads-vanished failure mode: a transient GPU outage leaves the set
            # half-filled forever. Record the still-missing keys with the failure so
            # the degraded state is visible instead of being forgotten.
            miss = missing_keys()
            _set_status("failed",
                        "no tiles passed — is the GPU box reachable?"
                        + (f" Still unmapped: {', '.join(miss)}." if miss else ""),
                        {"missing_at_failure": miss})
            return False
        _set_status("done", f"{len(made)}/{len(todo)} tiles ({', '.join(sorted(made))})")
        return True
    finally:
        _lock.release()


def start_generate(theme=None):
    if _lock.locked():
        return False
    threading.Thread(target=generate, args=(theme,), daemon=True).start()
    return True


# ── slow background agent loop (world_ticker hook; toggle-gated) ─────────────
_AUTO_DONE_LINES = [
    "🧱 {name} painted the town's new '{key}' ground texture — it passed inspection and is live on the map.",
    "🎨 {name} finished a hand-tiled '{key}' texture for the world. The set keeps growing.",
]
_AUTO_SCRAP_LINES = [
    "🗑️ {name} scrapped a draft '{key}' texture — {why}.",
    "😤 {name} binned a '{key}' tile attempt that didn't match the town's look ({why}).",
]


def _pick_painter(conn):
    rows = conn.execute(
        "SELECT * FROM world_agents WHERE kind='worker' AND job_class='image'").fetchall()
    rows = rows or conn.execute("SELECT * FROM world_agents WHERE kind='worker'").fetchall()
    return dict(random.choice(rows)) if rows else None


def _auto_paint(key, agent):
    """Worker thread: one agent paints one tile; credit or quietly scrap."""
    res = generate_tile(key)
    if not agent:
        return
    conn = get_conn()
    try:
        c = conn.cursor()
        if res.get("ok"):
            row = c.execute("SELECT xp FROM world_agents WHERE key=?", (agent["key"],)).fetchone()
            xp = (row["xp"] if row else 0) or 0
            xp += 12
            c.execute("UPDATE world_agents SET xp=?, level=? WHERE key=?",
                      (xp, level_for(xp), agent["key"]))
            c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
                      (agent["key"], "job_done",
                       random.choice(_AUTO_DONE_LINES).format(name=agent["name"], key=key)))
            log_agent(agent["key"], agent["name"],
                      f"painted the world's '{key}' terrain tile (passed QA + style check, +12xp).")
        else:
            # failures are quietly discarded — just a journal note, no town noise
            log_agent(agent["key"], agent["name"],
                      random.choice(_AUTO_SCRAP_LINES).format(
                          name=agent["name"], key=key, why=res.get("reason") or "not good enough"))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def degraded_watch(c, every=6 * 3600):
    """Slow watchdog (rides the existing world_ticker tileset hook — no new timer).

    An INSTALLED but INCOMPLETE tileset silently erased the world's roads for days,
    because a transient generation failure left a key unmapped and nobody re-checked.
    So re-check on a slow cadence and LOG the degraded set. This never generates
    anything: filling is the owner's 🧱 button, or the pre-existing
    `world_tileset_auto` toggle (default OFF) — no automatic GPU work without it."""
    now = time.time()
    last = float(mget(c, "tileset_degraded_last", 0) or 0)
    if last and now - last < every:
        return None
    mset(c, "tileset_degraded_last", now)
    miss = missing_keys() if _installed() else []
    mset(c, "tileset_missing", json.dumps(miss))
    if miss:
        logging.warning(
            "[tileset] DEGRADED — installed but %d terrain tile(s) unmapped: %s. "
            "The map falls back per-tile (terrain image → procedural), but fill them "
            "from Company Settings → 🧱 Terrain tiles.", len(miss), ", ".join(miss))
    return miss or None


def auto_tick(conn, _run=None):
    """world_ticker hook: when `world_tileset_auto` is ON, every
    `world_tileset_auto_min` minutes one world agent paints ONE pending tile
    (QA + style gated; failures silently discarded). Returns the picked key or
    None. Self-cadenced; never overlaps a running generation.

    The degraded re-check runs FIRST and regardless of the toggle — it only looks
    and logs, so an incomplete set can't stay invisible while auto-paint is off."""
    c = conn.cursor()
    try:
        degraded_watch(c)
    except Exception:
        pass
    if not ws.b("world_tileset_auto", conn):
        return None
    every = max(15, ws.i("world_tileset_auto_min", conn) or 180) * 60
    now = time.time()
    last = float(mget(c, "tileset_auto_last", 0) or 0)
    if not last:
        mset(c, "tileset_auto_last", now)   # don't fire on the very first observation
        return None
    if now - last < every or _lock.locked():
        return None
    pending = [k for k, _ in KINDS if k not in LOCKED and k not in _gen_keys()]
    if not pending:
        return None
    mset(c, "tileset_auto_last", now)
    key = random.choice(pending)
    agent = _pick_painter(conn)
    runner = _run or (lambda k, a: threading.Thread(
        target=_auto_paint, args=(k, a), daemon=True).start())
    runner(key, agent)
    return key
