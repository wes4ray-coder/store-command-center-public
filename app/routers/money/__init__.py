"""Money — real-dollar mission control.

The agent swarm's purpose here is to make the owner REAL dollars (not in-game gold).
Shop search queries (demand signals) flow in from the storefront; "the company"
reviews them against the current catalog with the LLM and proposes money missions:
product gaps we should carry, affiliate/deal opportunities, online income ideas,
and local carpentry work leads (your local area) for the Acme Carpentry front.
Missions follow the same approve/reject queue pattern as world_ops prayers, and an
approved mission is announced into The Company world (world_events + a named agent).

Signals ingest (/api/money/signals POST) is designed to be allowlisted through the
auth middleware — it self-guards with the X-Money-Token header, which must equal
the `money_signal_token` setting.

This module is a package: the shared ``router`` + schema/enums/JSON-parser live in
``_base``; the routes are split across ``signals`` (demand-signal ingest/list),
``intel`` (LLM review + carpentry lead hunt), ``missions`` (the missions queue +
stats) and ``auto`` (the autonomous cadence thread). Importing the submodules runs
their ``@router.*`` decorators, registering every route on the single shared router.
"""
from ._base import router                       # shared router + one-time _ensure_schema()
from . import signals, intel, missions, auto    # noqa: F401  (import registers their @router routes)

# Re-exports so external callers keep resolving names against this module exactly
# as they did against the old single-file module:
#   main.py    -> money.start_auto()
#   prompts.py -> MONEY_GAP_REVIEW_PROMPT, LEAD_HUNT_PROMPT
#                 (lazy refs: ("routers.money", "MONEY_GAP_REVIEW_PROMPT"), ("routers.money", "LEAD_HUNT_PROMPT"))
from .auto import start_auto  # noqa: F401
from .intel import MONEY_GAP_REVIEW_PROMPT, LEAD_HUNT_PROMPT  # noqa: F401

__all__ = ["router", "start_auto", "MONEY_GAP_REVIEW_PROMPT", "LEAD_HUNT_PROMPT"]
