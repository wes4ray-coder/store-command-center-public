"""The Company — world-building surface: terrain tileset generation, raids, the
hand-edited map layout + foot-traffic wear, and the generated soundscape."""
import time, json, logging
from fastapi import HTTPException, Body, BackgroundTasks

from deps import get_conn
import world_defs as wd
import world_gov, world_build, world_systems, world_settings as ws
import world_skills, world_orchestra, world_raid, world_learn, world_security, world_tech, world_construct, world_work, world_mood, world_research, world_schedule, world_items
import world_balance as wb
from ._base import router


@router.get("/api/world/tileset")
def world_tileset_status():
    """Generated-terrain-tileset status: state/progress, whether one is installed, and
    its COMPLETENESS — `complete`, `missing` (required terrain keys with no usable atlas
    cell; structural floor/wall are excluded by design) and `degraded` (installed but
    incomplete). A half-filled set once erased the world's roads silently, so an
    incomplete install must never report as a healthy one. Each tile also carries the
    `source` the renderer will actually paint: atlas → terrain_image → procedural."""
    import world_tileset
    return world_tileset.status()


@router.post("/api/world/tileset")
def world_tileset_generate(body: dict = Body(default={})):
    """Fill ALL pending terrain tiles from the world theme (or a custom one) —
    runs the same per-tile QA + style gates sequentially. Poll GET for progress."""
    import world_tileset
    if not world_tileset.start_generate(body.get("theme")):
        raise HTTPException(409, "A tileset generation is already running.")
    return {"ok": True, "note": "Generating terrain tiles — watch the status."}


@router.post("/api/world/tileset/tile")
def world_tileset_generate_one(body: dict = Body(default={})):
    """Generate ONE terrain tile (progressive fill). It only goes live if it
    passes the QA gate AND the style-consistency check; poll GET for the result."""
    import world_tileset
    key = (body.get("key") or "").strip()
    if key not in world_tileset.KIND_DESC:
        raise HTTPException(400, f"key must be one of {[k for k, _ in world_tileset.KINDS]}")
    if key in world_tileset.LOCKED:
        raise HTTPException(400, f"'{key}' is structural — the renderer keeps its crafted procedural art.")
    if not world_tileset.start_generate_tile(key, body.get("theme")):
        raise HTTPException(409, "A tileset generation is already running.")
    return {"ok": True, "key": key, "note": f"Painting '{key}' — watch the status."}


@router.post("/api/world/tileset/reject")
def world_tileset_reject(body: dict = Body(default={})):
    """👎 a generated tile: revert it to procedural, log the rejection as avoid-
    context for future tile prompts, and feed a deny example to the taste model."""
    import world_tileset
    key = (body.get("key") or "").strip()
    res = world_tileset.reject_tile(key)
    if not res.get("ok"):
        raise HTTPException(400, res.get("reason") or "reject failed")
    return res


@router.delete("/api/world/tileset")
def world_tileset_remove():
    """Back to procedural terrain (removes the generated atlas + tile mappings)."""
    import world_tileset
    world_tileset.remove()
    return {"ok": True}


# ── Layer 2: one-shot whole-world terrain IMAGE (ground skin; logic stays on
# the grid; OFF by default via the world_terrain_image_enabled setting) ──────
@router.get("/api/world/terrain")
def world_terrain_status():
    """Whole-world terrain-image status: {generating, has_image, url, v, enabled}."""
    import world_terrain
    return world_terrain.status()


@router.post("/api/world/terrain")
def world_terrain_generate(body: dict = Body(default={})):
    """Render ONE large top-down terrain image for the whole map (grass/roads/
    plaza/ponds/forest/mountains — no buildings). Poll GET for progress. The
    client only swaps it in when world_terrain_image_enabled is on.

    Optional {base_image: <dataURL>, denoise?: float} runs LAYOUT-GUIDED img2img:
    the client-rendered town-layout image is fed to the generator as the init base
    so the terrain matches the real roads/water/plaza. No base_image = the classic
    generic text-only terrain (unchanged). A layout dataURL can be a few MB; FastAPI/
    uvicorn impose no body-size limit by default, so no limit change is needed."""
    import world_terrain
    base_image = body.get("base_image")
    denoise = body.get("denoise", 0.55)
    if not world_terrain.start_generate(body.get("theme"), base_png=base_image, denoise=denoise):
        raise HTTPException(409, "A terrain image is already generating.")
    mode = "layout-guided" if base_image else "generic"
    return {"ok": True, "note": f"Rendering the {mode} terrain image — watch the status."}


