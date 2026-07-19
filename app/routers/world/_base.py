"""Shared base for the world package: the single ``APIRouter`` + the module logger.

Split out of the former monolithic ``routers/world.py``. The shared router lives
here so the submodules can register their ``@router.*`` routes against one router
with no import cycles. There are no import-time side effects beyond constructing
the router (the original module had none either — the sim's schema/seeding is owned
by ``world_defs.seed`` and the background ticker, not this HTTP surface)."""
import logging
from fastapi import APIRouter

router = APIRouter()
logger = logging.getLogger("store")
