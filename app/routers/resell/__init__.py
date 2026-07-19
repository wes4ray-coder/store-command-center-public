"""resell routes.

This module is a package: the shared ``router`` lives in ``_base`` and the routes
are split by concern across ``ai`` (vision analysis + price research), ``listings``
(listings CRUD, photos, platform content, eBay post) and ``offers`` (buyer offers,
browser-automation posting, monitor status). Importing the submodules runs their
``@router.*`` decorators, registering every route on the single shared ``router``.
"""
from ._base import router          # shared router
from . import ai, listings, offers  # noqa: F401  (import registers their @router routes)

__all__ = ["router"]