@router.delete("/api/world/terrain")
def world_terrain_remove():
    """Drop the generated terrain image (revert to procedural per-tile terrain)."""
    import world_terrain
    world_terrain.remove()
    return {"ok": True}


# ── Layer 2b: ONE shared generated interior-FLOOR texture (blitted under every
# building interior; per-kind tint washed over it so buildings still read
# distinct; OFF by default via the world_floor_image_enabled setting) ─────────
@router.get("/api/world/floor")
def world_floor_status():
    """Shared interior-floor-texture status: {generating, has_image, url, v, enabled}."""
    import world_floors
    return world_floors.status()


@router.post("/api/world/floor")
def world_floor_generate(body: dict = Body(default={})):
    """Render ONE seamless tileable top-down interior-floor texture (warm planks/
    tiles — no walls/furniture/characters). Poll GET for progress. The client only
    blits it under building interiors when world_floor_image_enabled is on."""
    import world_floors
    if not world_floors.start_generate(body.get("theme")):
        raise HTTPException(409, "A floor image is already generating.")
    return {"ok": True, "note": "Rendering the interior-floor texture — watch the status."}


@router.delete("/api/world/floor")
def world_floor_remove():
    """Drop the generated floor texture (revert to the procedural per-kind tint floor)."""
    import world_floors
    world_floors.remove()
    return {"ok": True}


# ── per-CIVILIZATION-ERA generated building sprites (world_era_sprites) — an
# OPTIONAL generated top-down pixel-art image per (building-type, era) that swaps
# in over the procedural era restyle. Rides the world_sprites GPU pipeline + its
# hourly budget; OFF by default (world_era_sprites_enabled). Entity id scheme:
# era_<type>_<eraName>, drawn client-side via WSP.drawStatic. ─────────────────
@router.get("/api/world/era-sprites")
def world_era_sprites_status():
    """Which (type, era) building sprites exist + counts + queued + budget-remaining,
    plus the ladder, the type list, and the running pre-seed state."""
    import world_era_sprites
    return world_era_sprites.status()


@router.post("/api/world/era-sprites/preseed")
def world_era_sprites_preseed(body: dict = Body(default={})):
    """Kick a budget-paced BACKGROUND pre-seed of era building sprites (all types,
    or a {types:[...]} subset). Generates one-at-a-time on the shared GPU, stopping
    when the hourly budget is spent — re-run to continue. Requires the feature on."""
    import world_era_sprites
    return world_era_sprites.pre_seed(body.get("types"))


@router.post("/api/world/era-sprites/one")
def world_era_sprites_one(body: dict = Body(default={})):
    """Get-or-enqueue ONE era building sprite. body: {type, era}. Returns ready/
    pending/queued or a gated reason (disabled/capped/busy). Made once, cached."""
    import world_era_sprites
    t = (body.get("type") or "").strip()
    era = (body.get("era") or "").strip()
    if not t or not era:
        raise HTTPException(400, "type and era are required")
    return world_era_sprites.request(t, era)


@router.get("/api/world/moon")
def world_moon_status():
    """Moon texture status: {generating, has_image, url, v, enabled, daytime}."""
    import world_moon
    return world_moon.status()


@router.post("/api/world/moon")
def world_moon_generate(body: dict = Body(default={})):
    """Render ONE square top-down lunar-surface texture for the drifting moon (and the
    future zoomable moon map). Poll GET for progress. Swaps into the procedural moon
    disc when present; the moon layer is gated by world_moon_enabled."""
    import world_moon
    if not world_moon.start_generate(body.get("theme")):
        raise HTTPException(409, "A moon image is already generating.")
    return {"ok": True, "note": "Rendering the moon texture — watch the status."}


@router.delete("/api/world/moon")
def world_moon_remove():
    """Drop the generated moon texture (revert to the procedural cratered disc)."""
    import world_moon
    world_moon.remove()
    return {"ok": True}


@router.get("/api/world/space")
def world_space_status():
    """JASA space-program overlay: agency, launch pad, active launch, Moon roster.
    Same object injected into /api/world/state under the 'space' key."""
    import world_space
    return world_space.snapshot()


