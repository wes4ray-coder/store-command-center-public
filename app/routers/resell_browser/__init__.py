"""Resale browser automation — the Store's own headless Chrome for marketplace
posting, auto-fill, AI haggling, and the inbox reader. A second router, included in
main.py alongside resell.py (which keeps the listings/offers/research endpoints).

This module is a package: the shared ``router`` + cross-domain helpers live in
``_base``; the routes are split across ``session`` (browser lifecycle + inspect),
``posting`` (create-page open, photo upload, form auto-fill) and ``messaging``
(AI haggle replies + inbox reader). Importing the submodules runs their
``@router.*`` decorators, registering every route on the single shared ``router``.
"""
from ._base import router                       # shared router + cross-domain helpers
from . import session, posting, messaging       # noqa: F401  (import registers their @router routes)

# Re-exports so external callers keep resolving names against this module exactly
# as they did against the old single-file module:
#   prompts.py -> _HAGGLE_SYSTEM, _INBOX_PARSE_SYSTEM
#                 (lazy refs: ("routers.resell_browser", "_HAGGLE_SYSTEM"), ("routers.resell_browser", "_INBOX_PARSE_SYSTEM"))
from .messaging import _HAGGLE_SYSTEM, _INBOX_PARSE_SYSTEM  # noqa: F401

__all__ = ["router", "_HAGGLE_SYSTEM", "_INBOX_PARSE_SYSTEM"]
