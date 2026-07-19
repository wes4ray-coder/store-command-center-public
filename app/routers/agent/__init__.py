"""AI Assistant tab — a real agentic loop over the store's own API.

The assistant is TOOLED: it plans, calls store endpoints (generated straight from the
FastAPI route table — see assistant_tools.py), observes results, and continues until
done (max-iteration capped). Runs execute inside the orchestrator LLM queue (one job
per loop segment) so they share the single GPU authority with everything else; the
frontend polls /api/agent/events for live tool-call/result/status updates.

Safety: non-read calls are categorized (money / delete / security / world / publish /
settings / swarm / studio / other). Categories not auto-approved pause the loop with
an approval_request the user answers in the chat UI (/api/agent/approve). Every gate
has a per-category auto-approve toggle (assistant settings) — nothing is hard-gated.

Also here: persistent conversations, and "skills" — reusable prompt recipes
(server-side, editable, seeded with a few useful ones).

This module is a package: the shared ``router`` + storage/run-registry helpers live
in ``_base``; the routes are split across ``chat`` (agentic loop + chat/approve/stop),
``conversations``, ``settings`` and ``skills``. Importing the submodules runs their
``@router.*`` decorators, registering every route on the single shared ``router``.
"""
from ._base import router, _ASSISTANT_SYSTEM  # noqa: F401  (_ASSISTANT_SYSTEM: prompts registry ref)
from . import chat, conversations, settings, skills  # noqa: F401  (import registers routes)

__all__ = ["router"]
