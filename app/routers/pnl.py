"""Profit & Loss routes — Printify→Etsy margin view.

Thin wrapper over app/pnl.py. The engine never raises, so this endpoint always
returns 200 with a summary (a zero/ready state when there are no sales yet).
"""
from fastapi import APIRouter, Query

import pnl

router = APIRouter()


@router.get("/api/pnl")
def get_pnl(period: str = Query("all", pattern="^(all|30d|mtd)$")):
    """Aggregate P&L for the period. period = all | 30d | mtd."""
    return pnl.summary(period)
