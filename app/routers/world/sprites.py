"""The Company — per-entity sprite-sheet registry endpoints (world_sprites).

GET  /api/world/sprites                 → every entity's ready sheets (renderer poll)
GET  /api/world/sprites/{entity_id}     → one entity's full manifest
POST /api/world/sprites/{entity_id}/{action} → get-or-enqueue "this entity doing
     this action" (need-triggered; pack-library-first; transparency+QA gated;
     budget-capped; generated ONCE then cached forever)
POST /api/world/sprites/backfill        → the explicit bulk-backfill button
GET  /api/world/packs                   → downloaded asset-pack index + attributions
"""
import json
from fastapi import Body, HTTPException

import world_sprites
from ._base import router


@router.get("/api/world/sprites")
def sprites_index():
    return {"entities": world_sprites.index(),
            "pack_actions": sorted(world_sprites.pack_actor_actions())}


@router.get("/api/world/sprites/{entity_id}")
def sprites_manifest(entity_id: str):
    m = world_sprites.manifest(entity_id)
    if m is None:
        raise HTTPException(400, "bad entity id")
    return m


@router.post("/api/world/sprites/{entity_id}/{action}")
def sprites_request(entity_id: str, action: str, body: dict = Body(default={})):
    return world_sprites.get_or_enqueue(
        entity_id, action,
        label=str(body.get("label") or "")[:120],
        kind=str(body.get("kind") or "agent")[:20])


@router.post("/api/world/sprites/{entity_id}/{action}/regenerate")
def sprites_regenerate(entity_id: str, action: str, body: dict = Body(default={})):
    """Re-roll ONE action sheet for ONE entity — the owner's answer to a bad
    animation. Same gates as any other render (toggle, hourly budget, frame QA):
    a re-roll that fails installs nothing and the pack sheet keeps rendering."""
    return world_sprites.regenerate(entity_id, action,
                                    label=str(body.get("label") or "")[:120])


@router.post("/api/world/sprites/backfill")
def sprites_backfill():
    """Bulk backfill is a BUTTON, never automatic: every own-look entity gets its
    core sheets; legacy opaque prop squares get a no-GPU knockout repair."""
    started = world_sprites.start_backfill()
    return {"ok": True, "started": started,
            "note": None if started else "a sprite generation is already running"}


@router.get("/api/world/packs")
def packs_index():
    """The downloaded asset library, first-class: machine index + attributions."""
    out = {"packs": [], "attributions": ""}
    try:
        out.update(json.loads((world_sprites.PACKS_DIR / "index.json").read_text()))
    except Exception:
        pass
    try:
        out["attributions"] = (world_sprites.PACKS_DIR / "ATTRIBUTIONS.md").read_text()
    except Exception:
        pass
    return out
