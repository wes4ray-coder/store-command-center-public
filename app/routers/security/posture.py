"""Posture / defenses / Command-view endpoints."""
from fastapi import HTTPException
import defense
from ._base import router


@router.get("/api/security/posture")
def security_posture():
    """Cheap composite for the Command view — latest audit snapshot, score trend,
    recent alerts. No live probes; instant."""
    return defense.posture()


@router.get("/api/security/defenses")
def security_defenses():
    """Every background defense (app jobs + host systems) with live status and
    last-run. Probes docker/journal/ssh/http, so cached ~45s."""
    from cache import cached
    return cached("sec:defenses", 45, defense.defenses)


@router.post("/api/security/defenses/toggle")
def security_defenses_toggle(data: dict):
    """Flip an app defense on/off (and optionally set its interval in minutes)."""
    data = data or {}
    r = defense.toggle(data.get("id", ""), bool(data.get("on")), data.get("interval_min"))
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "toggle failed"))
    from cache import invalidate_prefix
    invalidate_prefix("sec:defenses")
    return r
