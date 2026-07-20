"""Accuracy-weighted oracle CONSENSUS — the signal the Company consumes.

Each analyst's open ladder calls are weighted by that analyst's RESOLVED track
record (Laplace-smoothed hit rate, so a rookie counts ~50%). Per asset we net
the weighted up/down votes per rung into a bias in [-1, +1], then average the
rungs into an overall asset bias. `brief()` renders the compact one-line
summary that world strategy / leaders / crypto drafts / money reviews cite.

ADVISORY ONLY: nothing here moves money or triggers actions — consumers embed
it as context inside flows that are already approval-gated, and the whole
hookup sits behind the `oracle_company_hookup` toggle (checked in `brief()` /
`hookup_enabled()` so consumers stay one-liners).
"""
from datetime import datetime, timedelta

from deps import *          # get_conn
from services import *      # (kept consistent with sibling routers)

from ._base import router, oracle_setting

MAX_AGE_DAYS = 21           # ignore open calls older than this (stale theses)


def hookup_enabled() -> bool:
    return oracle_setting("oracle_company_hookup") in ("1", "true", "on")


def _agent_weights(conn) -> dict:
    """agent_id → Laplace-smoothed resolved hit rate ((correct+1)/(resolved+2))."""
    rows = conn.execute(
        "SELECT agent_id, COUNT(*) AS n, SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS c "
        "FROM oracle_predictions WHERE status='resolved' GROUP BY agent_id").fetchall()
    return {r["agent_id"]: (r["c"] or 0, r["n"] or 0) for r in rows}


def compute(conn=None) -> dict:
    """{"assets": [{asset, market, bias, n_calls, n_agents, rungs: [...]}, ...]}
    sorted by |bias| — strongest conviction first."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        cutoff = (datetime.now() - timedelta(days=MAX_AGE_DAYS)).isoformat(timespec="seconds")
        wraw = _agent_weights(conn)
        preds = [dict(r) for r in conn.execute(
            "SELECT agent_id,asset,market,direction,target_value,current_value,horizon_days,"
            "confidence FROM oracle_predictions WHERE status='open' AND created_at>=?",
            (cutoff,)).fetchall()]
    finally:
        if own:
            conn.close()
    by_asset = {}
    for p in preds:
        c, n = wraw.get(p["agent_id"], (0, 0))
        w = (c + 1) / (n + 2)                                  # smoothed accuracy weight
        a = by_asset.setdefault(p["asset"], {"market": p["market"], "rungs": {}, "agents": set()})
        a["agents"].add(p["agent_id"])
        r = a["rungs"].setdefault(p["horizon_days"], {"num": 0.0, "den": 0.0, "tsum": 0.0, "n": 0})
        sign = 1.0 if p["direction"] == "up" else -1.0
        conf = max(0.05, min(float(p["confidence"] or 0.5), 1.0))
        r["num"] += sign * w * conf
        r["den"] += w * conf
        r["tsum"] += float(p["target_value"] or 0)
        r["n"] += 1
    assets = []
    for asset, a in by_asset.items():
        rungs = []
        for h in sorted(a["rungs"]):
            r = a["rungs"][h]
            bias = r["num"] / r["den"] if r["den"] else 0.0
            rungs.append({"h": h, "bias": round(bias, 3),
                          "direction": "up" if bias >= 0 else "down",
                          "avg_target": round(r["tsum"] / r["n"], 6) if r["n"] else None,
                          "n": r["n"]})
        overall = sum(r["bias"] for r in rungs) / len(rungs) if rungs else 0.0
        assets.append({"asset": asset, "market": a["market"], "bias": round(overall, 3),
                       "n_calls": sum(r["n"] for r in rungs), "n_agents": len(a["agents"]),
                       "rungs": rungs})
    assets.sort(key=lambda x: abs(x["bias"]), reverse=True)
    return {"assets": assets}


def _rung_label(h: int) -> str:
    return {7: "1w", 14: "2w"}.get(h, f"{h}d")


def brief(limit: int = 5, conn=None) -> str:
    """One compact advisory line for LLM/context embedding. Empty string when the
    company hookup is toggled off or there's nothing open — callers can stay dumb."""
    if not hookup_enabled():
        return ""
    try:
        assets = compute(conn)["assets"][:limit]
    except Exception:
        return ""
    if not assets:
        return ""
    parts = []
    for a in assets:
        mood = "bullish" if a["bias"] > 0.15 else ("bearish" if a["bias"] < -0.15 else "mixed")
        chips = ",".join(f"{_rung_label(r['h'])}{'▲' if r['direction'] == 'up' else '▼'}"
                         for r in a["rungs"])
        parts.append(f"{a['asset']} {mood} ({a['bias']:+.2f}; {chips}; "
                     f"{a['n_calls']} calls/{a['n_agents']} analysts)")
    return "Oracle tournament consensus (accuracy-weighted, advisory only): " + " · ".join(parts)


@router.get("/api/oracle/consensus")
def get_consensus():
    d = compute()
    return {"enabled": hookup_enabled(), "brief": brief(), **d}
