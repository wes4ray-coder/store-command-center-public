"""Resolution + scoring: when a prediction's horizon arrives, fetch the real price,
score the call (direction / closeness / how-far-out), and write the analyst a lesson."""
from datetime import datetime

from deps import *          # get_conn
from services import *      # (kept consistent with sibling routers)

from ._base import router, _price


def _score(pred: dict, actual: float):
    cur, tgt = pred["current_value"], pred["target_value"]
    actual_dir = "up" if actual >= cur else "down"
    correct = pred["direction"] == actual_dir
    rel = abs(actual - tgt) / actual if actual else 1.0
    closeness = 20.0 * max(0.0, 1.0 - rel)          # perfect target = +20
    base = (10.0 if correct else -5.0) + closeness
    horizon_mult = 1.0 + pred["horizon_days"] / 30.0  # longer correct calls worth more
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
