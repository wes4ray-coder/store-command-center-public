"""The Company — public snapshot surface (outbound only).

These routes control the OUTBOUND push of a rendered world picture to the public
site. They expose no inbound path to the world: there is no endpoint here that a
public visitor can reach, and nothing here accepts a command destined for the sim.

See `app/world_snapshot.py` for the security model (toggle → gate → leak sweep).
"""
from fastapi import Body, HTTPException

from ._base import router
import world_snapshot as wsnap


@router.get("/api/world/public/status")
def world_public_status():
    """Toggle state, interval, gate reason and the last push result."""
    return wsnap.status()


@router.post("/api/world/public/toggle")
def world_public_toggle(on: bool = Body(..., embed=True)):
    """Turn the public snapshot push on or off. Ships OFF."""
    wsnap._set_setting(wsnap.TOGGLE_KEY, "1" if on else "")
    return wsnap.status()


@router.post("/api/world/public/interval")
def world_public_interval(minutes: int = Body(..., embed=True)):
    wsnap._set_setting(wsnap.INTERVAL_KEY, str(max(wsnap.MIN_INTERVAL_MIN, int(minutes))))
    return wsnap.status()


@router.post("/api/world/public/push")
def world_public_push(force: bool = Body(False, embed=True),
                      password: str = Body("", embed=True)):
    """Push now. Runs on a background thread (CPU-only headless render).

    `force` bypasses the enable toggle for a one-off manual push; it does NOT
    bypass the gated-content check or the leak gate — those are unconditional.
    """
    gated = wsnap.gate_reason()
    if gated:
        raise HTTPException(409, f"Refusing to publish: {gated}")
    if not wsnap.push_async(force=bool(force), password=password or ""):
        raise HTTPException(409, "A snapshot push is already running.")
    return {"started": True, **wsnap.status()}
