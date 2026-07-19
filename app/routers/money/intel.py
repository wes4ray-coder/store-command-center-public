"""money — the company's LLM-driven proposal generators: review shop searches vs the
catalog for demand gaps, and hunt local carpentry work leads via searxng."""
import json as _json
import hmac as _hmac
import random as _random
import requests
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

from deps import *
from services import *
from ._base import router, MISSION_KINDS, _parse_missions_json


# GOAL framing for the company review. Editable copy may live in the prompt
# registry under `money_gap_review`; this local constant is the fallback.
MONEY_GAP_REVIEW_PROMPT = (
    "You are the revenue strategist for Acme — a small indie operation that runs an "
    "online shop (geeky tees, 3D-printable models, software, curated gadget deals) and a "
    "local carpentry business (Acme Carpentry, serving your local area). "
    "Your ONLY goal is to make the owner REAL dollars — not in-game gold: find product "
    "gaps we should carry, affiliate/deal opportunities, online income ideas, and local "
    "carpentry work leads.\n\n"
    "You are given (1) recent shop SEARCH QUERIES from visitors (with how many results "
    "each found) and (2) the CURRENT CATALOG of product titles. Identify products or "
    "niches we DON'T carry but should (demand gaps — especially queries with zero/few "
    "results), plus any other money-making leads the queries imply.\n\n"
    "Return a STRICT JSON array and nothing else — no markdown, no commentary:\n"
    '[{"kind": "product_gap" | "online_income" | "other", "title": "short actionable '
    'title", "detail": "1-3 sentences: what to do and why it will earn", '
    '"est_value_usd": <number, realistic monthly USD estimate>}]\n'
    "3 to 8 items. Be concrete and realistic; skip anything that can't plausibly earn."
)


def _review_system_prompt() -> str:
    try:
        return get_prompt("money_gap_review")
    except Exception:
        return MONEY_GAP_REVIEW_PROMPT


