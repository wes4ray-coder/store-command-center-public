"""Oracle — a forecasting TOURNAMENT between local LLM models.

Several models compete as "analysts": each researches real-world catalysts
(economic / news / government / social) via searxng, then publishes a LADDER of
predictions for where a crypto or stock price is heading — one call per horizon
(1d / 3d / 5d / 1w / 2w by default, optional 30d long tier), each resolving and
scoring independently when its horizon arrives. Scoring rewards direction plus
horizon-scaled closeness; a correct 2-week call beats a correct 1-day call
modestly. Each analyst keeps a memory of its past hits/misses and feeds those
lessons into future calls, so they sharpen over time. A leaderboard ranks them.
No money moves — but the accuracy-weighted CONSENSUS of open calls is exposed as
an advisory signal the Company (world strategy/leaders, crypto strategy drafts,
money reviews) can cite, behind the `oracle_company_hookup` toggle.

Package layout (split out of the former routers/oracle.py):
  _base.py     — shared APIRouter, schema+seed (once), constants, ladder, helpers
  forecast.py  — the ladder tournament round + /round, /round/status
  scoring.py   — resolution/scoring (ladder + legacy curves) + /resolve
  agents.py    — roster/leaderboard/predictions/memory views + mutations
  consensus.py — accuracy-weighted consensus signal + /consensus (advisory only)
  auto.py      — autonomous cadence (15-min resolve tick, daily round) + /settings
"""
from ._base import router
from . import forecast, scoring, agents, consensus  # noqa: F401 — importing registers their @router routes
from .auto import start_auto

__all__ = ["router", "start_auto"]