@router.post("/api/world/space/launch")
def world_space_launch():
    """Force a launch now. 409 if a mission is already active or the feature is off."""
    import world_space
    ok, note = world_space.launch_now()
    if not ok:
        raise HTTPException(409, note)
    return {"ok": True, "note": note, "space": world_space.snapshot()}


@router.post("/api/world/raid")
def world_raid_trigger(body: dict = Body(default={})):
    """Manually raise a raid. {'drill': true} spawns practice dummies when there are
    no real threats — so you can always see the defense in action."""
    conn = get_conn()
    try:
        res = world_raid.trigger_raid(conn.cursor(), reason=body.get("reason") or "manual alert",
                                      drill=bool(body.get("drill")))
        conn.commit()
    finally:
        conn.close()
    return res


@router.post("/api/world/raid/standdown")
def world_raid_standdown():
    conn = get_conn()
    try:
        world_orchestra.set_phase(conn.cursor(), "recovery", "manual stand-down")
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.get("/api/world/layout")
def get_layout():
    """The user's hand-edited map layout (play-god mode), or null for procedural."""
    conn = get_conn()
    try:
        raw = wd.mget(conn.cursor(), "layout")
    finally:
        conn.close()
    conn = get_conn()
    try:
        wraw = wd.mget(conn.cursor(), "tile_wear")
    finally:
        conn.close()
    try:
        wear = json.loads(wraw) if wraw else {}
    except Exception:
        wear = {}
    if not raw:
        return {"layout": None, "wear": wear}
    try:
        return {"layout": json.loads(raw), "wear": wear}
    except Exception:
        return {"layout": None, "wear": wear}


@router.post("/api/world/wear")
def push_wear(body: dict = Body(...)):
    """Merge foot-traffic increments into the persistent desire-line map.
    {updates: {"c,r": steps, ...}} — counts accumulate server-side, capped."""
    updates = body.get("updates") or {}
    if not isinstance(updates, dict) or not updates:
        return {"ok": True, "tiles": 0}
    conn = get_conn()
    try:
        c = conn.cursor()
        try:
            wear = json.loads(wd.mget(c, "tile_wear") or "{}")
        except Exception:
            wear = {}
        n = 0
        for k, v in list(updates.items())[:4000]:
            try:
                wear[k] = min(600, int(wear.get(k, 0)) + max(0, int(v)))
                n += 1
            except Exception:
                continue
        wd.mset(c, "tile_wear", json.dumps(wear))
        conn.commit()
        return {"ok": True, "tiles": n}
    finally:
        conn.close()


@router.post("/api/world/layout")
def save_layout(body: dict = Body(...)):
    """Persist an edited map layout (buildings, decor, work nodes, landmarks — stored
    as an opaque blob). Send {"layout": null} to reset to the procedural map."""
    layout = body.get("layout")
    conn = get_conn()
    try:
        c = conn.cursor()
        if layout is None:
            c.execute("DELETE FROM world_meta WHERE key='layout'")
        else:
            wd.mset(c, "layout", json.dumps(layout))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "reset": layout is None}


# ── generated soundscape — The Company's own ambience + SFX (world_audio) ────
@router.get("/api/world/audio/assets")
def world_audio_assets():
    """Catalog of generated world sounds (+ the running generation job, if any)."""
    import world_audio as wau
    return wau.list_assets()


@router.post("/api/world/audio/generate")
def world_audio_generate(body: dict = Body(default={})):
    """Render missing world sounds with the store's own audio models (manual-only;
    the 🔊 mixer button). body: {keys?: [...], engine?: auto|musicgen|stable_audio,
    force?: bool}. Clips run through the normal audio pipeline + GPU scheduler."""
    import world_audio as wau
    return wau.start_generate(keys=body.get("keys"),
                              engine=body.get("engine") or "auto",
                              force=bool(body.get("force")))


@router.get("/api/world/audio/file/{key}")
def world_audio_file(key: str):
    """Serve one cached generated wav (key must be in the catalog)."""
    from fastapi.responses import FileResponse
    import world_audio as wau
    if key not in wau.CATALOG:
        raise HTTPException(404, "unknown world audio key")
    p = wau.asset_path(key)
    if not p.exists():
        raise HTTPException(404, "not generated yet")
    return FileResponse(str(p), media_type="audio/wav", filename=p.name)
