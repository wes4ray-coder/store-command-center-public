"""Shared base for the resell package: the single router.

Split out of the former monolithic ``routers/resell.py``. The shared
``APIRouter`` lives here so there are no import cycles between the domain
submodules. The original module had no import-time side effects, so there are
none here beyond constructing the router.
"""
from fastapi import APIRouter

router = APIRouter()
