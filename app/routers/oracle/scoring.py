"""Resolution + scoring: when a prediction's horizon arrives, fetch the real price,
score the call, and write the analyst a lesson.

Two scoring curves coexist:
  • LEGACY (rows with batch_id NULL — made before the ladder): closeness is raw
    relative error and the horizon multiplier is 1 + h/30 (heavily favors 90d).
    Old open rows keep resolving under exactly this math.
  • LADDER (rows with a batch_id): closeness is judged against a horizon-scaled
    tolerance (~3%·√h — a 1-day call is graded on day-trade-size moves, a 2-week
    call on bigger swings), wrong-direction closeness is quartered so a lucky
    flat market can't make a wrong call profitable, and the horizon multiplier
    is the gentle 1 + √h/6 — a correct 2-week call beats a correct 1-day call
    modestly (~1.4×) instead of the old 90d ≈ 4× blowout.
"""
import math
from datetime import datetime

from deps import *          # get_conn
from services import *      # (kept consistent with sibling routers)

from ._base import router, _price


def _score(pred: dict, actual: float):
    cur, tgt = pred["current_value"], pred["target_value"]
    actual_dir = "up" if actual >= cur else "down"
    correct = pred["direction"] == actual_dir
    rel = abs(actual - tgt) / actual if actual else 1.0
    h = max(1, int(pred.get("horizon_days") or 1))
    if pred.get("batch_id"):
        # ladder curve — short calls are worth making, long right calls modestly more
        tol = 0.03 * math.sqrt(h)                       # a "normal" move for this horizon
        closeness = 20.0 * max(0.0, 1.0 - rel / tol)    # inside tolerance = points
        if not correct:
            closeness *= 0.25                           # wrong direction ≈ never profitable
        base = (10.0 if correct else -5.0) + closeness
        horizon_mult = 1.0 + math.sqrt(h) / 6.0         # 1d ×1.17 · 7d ×1.44 · 14d ×1.62
    else:
        # legacy curve — untouched so pre-ladder open rows resolve as promised
        closeness = 20.0 * max(0.0, 1.0 - rel)          # perfect target = +20
        base = (10.0 if correct else -5.0) + closeness
        horizon_mult = 1.0 + h / 30.0                   # longer correct calls worth more
    return round(base * horizon_mult, 2), correct, round(rel, 4)


def _resolve_due() -> int:
    conn = get_conn()
    due = [dict(r) for r in conn.execute(
        "SELECT * FROM oracle_predictions WHERE status='open' AND resolve_at<=?",
        (datetime.now().isoformat(timespec="seconds"),)).fetchall()]
    conn.close()
    resolved = 0
    for p in due:
        actual = _price(p["asset"])
        if actual is None:
            continue
        score, correct, rel = _score(p, actual)
        conn = get_conn()
        conn.execute("UPDATE oracle_predictions SET status='resolved',actual_value=?,rel_error=?,"
                     "correct=?,score=?,resolved_at=? WHERE id=?",
                     (actual, rel, 1 if correct else 0, score,
                      datetime.now().isoformat(timespec="seconds"), p["id"]))
        move = "▲" if actual >= p["current_value"] else "▼"
        lesson = (f"{p['asset']}: called {p['direction']} → ${p['target_value']:,.2f} over "
                  f"{p['horizon_days']}d. Actual {move} ${actual:,.2f} "
                  f"({'RIGHT' if correct else 'WRONG'}, {rel:.1%} off, score {score:+}). "
                  f"Thesis was: {p['thesis'][:180]}")
        conn.execute("INSERT INTO oracle_memory (agent_id,text) VALUES (?,?)", (p["agent_id"], lesson))
        conn.commit(); conn.close()
        resolved += 1
    return resolved


@router.post("/api/oracle/resolve")
def resolve_now():
    return {"resolved": _resolve_due()}
