"""Systems status board — /api/systems

A read-only, live view of every system / subsystem / plugin the app runs, with its
real current status (enabled/disabled/gated/orphan/invisible/infra), whether it has a
leg in the Company world, and which plugins are installed. Backed by the declarative
catalog in app/systems_registry.py — the seed of a future single-source registry.
"""
from fastapi import APIRouter

import systems_registry

router = APIRouter()


@router.get("/api/systems")
def get_systems():
    """The full catalog enriched with live status + installed plugins + rollup counts.
    Never raises (systems_registry.snapshot degrades gracefully)."""
    return systems_registry.snapshot()