# ── the company review: signals + catalog → proposed missions ────────────────
def _catalog_titles(limit: int = 150) -> list:
    """Current product titles: everything pushed to WordPress plus the local
    affiliate/software catalog (portal tables). Best-effort — an empty catalog
    just means the LLM treats every queried niche as a gap."""
    titles = []
    conn = get_conn()
    try:
        try:
            for r in conn.execute(
                    "SELECT title FROM portal_pushes WHERE kind='product' AND title IS NOT NULL "
                    "AND title!='' ORDER BY pushed_at DESC LIMIT ?", (limit,)).fetchall():
                titles.append(r["title"])
        except Exception:
            pass
        try:
            for r in conn.execute(
                    "SELECT title FROM portal_affiliate ORDER BY updated_at DESC LIMIT ?",
                    (limit,)).fetchall():
                titles.append(r["title"])
        except Exception:
            pass
    finally:
        conn.close()
    seen, out = set(), []
    for t in titles:
        k = (t or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(t.strip())
    return out[:limit]


@router.post("/api/money/review")
def run_review():
    """The company reviews the searches: take all 'new' signals + the current catalog,
    ask the LLM ONCE for demand gaps / money leads, insert them as proposed missions,
    and mark the signals reviewed. Returns a task_id (poll /api/task/{id})."""
    conn = get_conn()
    signals = [dict(r) for r in conn.execute(
        "SELECT * FROM money_signals WHERE status='new' ORDER BY id ASC LIMIT 200").fetchall()]
    conn.close()
    if not signals:
        raise HTTPException(400, "No new signals to review.")
    titles = _catalog_titles()
    sig_lines = "\n".join(
        f"- \"{s['query']}\" (source: {s['source'] or 'shop'}, results found: {s['results_count']})"
        for s in signals)
    cat_lines = "\n".join(f"- {t}" for t in titles) if titles else "(catalog is empty)"
    user = (f"SHOP SEARCH QUERIES ({len(signals)} recent):\n{sig_lines}\n\n"
            f"CURRENT CATALOG ({len(titles)} product titles):\n{cat_lines}")
    sig_ids = [s["id"] for s in signals]
    first_id = sig_ids[0]

    def _work():
        raw = _call_lmstudio(_review_system_prompt(), user, max_tokens=2000, json_mode=True)
        missions = _parse_missions_json(raw)
        c = get_conn()
        try:
            for m in missions:
                c.execute(
                    """INSERT INTO money_missions (kind,title,detail,source_signal_id,est_value_cents)
                       VALUES (?,?,?,?,?)""",
                    (m["kind"], m["title"], m["detail"], first_id, m["est_value_cents"]))
            qmarks = ",".join("?" * len(sig_ids))
            c.execute(f"UPDATE money_signals SET status='reviewed' WHERE id IN ({qmarks})", sig_ids)
            c.commit()
        finally:
            c.close()
        return {"proposed": len(missions), "signals_reviewed": len(sig_ids),
                "missions": missions}

    tid = orch.submit_llm(_work, desc=f"Money review: {len(signals)} signals", priority=2, task="money_gap_review")  # autonomous
    return {"task_id": tid, "signals": len(signals)}


# ── carpentry lead hunting (searxng → LLM → missions) ────────────────────────
SEARX_URL = "http://127.0.0.1:8899"

DEFAULT_LEAD_QUERIES = [
    "carpenter needed your town",
    "handyman wanted Wood County Texas",
    "finish carpentry work DFW",
    "deck repair contractor wanted East Texas",
    "home repair help wanted Tyler TX",
]

LEAD_HUNT_PROMPT = (
    "You screen web search results to find REAL local work leads for Acme Carpentry — "
    "a one-man precision repair / finish-carpentry / remodel operation based in your town, "
    "serving the local area and DFW. From the search results given, pick ONLY entries that "
    "plausibly lead to paid carpentry/handyman work (job posts, 'looking for a carpenter' "
    "asks, gig boards, bid requests). Skip ads, directories, and how-to articles. "
    "Respond with STRICT JSON: an array of objects "
    '[{"title": str, "detail": str (1-2 sentences INCLUDING the url), "est_value_usd": number}]. '
    "Empty array if nothing qualifies."
)


def _searx(query: str, n: int = 5) -> list:
    try:
        r = requests.get(f"{SEARX_URL}/search",
                         params={"q": query, "format": "json", "language": "en"},
                         timeout=20)
        r.raise_for_status()
        out = []
        for res in (r.json().get("results") or [])[:n]:
            out.append({"title": (res.get("title") or "")[:200],
                        "url": res.get("url") or "",
                        "snippet": (res.get("content") or "")[:300]})
        return out
    except Exception as e:
        logger.warning("searx query failed (%s): %s", query, e)
        return []


@router.post("/api/money/leads/hunt")
def hunt_leads():
    """Hunt local carpentry work leads: searxng sweep → LLM screen → proposed
    carpentry_lead missions. Queries overridable via setting `money_lead_queries`
    (one per line). Returns a task_id (poll /api/task/{id})."""
    qraw = get_setting("money_lead_queries", "") or ""
    queries = [q.strip() for q in qraw.splitlines() if q.strip()] or DEFAULT_LEAD_QUERIES

    results, seen_urls = [], set()
    for q in queries:
        for res in _searx(q):
            if res["url"] and res["url"] not in seen_urls:
                seen_urls.add(res["url"])
                results.append(res)
    if not results:
        raise HTTPException(502, "searxng returned no results (is it running on :8899?)")

    # skip urls already captured in existing carpentry_lead missions
    conn = get_conn()
    known = " ".join(r["detail"] or "" for r in conn.execute(
        "SELECT detail FROM money_missions WHERE kind='carpentry_lead'").fetchall())
    conn.close()
    fresh = [r for r in results if r["url"] not in known]
    if not fresh:
        return {"task_id": None, "results": len(results), "fresh": 0,
                "note": "all results already known"}

    lines = "\n".join(f"- {r['title']} | {r['url']} | {r['snippet']}" for r in fresh[:40])
    user = f"SEARCH RESULTS ({len(fresh)} fresh):\n{lines}"

    def _work():
        raw = _call_lmstudio(
            get_prompt("money_lead_hunt") if _has_prompt("money_lead_hunt") else LEAD_HUNT_PROMPT,
            user, max_tokens=1800, json_mode=True)
        missions = _parse_missions_json(raw)
        c = get_conn()
        try:
            for m in missions:
                c.execute(
                    """INSERT INTO money_missions (kind,title,detail,est_value_cents)
                       VALUES ('carpentry_lead',?,?,?)""",
                    (m["title"], m["detail"], m["est_value_cents"]))
            c.commit()
        finally:
            c.close()
        return {"proposed": len(missions), "screened": len(fresh)}

    tid = orch.submit_llm(_work, desc=f"Lead hunt: {len(fresh)} results", priority=2, task="money_lead_hunt")  # autonomous
    return {"task_id": tid, "results": len(results), "fresh": len(fresh)}


def _has_prompt(key: str) -> bool:
    try:
        return bool(get_prompt(key))
    except Exception:
        return False
