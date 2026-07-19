"""Oracle — a forecasting TOURNAMENT between local LLM models.

Several models compete as "analysts": each researches real-world catalysts
(economic / news / government / social) via searxng, then predicts where a crypto
or stock price is heading, how far out, and why. When the horizon arrives, the
prediction is auto-scored on: got the direction right, how CLOSE the target was,
and how FAR OUT the call was (longer correct calls score much higher). Each analyst
keeps a memory of its past hits/misses and feeds those lessons into future calls, so
they sharpen over time. A leaderboard ranks them. No money moves — this is pure
prediction sport whose winners can later inform the trading side.

Package layout (split out of the former routers/oracle.py):
  _base.py     — shared APIRouter, schema+seed (once), constants, low-level helpers
  forecast.py  — the tournament round + /round, /round/status
  scoring.py   — resolution/scoring + /resolve
  agents.py    — roster/leaderboard/predictions/memory views + mutations
  auto.py      — autonomous daily cadence (start_auto)
"""
from ._base import router
from . import forecast, scoring, agents  # noqa: F401 — importing registers their @router routes
from .auto import start_auto

__all__ = ["router", "start_auto"]
