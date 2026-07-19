"""Health pulse endpoint — GET /api/health/pulse

A single at-a-glance up/down of every component the Store leans on (this API, the
GPU box, LM Studio, ComfyUI, Docker + key containers, DNS/Pi-hole). Aggregation +
defended probes live in app/health.py; this router is a thin, never-raising shim.
"""
from fastapi import APIRouter

import health

router = APIRouter()


@router.get("/api/health/pulse")
def health_pulse():
    """{components:[{key,label,group,status,detail,checked_at}], summary:{up,down,
    degraded,unknown}, worst}. Cached ~20s in health.pulse(); safe to poll."""
    try:
        return health.pulse()
    except Exception as e:
        # Absolute last-resort guard — the pulse itself is fully defended, but the
        # health check must never 500 and become the thing that looks broken.
        return {"components": [], "summary": {"up": 0, "down": 0, "degraded": 0, "unknown": 0},
                "worst": "unknown", "error": str(e)[:200]}
