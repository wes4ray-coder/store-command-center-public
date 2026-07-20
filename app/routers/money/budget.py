"""budget — 🧮 the AI budget + grocery planner that sits on top of the money ledger.

The owner asked for one thing: "help me manage my money and budget for food and gas …
post on the calendar how much for budget and saving, and recommendations for grocery
list … keep up with what I buy, how much, item count and price, and how fast I go
through it." This module is that, built strictly on rows he actually recorded.

THE HOUSE RULE FOR THIS FILE: **never fabricate a number.** Every figure returned
here traces back to a row in `purchases` / `purchase_items` / `paychecks` / `bills`.
Where the data is too thin, the answer is the literal string ``insufficient_data``
plus how many observations exist and how many are needed — never a plausible-looking
guess. That rule is why `MIN_OBSERVATIONS` exists and why nothing predicts from two
points.

Four layers, bottom up:

  1. ITEM NORMALIZATION  `normalize_item_name` collapses the way a human types the
     same thing across trips ("Milk 1 gal", "milk gallon", "MILK") onto one match key
     ("milk"). Pure, deterministic, and tested — it is the join key everything else
     depends on. The raw text the owner typed is always kept alongside for display.

  2. CONSUMPTION  from the repeat purchases of one normalized item: average days
     between buys, average qty per buy, average/last unit price and its trend, and a
     predicted next-need date. Requires MIN_OBSERVATIONS (3) distinct purchase DAYS —
     three points give two intervals, the minimum from which an interval can vary at
     all. Confidence comes from the coefficient of variation of those intervals and
     is never hidden: a wildly irregular item says so.

  3. BUDGET  envelopes per category over the owner's REAL pay period (derived from
     recorded `paychecks`, confirmed by him). Committed outgoings come from the
     EXISTING bill projection in calendar.collect_events — the cycle math is reused,
     never reimplemented. No double counting: bills come from bills/bill_payments,
     everything else from `purchases`, and the two sets never overlap (the same
     invariant ledger.py already documents).

  4. PLANNER  an LLM grocery list, grounded in the computed figures and validated
     against the owner's OWN item history on the way back. It rides orch.submit_llm
     like every other model call in this app — never a direct LM Studio call — and
     its output is ADVISORY: saved as a draft, editable, and applied to nothing
     until the owner explicitly accepts it.

Calendar: `budget_calendar_events()` is called by calendar.py (lazily, to keep the
import one-way) so the new markers ride the EXISTING /api/calendar/events shape and
the existing ICS feed. Anything extrapolated carries `projected: true`, the same flag
the projected bill occurrences already use.

NOT the game world's economy (world_ops_ledger / world_bills) — unrelated.
"""
import json as _json
import re as _re
import statistics as _stats
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException, Body, Request
from pydantic import BaseModel

from deps import *          # get_conn, get_setting, orch, _call_lmstudio, get_prompt, logger
from ._base import router
from .bills import _add_months

# ── schema (defined in db_schema.py; ensured once here at import, exactly like
#    bills.py / ledger.py) ─────────────────────────────────────────────────────
from db_schema import create_budget_tables as _create_budget_tables


def _ensure_budget_schema():
    conn = get_conn()
    try:
        _create_budget_tables(conn)   # commits internally
    finally:
        conn.close()


_ensure_budget_schema()


# ══ TUNABLES ══════════════════════════════════════════════════════════════════
MIN_OBSERVATIONS = 3        # distinct purchase days before ANYTHING is predicted.
                            # 3 points = 2 intervals = the fewest from which an
                            # interval can have any spread at all. Two points give
                            # one interval and zero evidence it repeats.
MIN_PRICE_POINTS = 3        # priced observations before a price TREND is claimed
_FLAT_TREND_PCT = 2.0       # |change| under this reads as "flat", not a trend
_MAX_ITEMS = 400            # ceilings so one call can never spin the box
_MAX_PLAN_LINES = 40
_MAX_PERIOD_MARKERS = 4     # how many pay periods ahead get a calendar marker

# Confidence bands over the coefficient of variation (stdev/mean) of the intervals.
_CV_HIGH, _CV_MEDIUM = 0.25, 0.50

# Categories the UI seeds an envelope set from. Free text everywhere else — these
# are only defaults offered in the setup form, never enforced.
DEFAULT_ENVELOPES = ("food", "gas", "savings", "other")
SAVINGS_CATEGORY = "savings"
FOOD_CATEGORY = "food"

# Pay cycles. Mirrors ledger.PAY_CYCLES; "irregular"/unset means we do NOT project
# income at all — we only report what was actually received.
BUDGET_CYCLES = ("weekly", "biweekly", "semimonthly", "monthly", "irregular")

# Feature toggles (house rule: every gate ships with a toggle).
#   budget_planner_enabled       — may the AI planner run at all. Default ON: it
#                                  only ever writes a DRAFT the owner must accept.
#   budget_calendar_predictions  — may predicted restock / grocery-day markers show
#                                  on the calendar. Default ON; they are flagged
#                                  `projected` so they never read as facts.
# There is deliberately NO toggle for "auto-apply a plan" — that path does not
# exist. A plan becomes a purchase only by an explicit owner action.
TOGGLES = {
    "budget_planner_enabled": True,
    "budget_calendar_predictions": True,
}


def _toggle(key: str) -> bool:
    raw = get_setting(key, None)
    if raw in (None, ""):
        return bool(TOGGLES.get(key, False))
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _set_setting(key: str, value: str):
    conn = get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (key, str(value)))
        conn.commit()
    finally:
        conn.close()


# ══ 1. ITEM NAME NORMALIZATION ════════════════════════════════════════════════
# The join key across shopping trips. Deliberately small and boring: a big fuzzy
# matcher would silently merge things that are not the same item, and a wrong merge
# corrupts every consumption number downstream. When in doubt it keeps them apart.

# Unit / size words that describe HOW MUCH, never WHAT. Stripped so "milk 1 gal"
# and "milk gallon" land on the same key.
_UNIT_WORDS = {
    "gal", "gallon", "gallons", "qt", "quart", "quarts", "pt", "pint", "pints",
    "l", "liter", "liters", "litre", "litres", "ml", "cl",
    "oz", "ounce", "ounces", "floz", "lb", "lbs", "pound", "pounds",
    "g", "gr", "gram", "grams", "kg", "kilo", "kilos",
    "ct", "count", "cnt", "pk", "pack", "packs", "pkg", "package", "box", "boxes",
    "bag", "bags", "bottle", "bottles", "can", "cans", "case", "cases",
    "jar", "jars", "carton", "cartons", "dozen", "doz", "each", "ea", "ct.",
}
# Marketing / size adjectives that vary trip to trip on the SAME item.
_FILLER_WORDS = {
    "the", "a", "an", "of", "and", "with", "brand", "value", "great",
    "large", "small", "medium", "mini", "jumbo", "xl", "family", "size", "sized",
    "fresh", "natural", "organic", "premium", "select", "classic", "original",
}
# "1gal", "2ct", "12oz", "1.5l" — a number welded to a unit.
_NUM_UNIT_RE = _re.compile(r"^\d+(?:[.,]\d+)?(?P<u>[a-z]+)$")
_PURE_NUM_RE = _re.compile(r"^\d+(?:[.,]\d+)?$")


def _singular(tok: str) -> str:
    """Crude, intentional de-pluralizer: 'eggs'→'egg', 'berries'→'berry'.

    Only the endings that are safe to strip. Words under 4 characters and the
    -ss family ('glass') are left alone — over-stemming merges distinct items,
    which is the failure mode that actually costs the owner accuracy.
    """
    if len(tok) < 4 or tok.endswith("ss"):
        return tok
    if tok.endswith("ies"):
        return tok[:-3] + "y"
    if tok.endswith("es") and tok[-3:-2] in ("s", "x", "z", "h"):
        return tok[:-2]
    if tok.endswith("s"):
        return tok[:-1]
    return tok


def normalize_item_name(raw: str) -> str:
    """Collapse a typed item name onto its match key. Pure and deterministic.

        "Milk 1 gal"        -> "milk"
        "milk gallon"       -> "milk"
        "MILK, 2%"          -> "milk"
        "Large Eggs 12 ct"  -> "egg"
        "Dr Pepper 12pk"    -> "dr pepper"

    Never returns "" for non-empty input: if every token looked like packaging,
    the cleaned original is used instead. Losing the item entirely would be worse
    than an imperfect key.
    """
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    s = _re.sub(r"\([^)]*\)", " ", s)              # drop "(2 pack)" asides
    s = s.replace("%", " ")                        # "2%" is a variant, not an item
    s = _re.sub(r"[^a-z0-9.\s]+", " ", s)          # punctuation -> space
    tokens = [t for t in s.split() if t]

    kept = []
    for t in tokens:
        t = t.strip(".")
        if not t:
            continue
        if _PURE_NUM_RE.match(t):                  # bare "1", "12"
            continue
        m = _NUM_UNIT_RE.match(t)
        if m and m.group("u") in _UNIT_WORDS:      # "1gal", "12ct"
            continue
        if t in _UNIT_WORDS or t in _FILLER_WORDS:
            continue
        kept.append(_singular(t))

    out = " ".join(kept).strip()
    if out:
        return out
    # Everything was packaging noise — fall back to the cleaned original so the
    # item still has a stable key rather than vanishing into "".
    return " ".join(tokens).strip()


# ══ PURCHASE LINE ITEMS (written from ledger.py's create/update) ══════════════
def _line_cents(v, field):
    if v in (None, ""):
        return None
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} must be a whole number of cents")


def _qty(v) -> float:
    if v in (None, ""):
        return 1.0
    try:
        q = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, "qty must be a number")
    if q <= 0:
        raise HTTPException(400, "qty must be greater than zero")
    return q


def clean_items(items, fallback_category: str = "") -> list:
    """Validate a list of line-item dicts into rows ready for `purchase_items`.

    Fills in whichever of (qty, unit_price_cents, line_total_cents) can be derived
    from the other two, and NEVER invents the third when only one is known — an
    unpriced line is stored with a NULL unit price rather than a made-up one.
    """
    if items in (None, ""):
        return []
    if not isinstance(items, list):
        raise HTTPException(400, "items must be a list")
    if len(items) > _MAX_PLAN_LINES * 4:
        raise HTTPException(400, "too many line items on one purchase")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise HTTPException(400, "each item must be an object")
        name = str(it.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "each line item needs a name")
        qty = _qty(it.get("qty"))
        unit_price = _line_cents(it.get("unit_price_cents"), "unit_price_cents")
        total = _line_cents(it.get("line_total_cents"), "line_total_cents")
        if total is None and unit_price is not None:
            total = int(round(qty * unit_price))
        if total is None:
            raise HTTPException(400, f"line {name!r} needs a unit price or a line total")
        if unit_price is None and qty > 0:
            unit_price = int(round(total / qty))
        out.append({
            "name": name[:160],
            "normalized_name": normalize_item_name(name)[:160],
            "qty": qty,
            "unit": str(it.get("unit") or "").strip()[:24],
            "unit_price_cents": unit_price,
            "line_total_cents": total,
            "category": (str(it.get("category") or "").strip() or fallback_category)[:80],
        })
    return out


def replace_purchase_items(conn, purchase_id: int, items: list):
    """Swap the whole line-item set for one purchase (edit = replace, not merge)."""
    conn.execute("DELETE FROM purchase_items WHERE purchase_id=?", (purchase_id,))
    for it in items:
        conn.execute(
            "INSERT INTO purchase_items (purchase_id,name,normalized_name,qty,unit,"
            "unit_price_cents,line_total_cents,category) VALUES (?,?,?,?,?,?,?,?)",
            (purchase_id, it["name"], it["normalized_name"], it["qty"], it["unit"],
             it["unit_price_cents"], it["line_total_cents"], it["category"]))


def items_total_cents(items: list) -> int:
    return sum(int(i.get("line_total_cents") or 0) for i in items)


def load_purchase_items(conn, purchase_id: int) -> list:
    try:
        rows = conn.execute(
            "SELECT * FROM purchase_items WHERE purchase_id=? ORDER BY id", (purchase_id,)).fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]


# ══ 2. CONSUMPTION ════════════════════════════════════════════════════════════
def _observations(conn, norm: str) -> list:
    """Every purchase DAY for one normalized item, oldest first.

    Same-day lines for the same item are one observation with their quantities and
    totals summed — buying two gallons in one trip is one shopping event, and
    counting it as two would inject a fake zero-day interval and wreck the cadence.
    """
    try:
        rows = conn.execute(
            "SELECT p.purchased_at AS d, i.name AS name, i.qty AS qty, i.unit AS unit, "
            "i.unit_price_cents AS up, i.line_total_cents AS total, "
            "COALESCE(NULLIF(i.category,''), p.category) AS cat "
            "FROM purchase_items i JOIN purchases p ON p.id = i.purchase_id "
            "WHERE i.normalized_name = ? AND p.purchased_at IS NOT NULL AND p.purchased_at <> '' "
            "ORDER BY p.purchased_at ASC, i.id ASC", (norm,)).fetchall()
    except Exception:
        return []
    days: dict = {}
    for r in rows:
        d = str(r["d"])[:10]
        o = days.setdefault(d, {"date": d, "qty": 0.0, "total_cents": 0,
                                "names": [], "unit": "", "category": "", "priced_qty": 0.0,
                                "priced_cents": 0})
        o["qty"] += float(r["qty"] or 0)
        o["total_cents"] += int(r["total"] or 0)
        if r["up"] is not None:
            o["priced_qty"] += float(r["qty"] or 0)
            o["priced_cents"] += int(r["up"]) * float(r["qty"] or 0)
        o["names"].append(r["name"])
        o["unit"] = o["unit"] or (r["unit"] or "")
        o["category"] = o["category"] or (r["cat"] or "")
    out = []
    for d in sorted(days):
        o = days[d]
        # Unit price for the day = qty-weighted mean of the priced lines only.
        o["unit_price_cents"] = (int(round(o["priced_cents"] / o["priced_qty"]))
                                 if o["priced_qty"] > 0 else None)
        o["name"] = o["names"][-1]
        o.pop("names", None)
        o.pop("priced_qty", None)
        o.pop("priced_cents", None)
        out.append(o)
    return out


def _price_trend(prices: list) -> dict:
    """Direction and size of the unit-price drift, or insufficient_data.

    Compares the mean of the older half against the mean of the newer half. Blunt
    on purpose: a regression slope over 4 noisy points looks far more authoritative
    than it deserves to, and this is the owner's grocery bill, not a research paper.
    """
    pts = [p for p in prices if p is not None]
    if len(pts) < MIN_PRICE_POINTS:
        return {"status": "insufficient_data", "price_points": len(pts),
                "needed": MIN_PRICE_POINTS,
                "message": f"{len(pts)} priced purchase{'' if len(pts) == 1 else 's'} so far — "
                           f"{MIN_PRICE_POINTS} needed before a price trend means anything."}
    half = len(pts) // 2
    older = pts[:half] or pts[:1]
    newer = pts[-half:] or pts[-1:]
    a, b = _stats.fmean(older), _stats.fmean(newer)
    pct = ((b - a) / a * 100.0) if a else 0.0
    direction = "flat" if abs(pct) < _FLAT_TREND_PCT else ("rising" if pct > 0 else "falling")
    return {"status": "ok", "price_points": len(pts), "direction": direction,
            "change_pct": round(pct, 1),
            "earlier_avg_cents": int(round(a)), "recent_avg_cents": int(round(b))}


def consumption_stats(conn, norm: str, today: Optional[date] = None) -> dict:
    """How fast the owner goes through one item — or an honest refusal to guess.

    Below MIN_OBSERVATIONS this returns status='insufficient_data' with the count so
    far and what is still needed, and NO prediction of any kind. That is the whole
    point: two purchases cannot tell you a cadence, and pretending otherwise would
    put a fake date on his calendar.
    """
    today = today or date.today()
    obs = _observations(conn, norm)
    n = len(obs)
    base = {
        "normalized_name": norm,
        "display_name": obs[-1]["name"] if obs else norm,
        "category": (obs[-1]["category"] if obs else ""),
        "unit": (obs[-1]["unit"] if obs else ""),
        "observations": n,
        "min_observations": MIN_OBSERVATIONS,
        "first_purchase": obs[0]["date"] if obs else None,
        "last_purchase": obs[-1]["date"] if obs else None,
        "last_unit_price_cents": (obs[-1]["unit_price_cents"] if obs else None),
        "last_qty": (round(obs[-1]["qty"], 3) if obs else None),
        "total_spent_cents": sum(o["total_cents"] for o in obs),
        "total_qty": round(sum(o["qty"] for o in obs), 3),
        # Every point we have, always — so a sparse item can still be PLOTTED even
        # though it must not be predicted from.
        "points": [{"date": o["date"], "qty": round(o["qty"], 3),
                    "total_cents": o["total_cents"],
                    "unit_price_cents": o["unit_price_cents"]} for o in obs],
    }

    if n < MIN_OBSERVATIONS:
        need = MIN_OBSERVATIONS - n
        base.update({
            "status": "insufficient_data",
            "needed": need,
            "message": (f"{n} purchase{'' if n == 1 else 's'} recorded — "
                        f"{need} more before this can predict anything."),
            # Explicitly null, not absent: a consumer must not be able to read a
            # missing key as a zero.
            "avg_interval_days": None, "avg_qty": None, "avg_unit_price_cents": None,
            "predicted_next_date": None, "days_until_next": None,
            "confidence": "none", "interval_cv": None,
            "price_trend": _price_trend([o["unit_price_cents"] for o in obs]),
        })
        return base

    dates = [date.fromisoformat(o["date"]) for o in obs]
    intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    avg_interval = _stats.fmean(intervals)
    stdev = _stats.pstdev(intervals) if len(intervals) > 1 else 0.0
    cv = (stdev / avg_interval) if avg_interval > 0 else 0.0

    # Confidence is a function of BOTH spread and sample size. A tight cadence over
    # exactly 3 points is still only "medium" — three trips is not a habit yet.
    if cv <= _CV_HIGH and n >= 5:
        confidence = "high"
    elif cv <= _CV_MEDIUM:
        confidence = "medium"
    else:
        confidence = "low"

    step = max(1, int(round(avg_interval)))
    predicted = dates[-1] + timedelta(days=step)
    spread = max(1, int(round(stdev)))
    qtys = [o["qty"] for o in obs]
    priced = [o["unit_price_cents"] for o in obs if o["unit_price_cents"] is not None]

    base.update({
        "status": "ok",
        "avg_interval_days": round(avg_interval, 1),
        "interval_stdev_days": round(stdev, 1),
        "interval_cv": round(cv, 3),
        "intervals": intervals,
        "confidence": confidence,
        "confidence_reason": (
            f"{n} purchases, gaps of {min(intervals)}–{max(intervals)} days "
            f"(spread {round(cv * 100)}% of the average)"),
        "avg_qty": round(_stats.fmean(qtys), 3),
        "avg_unit_price_cents": int(round(_stats.fmean(priced))) if priced else None,
        "avg_spend_per_purchase_cents": int(round(_stats.fmean([o["total_cents"] for o in obs]))),
        "predicted_next_date": predicted.isoformat(),
        "predicted_earliest": (predicted - timedelta(days=spread)).isoformat(),
        "predicted_latest": (predicted + timedelta(days=spread)).isoformat(),
        "days_until_next": (predicted - today).days,
        "price_trend": _price_trend([o["unit_price_cents"] for o in obs]),
        "monthly_spend_cents": (
            int(round(base["total_spent_cents"] / max(1, (dates[-1] - dates[0]).days) * 30.44))
            if (dates[-1] - dates[0]).days > 0 else None),
    })
    return base


def _all_normalized(conn, category: Optional[str] = None) -> list:
    try:
        if category:
            rows = conn.execute(
                "SELECT i.normalized_name AS n FROM purchase_items i "
                "JOIN purchases p ON p.id=i.purchase_id "
                "WHERE LOWER(COALESCE(NULLIF(i.category,''), p.category))=LOWER(?) "
                "GROUP BY i.normalized_name ORDER BY COUNT(*) DESC LIMIT ?",
                (category, _MAX_ITEMS)).fetchall()
        else:
            rows = conn.execute(
                "SELECT normalized_name AS n FROM purchase_items "
                "GROUP BY normalized_name ORDER BY COUNT(*) DESC LIMIT ?",
                (_MAX_ITEMS,)).fetchall()
    except Exception:
        return []
    return [r["n"] for r in rows if r["n"]]


def all_item_stats(conn, category: Optional[str] = None, today: Optional[date] = None) -> list:
    return [consumption_stats(conn, n, today=today) for n in _all_normalized(conn, category)]


@router.get("/api/budget/consumption")
def consumption(category: Optional[str] = None, sort: str = "spend"):
    """Every item the owner has line-itemed, with its cadence — the discovery view.

    Sorted by total spend by default, because that is the sort that answers the
    question he did not know he was asking ("how much am I actually spending on
    that?"). Items below MIN_OBSERVATIONS are INCLUDED — with their points and an
    insufficient_data status — so a thin item is visible rather than hidden.
    """
    today = date.today()
    conn = get_conn()
    try:
        stats = all_item_stats(conn, category, today=today)
        cats = category_rollup(conn, stats)
    finally:
        conn.close()
    key = {
        "spend": lambda s: -(s.get("total_spent_cents") or 0),
        "frequency": lambda s: (s.get("avg_interval_days") if s.get("avg_interval_days")
                                is not None else 1e9),
        "count": lambda s: -(s.get("observations") or 0),
        "soon": lambda s: (s.get("days_until_next") if s.get("days_until_next")
                           is not None else 1e9),
        "name": lambda s: s.get("normalized_name") or "",
    }.get(sort, lambda s: -(s.get("total_spent_cents") or 0))
    stats.sort(key=key)
    ready = [s for s in stats if s["status"] == "ok"]
    return {
        "items": stats, "categories": cats, "today": today.isoformat(),
        "min_observations": MIN_OBSERVATIONS,
        "counts": {"items": len(stats), "predictable": len(ready),
                   "insufficient": len(stats) - len(ready)},
        # Said out loud so the UI never has to infer it.
        "note": (f"{len(stats) - len(ready)} item(s) do not have {MIN_OBSERVATIONS} "
                 f"purchases yet, so no cadence is predicted for them."),
    }


@router.get("/api/budget/consumption/item")
def consumption_item(request: Request):
    """One item's full history — the series behind the per-item chart.

    Takes ?name= (raw or normalized; it is normalized either way) rather than a path
    param so item names with slashes/spaces need no escaping dance.
    """
    raw = (request.query_params.get("name") or "").strip()
    if not raw:
        raise HTTPException(400, "name required")
    norm = normalize_item_name(raw)
    conn = get_conn()
    try:
        s = consumption_stats(conn, norm)
        try:
            variants = [r["name"] for r in conn.execute(
                "SELECT name, COUNT(*) c FROM purchase_items WHERE normalized_name=? "
                "GROUP BY name ORDER BY c DESC LIMIT 12", (norm,)).fetchall()]
        except Exception:
            variants = []
    finally:
        conn.close()
    if not s["observations"]:
        raise HTTPException(404, f"nothing recorded for {raw!r}")
    s["variants"] = variants        # the different ways he typed the same thing
    return s


def category_rollup(conn, stats: Optional[list] = None, months: int = 12) -> dict:
    """Food vs gas vs other, per month — where the money actually goes.

    Built from `purchases` (the authoritative amounts), NOT from the line items, so
    it stays correct for trips logged as a single total. The item-level `stats` only
    contribute the per-category item counts.
    """
    months = max(1, min(36, int(months)))
    today = date.today()
    keys, y, m = [], today.year, today.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    idx = {k: i for i, k in enumerate(keys)}
    series: dict = {}
    try:
        rows = conn.execute(
            "SELECT substr(purchased_at,1,7) ym, LOWER(COALESCE(NULLIF(category,''),'uncategorized')) cat, "
            "SUM(amount_cents) total, COUNT(*) n FROM purchases "
            "WHERE substr(purchased_at,1,7) >= ? GROUP BY ym, cat", (keys[0],)).fetchall()
    except Exception:
        rows = []
    totals: dict = {}
    for r in rows:
        i = idx.get(r["ym"])
        if i is None:
            continue
        series.setdefault(r["cat"], [0] * months)[i] += r["total"] or 0
        totals[r["cat"]] = totals.get(r["cat"], 0) + (r["total"] or 0)
    item_counts: dict = {}
    for s in (stats or []):
        c = (s.get("category") or "uncategorized").lower()
        item_counts[c] = item_counts.get(c, 0) + 1
    return {"months": keys, "series": series, "totals": totals, "item_counts": item_counts}


@router.get("/api/budget/categories")
def budget_categories(months: int = 12):
    """Per-category spend over time (the rollup chart). Purchases only — bills are
    a separate, non-overlapping set and are never folded in here."""
    conn = get_conn()
    try:
        return category_rollup(conn, months=months)
    finally:
        conn.close()


@router.get("/api/budget/items/suggest")
def items_suggest(request: Request, limit: int = 12):
    """Autocomplete built from the owner's OWN history — the only item vocabulary
    this app has. Returns the last price and typical qty so entry is one keystroke."""
    q = normalize_item_name((request.query_params.get("q") or "").strip())
    limit = max(1, min(50, int(limit)))
    conn = get_conn()
    try:
        try:
            rows = conn.execute(
                "SELECT i.normalized_name n, COUNT(*) c, MAX(p.purchased_at) last_at "
                "FROM purchase_items i JOIN purchases p ON p.id=i.purchase_id "
                + ("WHERE i.normalized_name LIKE ? " if q else "")
                + "GROUP BY i.normalized_name ORDER BY c DESC, last_at DESC LIMIT ?",
                ((f"%{q}%", limit) if q else (limit,))).fetchall()
        except Exception:
            rows = []
        out = []
        for r in rows:
            obs = _observations(conn, r["n"])
            if not obs:
                continue
            last = obs[-1]
            out.append({"normalized_name": r["n"], "name": last["name"],
                        "purchases": len(obs), "unit": last["unit"],
                        "last_unit_price_cents": last["unit_price_cents"],
                        "typical_qty": round(_stats.fmean([o["qty"] for o in obs]), 3),
                        "last_purchase": last["date"]})
    finally:
        conn.close()
    return {"items": out, "query": q}


# ══ 3. BUDGET: PAY PERIOD + ENVELOPES ═════════════════════════════════════════
def _paycheck_rows(conn, limit: int = 24) -> list:
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM paychecks WHERE received_at IS NOT NULL AND received_at <> '' "
            "ORDER BY received_at DESC, id DESC LIMIT ?", (limit,)).fetchall()]
    except Exception:
        return []


def cycle_candidates(conn) -> dict:
    """Suggest pay cycles from the RECORDED paychecks — the owner confirms one.

    Two independent signals, both reported, neither auto-applied:
      declared — the `cycle` he already typed on his paycheck rows
      observed — the median gap between consecutive paycheck dates
    Fewer than 3 paychecks means no observed suggestion at all. Guessing a pay
    cycle from two dates would silently mis-shape every period after it.
    """
    rows = _paycheck_rows(conn)
    declared: dict = {}
    for r in rows:
        c = (r.get("cycle") or "irregular")
        declared[c] = declared.get(c, 0) + 1
    out = {"paychecks": len(rows), "declared": declared,
           "observed": None, "median_gap_days": None,
           "suggested_anchor": rows[0]["received_at"][:10] if rows else None}
    dates = sorted({str(r["received_at"])[:10] for r in rows})
    if len(dates) < MIN_OBSERVATIONS:
        out["status"] = "insufficient_data"
        out["needed"] = MIN_OBSERVATIONS - len(dates)
        out["message"] = (f"{len(dates)} paycheck date(s) recorded — {MIN_OBSERVATIONS} "
                          f"needed before a pay cycle can be observed from your history.")
        return out
    ds = [date.fromisoformat(d) for d in dates]
    gaps = [(ds[i + 1] - ds[i]).days for i in range(len(ds) - 1)]
    med = _stats.median(gaps)
    out["median_gap_days"] = round(med, 1)
    out["status"] = "ok"
    if med <= 9:
        out["observed"] = "weekly"
    elif med <= 17:
        out["observed"] = "biweekly"
    elif med <= 24:
        out["observed"] = "semimonthly"
    elif med <= 45:
        out["observed"] = "monthly"
    else:
        out["observed"] = "irregular"
    return out


def get_config() -> dict:
    cycle = (get_setting("budget_pay_cycle", "") or "").strip().lower()
    if cycle not in BUDGET_CYCLES:
        cycle = ""
    anchor = (get_setting("budget_period_anchor", "") or "").strip()[:10]
    try:
        date.fromisoformat(anchor)
    except (ValueError, TypeError):
        anchor = ""
    return {"pay_cycle": cycle, "anchor": anchor, "configured": bool(cycle and anchor)}


def period_bounds(cycle: str, anchor: str, on: Optional[date] = None):
    """The pay period containing `on`, as (start, end) inclusive.

    Unset / irregular falls back to the calendar month — an honest default that
    projects no income. Month-anchored cycles clamp the anchor day to the month's
    length via bills._add_months, the SAME rule bills already use, so a 31st anchor
    behaves identically on both sides of the app.
    """
    on = on or date.today()
    if not cycle or cycle == "irregular" or not anchor:
        start = on.replace(day=1)
        return start, _add_months(start, 1, 1) - timedelta(days=1)
    try:
        a = date.fromisoformat(anchor)
    except (ValueError, TypeError):
        start = on.replace(day=1)
        return start, _add_months(start, 1, 1) - timedelta(days=1)

    if cycle in ("weekly", "biweekly"):
        n = 7 if cycle == "weekly" else 14
        k = (on - a).days // n            # floor division: works before the anchor too
        start = a + timedelta(days=k * n)
        return start, start + timedelta(days=n - 1)

    if cycle == "semimonthly":
        if on.day <= 15:
            return on.replace(day=1), on.replace(day=15)
        return on.replace(day=16), _add_months(on.replace(day=1), 1, 1) - timedelta(days=1)

    # monthly, anchored on the anchor's day-of-month
    day = a.day
    this = _add_months(on.replace(day=1), 0, day)
    start = this if on >= this else _add_months(this, -1, day)
    return start, _add_months(start, 1, day) - timedelta(days=1)


def _envelopes(conn) -> list:
    try:
        rows = conn.execute(
            "SELECT * FROM budget_envelopes WHERE active=1 ORDER BY sort, id").fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]


def _income(conn, start: date, end: date, cfg: dict) -> dict:
    """Expected income for the period. Recorded first; projected only when the
    owner has CONFIRMED a cycle and there is enough history to average.

    `basis_cents` is what the rest of the engine spends against, and `basis` names
    where it came from — 'recorded', 'projected' or 'none'. When it is None the
    caller must report insufficient_data rather than substituting a zero, because
    a zero income basis silently turns every percent envelope into $0 and makes
    safe-to-spend look like a real (and very wrong) answer.
    """
    try:
        rec = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0), COUNT(*) FROM paychecks "
            "WHERE received_at >= ? AND received_at <= ?",
            (start.isoformat(), end.isoformat())).fetchone()
    except Exception:
        rec = (0, 0)
    recorded, count = int(rec[0] or 0), int(rec[1] or 0)
    out = {"recorded_cents": recorded, "recorded_count": count,
           "projected_cents": None, "basis_cents": None, "basis": "none",
           "projection_note": ""}

    rows = _paycheck_rows(conn, limit=6)
    if cfg.get("configured") and len(rows) >= 2:
        avg = int(round(_stats.fmean([int(r["amount_cents"] or 0) for r in rows])))
        out["projected_cents"] = avg
        out["projection_note"] = (f"average of your last {len(rows)} recorded paychecks "
                                  f"— one per {cfg['pay_cycle']} period")
    elif cfg.get("configured"):
        out["projection_note"] = ("2 recorded paychecks are needed before income can be "
                                  "projected; only what has actually landed is counted.")
    else:
        out["projection_note"] = ("no pay cycle confirmed, so income is NOT projected — "
                                  "only paychecks you actually recorded are counted.")

    if recorded > 0:
        out["basis_cents"], out["basis"] = recorded, "recorded"
    elif out["projected_cents"] is not None:
        out["basis_cents"], out["basis"] = out["projected_cents"], "projected"
    return out


def _committed(conn, start: date, end: date) -> dict:
    """This period's bill obligation — what is still due PLUS what was already paid.

    The due dates come from the EXISTING projection in calendar.py (collect_events),
    never from cycle math re-implemented here, so month-end anchoring stays
    identical on both sides of the app.

    The subtle part is that marking a bill paid ADVANCES its next_due out of the
    period. Counting only the remaining due dates would therefore make a bill
    silently leave the period's committed total the moment it was paid — and
    safe-to-spend would JUMP UP by that amount right after the money left the
    account. Exactly backwards.

    So per bill: obligation = payments recorded in this period, plus any due
    occurrences in this period that those payments do not already account for.
    A bill paid once with one due date contributes its amount ONCE, before and
    after payment. Bills whose amount varies contribute nothing to the total and
    are counted separately — an unknown amount is never quietly treated as $0.
    """
    from .calendar import collect_events
    try:
        # include_budget=False is load-bearing: the budget layer is what is calling
        # here, and letting collect_events re-enter it would recurse (see the note
        # at that call site in calendar.py).
        events = collect_events(start, end, include_projected=True, include_budget=False)
    except Exception as e:              # pragma: no cover — defensive
        logger.warning(f"budget: bill projection unavailable ({e})")
        return {"cents": 0, "count": 0, "unknown_count": 0, "items": [], "degraded": True}

    # What actually left the account for bills inside the period.
    try:
        pay_rows = conn.execute(
            "SELECT p.bill_id AS bid, p.paid_at AS d, p.amount_cents AS amt, "
            "COALESCE(b.name,'Bill') AS name, COALESCE(b.category,'') AS cat "
            "FROM bill_payments p LEFT JOIN bills b ON b.id=p.bill_id "
            "WHERE p.paid_at >= ? AND p.paid_at <= ?",
            (start.isoformat(), end.isoformat())).fetchall()
    except Exception:
        pay_rows = []

    total, count, unknown, items = 0, 0, 0, []
    paid_left: dict = {}
    for r in pay_rows:
        total += int(r["amt"] or 0)
        count += 1
        paid_left[r["bid"]] = paid_left.get(r["bid"], 0) + 1
        items.append({"date": str(r["d"])[:10], "title": r["name"], "amount_cents": r["amt"],
                      "projected": False, "state": "paid", "category": r["cat"]})

    for e in events:
        if e.get("type") != "bill_due":
            continue
        bid = e.get("bill_id")
        if paid_left.get(bid):
            paid_left[bid] -= 1        # this due date is the one that payment settled
            continue
        count += 1
        amt = e.get("amount_cents")
        if amt is None:
            unknown += 1
        else:
            total += int(amt)
        items.append({"date": e["date"], "title": e["title"], "amount_cents": amt,
                      "projected": bool(e.get("projected")), "state": e.get("state"),
                      "category": e.get("category") or ""})
    items.sort(key=lambda i: i["date"])
    return {"cents": total, "count": count, "unknown_count": unknown,
            "items": items, "degraded": False}


def _spend_by_category(conn, start: date, upto: date) -> dict:
    """Non-bill spend per lowercased category, start → upto inclusive.

    `purchases` ONLY. Bill payments live in `bill_payments` and are counted as
    committed outgoings; summing both here is exactly the double count ledger.py
    warns about, so this query can never see them.
    """
    try:
        rows = conn.execute(
            "SELECT LOWER(COALESCE(NULLIF(category,''),'uncategorized')) cat, "
            "SUM(amount_cents) total, COUNT(*) n FROM purchases "
            "WHERE purchased_at >= ? AND purchased_at <= ? GROUP BY cat",
            (start.isoformat(), upto.isoformat())).fetchall()
    except Exception:
        return {}
    return {r["cat"]: {"cents": int(r["total"] or 0), "count": int(r["n"] or 0)} for r in rows}


def compute_period(conn, on: Optional[date] = None, today: Optional[date] = None) -> dict:
    """The whole budget picture for the period containing `on`.

    THE FORMULAS, stated once so they can be checked against the code:

        income_basis   = recorded paychecks in the period, else the projected
                         average when a cycle is confirmed, else None
        committed      = Σ bills due in the period (projection reused from calendar)
        disposable     = income_basis − committed
        allocation(e)  = e.amount_cents                     when kind='fixed'
                       = round(percent/100 × income_basis)  when kind='percent'
        spent(e)       = Σ purchases in [start, today] whose category is e.category
                         ('other' absorbs every category with no envelope of its own,
                          savings excluded — savings is a target, not spending)
        remaining(e)   = allocation(e) − spent(e)
        safe_to_spend  = income_basis − committed − savings_target − spent_total

    safe_to_spend reserves the period's WHOLE bill load whether or not it has been
    paid yet: the income basis covers the whole period, so the whole obligation must
    be held back. Bills are subtracted from `bills`, purchases from `purchases`, and
    the two sets are disjoint — nothing is counted twice.

    With no income basis every derived figure is None and `status` is
    'insufficient_data' with a `needs` list. It never falls back to zero.
    """
    today = today or date.today()
    cfg = get_config()
    start, end = period_bounds(cfg["pay_cycle"], cfg["anchor"], on or today)
    upto = min(today, end)

    income = _income(conn, start, end, cfg)
    committed = _committed(conn, start, end)
    envs = _envelopes(conn)
    spend = _spend_by_category(conn, start, upto)
    spent_total = sum(v["cents"] for v in spend.values())

    basis = income["basis_cents"]
    named = {(e["category"] or "").strip().lower() for e in envs}
    other_cents = sum(v["cents"] for k, v in spend.items()
                      if k not in named and k != SAVINGS_CATEGORY)

    rows, allocated, savings_target = [], 0, None
    for e in envs:
        cat = (e["category"] or "").strip().lower()
        kind = (e["kind"] or "fixed").lower()
        if kind == "percent":
            alloc = int(round((float(e["percent"] or 0) / 100.0) * basis)) if basis is not None else None
        else:
            alloc = int(e["amount_cents"] or 0)
        spent = spend.get(cat, {}).get("cents", 0)
        if cat == "other":
            spent = other_cents        # 'other' is the catch-all for unenveloped spend
        if cat == SAVINGS_CATEGORY:
            spent = 0                  # a savings target is not spending
            savings_target = alloc
        if alloc is not None:
            allocated += alloc
        rows.append({
            "id": e["id"], "category": e["category"], "kind": kind,
            "amount_cents": int(e["amount_cents"] or 0), "percent": float(e["percent"] or 0),
            "allocation_cents": alloc, "spent_cents": spent,
            "remaining_cents": (None if alloc is None else alloc - spent),
            "pct_used": (None if not alloc else round(spent / alloc * 100, 1)),
            "over": bool(alloc is not None and spent > alloc),
            "notes": e["notes"] or "",
            "status": "ok" if alloc is not None else "insufficient_data",
        })

    needs = []
    if basis is None:
        needs.append("record a paycheck, or confirm your pay cycle so income can be projected")
    if not envs:
        needs.append("set up at least one envelope (food, gas, savings…)")
    if not cfg["configured"]:
        needs.append("confirm your pay cycle and its start date")

    disposable = (basis - committed["cents"]) if basis is not None else None
    safe = (basis - committed["cents"] - (savings_target or 0) - spent_total) \
        if basis is not None else None

    days_left = max(0, (end - today).days) if today <= end else 0
    return {
        "status": "ok" if basis is not None else "insufficient_data",
        "needs": needs,
        "today": today.isoformat(),
        "period": {"start": start.isoformat(), "end": end.isoformat(),
                   "cycle": cfg["pay_cycle"] or "calendar-month",
                   "configured": cfg["configured"],
                   "days_total": (end - start).days + 1,
                   "days_left": days_left,
                   "days_elapsed": max(0, (upto - start).days + 1)},
        "income": income,
        "committed": {"cents": committed["cents"], "count": committed["count"],
                      "unknown_count": committed["unknown_count"],
                      "items": committed["items"],
                      "note": ("bills due in this period, projected with the same cycle "
                               "logic the calendar uses"
                               + (f"; {committed['unknown_count']} bill(s) have a variable "
                                  f"amount and are NOT included in the total"
                                  if committed["unknown_count"] else ""))},
        "spend": {"total_cents": spent_total, "by_category": spend,
                  "note": "purchases only — bill payments are counted under committed, never twice"},
        "disposable_cents": disposable,
        "allocated_cents": allocated if basis is not None or all(
            r["kind"] == "fixed" for r in rows) else None,
        "unallocated_cents": (None if disposable is None else disposable - allocated),
        "savings_target_cents": savings_target,
        "safe_to_spend_cents": safe,
        "safe_to_spend_parts": {
            "income_basis_cents": basis, "income_basis": income["basis"],
            "less_committed_cents": committed["cents"],
            "less_savings_target_cents": savings_target or 0,
            "less_spent_cents": spent_total,
        },
        "safe_to_spend_per_day_cents": (
            int(safe / days_left) if (safe is not None and days_left > 0) else None),
        "envelopes": rows,
    }


@router.get("/api/budget/period")
def budget_period(request: Request):
    """The current (or ?on=YYYY-MM-DD) pay period's budget. Never guesses income."""
    on = None
    raw = (request.query_params.get("on") or "").strip()
    if raw:
        try:
            on = date.fromisoformat(raw[:10])
        except ValueError:
            raise HTTPException(400, f"bad date {raw!r} — use YYYY-MM-DD")
    conn = get_conn()
    try:
        out = compute_period(conn, on=on)
        out["cycle_candidates"] = cycle_candidates(conn)
        out["toggles"] = {k: _toggle(k) for k in TOGGLES}
        return out
    finally:
        conn.close()


# ── config + envelopes CRUD ───────────────────────────────────────────────────
class ConfigIn(BaseModel):
    pay_cycle: str
    anchor: Optional[str] = None      # YYYY-MM-DD — the date a period starts


@router.get("/api/budget/config")
def budget_config():
    conn = get_conn()
    try:
        cfg = get_config()
        cfg["candidates"] = cycle_candidates(conn)
        cfg["cycles"] = list(BUDGET_CYCLES)
        cfg["toggles"] = {k: _toggle(k) for k in TOGGLES}
        cfg["default_envelopes"] = list(DEFAULT_ENVELOPES)
        return cfg
    finally:
        conn.close()


@router.post("/api/budget/config")
def set_budget_config(c: ConfigIn):
    cycle = (c.pay_cycle or "").strip().lower()
    if cycle not in BUDGET_CYCLES:
        raise HTTPException(400, f"bad pay_cycle {c.pay_cycle!r} — {'|'.join(BUDGET_CYCLES)}")
    anchor = (c.anchor or "").strip()[:10]
    if anchor:
        try:
            date.fromisoformat(anchor)
        except ValueError:
            raise HTTPException(400, f"bad anchor {c.anchor!r} — use YYYY-MM-DD")
    _set_setting("budget_pay_cycle", cycle)
    _set_setting("budget_period_anchor", anchor)
    return get_config()


@router.post("/api/budget/toggles")
def set_toggle(data: dict = Body(...)):
    """Every gate in this module ships with a switch (house rule). There is no
    switch for 'auto-apply an AI plan' because that path is not implemented."""
    key = str((data or {}).get("key") or "")
    if key not in TOGGLES:
        raise HTTPException(400, f"unknown toggle {key!r} — {'|'.join(TOGGLES)}")
    on = bool((data or {}).get("on"))
    _set_setting(key, "1" if on else "0")
    return {"key": key, "on": on, "toggles": {k: _toggle(k) for k in TOGGLES}}


class EnvelopeIn(BaseModel):
    category: str
    kind: str = "fixed"                 # fixed | percent
    amount_cents: Optional[int] = None
    percent: Optional[float] = None
    active: bool = True
    sort: int = 0
    notes: str = ""


def _valid_envelope(kind: str, amount_cents, percent):
    kind = (kind or "fixed").lower()
    if kind not in ("fixed", "percent"):
        raise HTTPException(400, "kind must be 'fixed' or 'percent'")
    if kind == "fixed":
        if amount_cents in (None, ""):
            raise HTTPException(400, "a fixed envelope needs amount_cents")
        return kind, max(0, int(amount_cents)), 0.0
    try:
        p = float(percent or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "percent must be a number")
    if not (0 < p <= 100):
        raise HTTPException(400, "percent must be between 0 and 100")
    return kind, 0, p


@router.get("/api/budget/envelopes")
def list_envelopes():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM budget_envelopes ORDER BY sort, id").fetchall()
        return {"envelopes": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/api/budget/envelopes")
def create_envelope(e: EnvelopeIn):
    cat = (e.category or "").strip()
    if not cat:
        raise HTTPException(400, "category required")
    kind, amount, pct = _valid_envelope(e.kind, e.amount_cents, e.percent)
    conn = get_conn()
    try:
        dupe = conn.execute("SELECT id FROM budget_envelopes WHERE LOWER(category)=LOWER(?)",
                            (cat,)).fetchone()
        if dupe:
            raise HTTPException(400, f"an envelope for {cat!r} already exists")
        cur = conn.execute(
            "INSERT INTO budget_envelopes (category,kind,amount_cents,percent,active,sort,notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (cat, kind, amount, pct, 1 if e.active else 0, int(e.sort or 0),
             (e.notes or "").strip()))
        conn.commit()
        return dict(conn.execute("SELECT * FROM budget_envelopes WHERE id=?",
                                 (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


@router.patch("/api/budget/envelopes/{eid}")
def update_envelope(eid: int, data: dict = Body(...)):
    allowed = {"category", "kind", "amount_cents", "percent", "active", "sort", "notes"}
    fields = {k: v for k, v in (data or {}).items() if k in allowed}
    if not fields:
        raise HTTPException(400, "nothing to update")
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM budget_envelopes WHERE id=?", (eid,)).fetchone()
        if not row:
            raise HTTPException(404, "envelope not found")
        kind = fields.get("kind", row["kind"])
        amount = fields.get("amount_cents", row["amount_cents"])
        pct = fields.get("percent", row["percent"])
        kind, amount, pct = _valid_envelope(kind, amount if kind == "fixed" else 0,
                                            pct if kind == "percent" else 0)
        fields["kind"], fields["amount_cents"], fields["percent"] = kind, amount, pct
        if "category" in fields:
            fields["category"] = str(fields["category"]).strip()
            if not fields["category"]:
                raise HTTPException(400, "category required")
        if "active" in fields:
            fields["active"] = 1 if fields["active"] else 0
        fields["updated_at"] = date.today().isoformat()
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE budget_envelopes SET {sets} WHERE id=?", (*fields.values(), eid))
        conn.commit()
        return dict(conn.execute("SELECT * FROM budget_envelopes WHERE id=?", (eid,)).fetchone())
    finally:
        conn.close()


@router.delete("/api/budget/envelopes/{eid}")
def delete_envelope(eid: int):
    conn = get_conn()
    try:
        n = conn.execute("DELETE FROM budget_envelopes WHERE id=?", (eid,)).rowcount
        conn.commit()
        if not n:
            raise HTTPException(404, "envelope not found")
        return {"ok": True}
    finally:
        conn.close()


# ══ 4. CALENDAR EVENTS (consumed by calendar.py) ══════════════════════════════
_BUDGET_EVENT_TYPES = ("budget_period", "savings_target", "safe_to_spend",
                       "restock", "grocery_day")


def budget_calendar_events(frm: date, to: date, today: Optional[date] = None) -> list:
    """Budget + prediction markers in the EXISTING calendar event shape.

    Ids are deterministic (derived from the date and the item key, never from a row
    id or the clock) so the ICS UIDs built from them stay stable across calls — a
    UID that changed each refresh would make every subscriber re-notify.

    Everything extrapolated carries projected:true, same as a projected bill due
    date. Emits nothing at all when the underlying data is insufficient: an empty
    calendar is honest, a calendar full of guesses is not.
    """
    today = today or date.today()
    out: list = []
    conn = get_conn()
    try:
        # ── budget period starts + savings targets, walked across the range ──
        cfg = get_config()
        cursor, guard = frm, 0
        seen = set()
        # Only a few periods ahead get a marker. The .ics feed spans 400 days, and
        # walking all of it emitted ~30 identical "period starts — $X" rows, every
        # one of them the SAME projected average pushed a year out. That is not
        # information, it is noise that buries the real events in a subscribed
        # calendar — and the further out it goes, the less the projection means.
        while cursor <= to and guard < _MAX_PERIOD_MARKERS:
            guard += 1
            try:
                snap = compute_period(conn, on=cursor, today=today)
            except Exception as e:      # pragma: no cover — defensive
                logger.warning(f"budget: period snapshot failed ({e})")
                break
            start = date.fromisoformat(snap["period"]["start"])
            end = date.fromisoformat(snap["period"]["end"])
            if start.isoformat() in seen:
                break
            seen.add(start.isoformat())
            future = start > today
            basis = snap["income"]["basis_cents"]
            if frm <= start <= to and basis is not None:
                out.append({
                    "id": f"budget-period-{start.isoformat()}",
                    "type": "budget_period", "date": start.isoformat(),
                    "title": "Budget period starts",
                    "amount_cents": basis, "category": "budget", "direction": "in",
                    # projected when the period has not begun, or when the income
                    # figure itself is a projection rather than a recorded paycheck
                    "projected": bool(future or snap["income"]["basis"] == "projected"),
                    "state": "planned",
                    "notes": (f"Income basis {snap['income']['basis']}; "
                              f"{snap['committed']['count']} bill(s) due this period."),
                })
                st = snap["savings_target_cents"]
                if st:
                    out.append({
                        "id": f"budget-savings-{start.isoformat()}",
                        "type": "savings_target", "date": start.isoformat(),
                        "title": "Savings target",
                        "amount_cents": st, "category": SAVINGS_CATEGORY, "direction": "in",
                        "projected": bool(future or snap["income"]["basis"] == "projected"),
                        "state": "planned",
                        "notes": "Set aside before spending — from your savings envelope.",
                    })
            # safe-to-spend marker sits on today, inside the live period only
            if start <= today <= end and frm <= today <= to \
                    and snap["safe_to_spend_cents"] is not None:
                out.append({
                    "id": f"budget-safe-{today.isoformat()}",
                    "type": "safe_to_spend", "date": today.isoformat(),
                    "title": "Safe to spend", "amount_cents": snap["safe_to_spend_cents"],
                    "category": "budget", "direction": "out",
                    "projected": bool(snap["income"]["basis"] == "projected"),
                    "state": "planned",
                    "notes": (f"Income {snap['income']['basis']} minus bills due, savings "
                              f"target and what you have already spent this period."),
                })
            cursor = end + timedelta(days=1)

        # ── predicted restocks + the suggested grocery day (toggleable) ──
        if _toggle("budget_calendar_predictions"):
            restocks = []
            for s in all_item_stats(conn, today=today):
                if s["status"] != "ok" or not s.get("predicted_next_date"):
                    continue            # sparse items are never given a date
                d = date.fromisoformat(s["predicted_next_date"])
                if not (frm <= d <= to):
                    continue
                est = (int(round(s["avg_unit_price_cents"] * s["avg_qty"]))
                       if s.get("avg_unit_price_cents") and s.get("avg_qty") else None)
                restocks.append((d, s))
                out.append({
                    "id": f"budget-restock-{s['normalized_name'].replace(' ', '_')}-{d.isoformat()}",
                    "type": "restock", "date": d.isoformat(),
                    "title": f"{s['display_name']} likely out ~",
                    "amount_cents": est, "category": s.get("category") or FOOD_CATEGORY,
                    "direction": "out",
                    "projected": True,      # always — this is an extrapolation
                    "state": "predicted",
                    "notes": (f"You buy this about every {s['avg_interval_days']} days "
                              f"({s['observations']} purchases, {s['confidence']} confidence). "
                              f"Window {s['predicted_earliest']} → {s['predicted_latest']}."),
                })
            # Suggested grocery day: the day before the densest cluster of restocks.
            if restocks:
                buckets: dict = {}
                for d, _s in restocks:
                    buckets[d] = buckets.get(d, 0) + 1
                # cluster = a date and its next 2 days
                best_day, best_n = None, 0
                for d in sorted(buckets):
                    n = sum(buckets.get(d + timedelta(days=k), 0) for k in (0, 1, 2))
                    if n > best_n:
                        best_day, best_n = d, n
                if best_day and best_n >= 2:
                    shop = best_day - timedelta(days=1)
                    if frm <= shop <= to:
                        out.append({
                            "id": f"budget-groceryday-{shop.isoformat()}",
                            "type": "grocery_day", "date": shop.isoformat(),
                            "title": "Suggested grocery day",
                            "amount_cents": None, "category": FOOD_CATEGORY, "direction": "out",
                            "projected": True,
                            "state": "suggested",
                            "notes": f"{best_n} item(s) are predicted to run out in the "
                                     f"following 3 days.",
                        })
    finally:
        conn.close()
    return out


# ══ 5. THE AI PLANNER ═════════════════════════════════════════════════════════
GROCERY_PLAN_PROMPT = (
    "You are a careful household grocery planner. You are given (a) the REMAINING food "
    "budget for the current pay period, in dollars, and (b) a CATALOG of items the "
    "household has actually bought before, each with how often they buy it, how much they "
    "buy, and the last unit price they really paid.\n\n"
    "Build a shopping list for the next trip.\n\n"
    "HARD RULES — breaking any of these makes your answer useless:\n"
    "1. Use ONLY items that appear in the CATALOG, spelled exactly as the catalog spells "
    "them. Never add an item that is not listed, however sensible it seems.\n"
    "2. Do NOT invent, guess or state prices. Prices are computed from the household's own "
    "receipts, not by you. Omit money entirely.\n"
    "3. Prefer items whose predicted run-out date is soonest.\n"
    "4. Keep the list within the remaining budget using the quantities and prices given.\n"
    "5. Quantities must be realistic multiples of how much they normally buy.\n\n"
    "Return STRICT JSON and nothing else — no markdown, no commentary:\n"
    '{"items": [{"name": "<exact catalog name>", "qty": <number>, '
    '"why": "<max 12 words, e.g. runs out in 2 days>"}], '
    '"observations": ["<short, specific note about their spending, max 20 words>"]}\n'
    "Up to 20 items. If the catalog is empty, return an empty items array — do not "
    "invent a starter list."
)


def _plan_prompt() -> str:
    try:
        return get_prompt("budget_grocery_plan") or GROCERY_PLAN_PROMPT
    except Exception:
        return GROCERY_PLAN_PROMPT


def _parse_plan_json(raw: str) -> dict:
    """Defensive parse of the model reply, mirroring _base._parse_missions_json."""
    raw = _re.sub(r"<think>.*?</think>", "", raw or "", flags=_re.DOTALL).strip()
    raw = _re.sub(r"^```(?:json)?\s*", "", raw)
    raw = _re.sub(r"\s*```$", "", raw).strip()
    data = None
    try:
        data = _json.loads(raw)
    except Exception:
        i, j = raw.find("{"), raw.rfind("}")
        if i != -1 and j > i:
            try:
                data = _json.loads(raw[i:j + 1])
            except Exception:
                data = None
    if isinstance(data, list):
        data = {"items": data}
    if not isinstance(data, dict):
        return {"items": [], "observations": []}
    items = data.get("items")
    obs = data.get("observations")
    return {"items": items if isinstance(items, list) else [],
            "observations": [str(o)[:200] for o in obs][:8] if isinstance(obs, list) else []}


def validate_plan_items(raw_items: list, catalog: list) -> tuple:
    """Check the model's list against the household's OWN item history.

    This is the anti-hallucination gate, and it is deliberately strict:

      • an item whose normalized name is not in the catalog is DROPPED, with the
        reason recorded — the model does not get to add groceries to the list
      • every price is RECOMPUTED from our recorded unit prices; any price the
        model emitted is discarded unread. An item we have never priced comes back
        with est_cents None and flagged, never with a plausible number
      • quantities are clamped to at most 4× the household's typical qty, so a
        stray "qty": 99 cannot blow up an estimate

    Returns (accepted, rejected). Both are plain dicts, safe to store as JSON.
    """
    by_norm = {c["normalized_name"]: c for c in catalog}
    accepted, rejected, seen = [], [], set()
    for it in (raw_items or [])[:_MAX_PLAN_LINES]:
        if not isinstance(it, dict):
            rejected.append({"name": str(it)[:80], "reason": "malformed"})
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            rejected.append({"name": "", "reason": "no name"})
            continue
        norm = normalize_item_name(name)
        known = by_norm.get(norm)
        if not known:
            rejected.append({"name": name[:120], "normalized_name": norm,
                             "reason": "unknown_item",
                             "detail": "not in your purchase history — dropped, not guessed"})
            continue
        if norm in seen:
            rejected.append({"name": name[:120], "reason": "duplicate"})
            continue
        seen.add(norm)
        typical = float(known.get("typical_qty") or 1) or 1.0
        try:
            qty = float(it.get("qty") or typical)
        except (TypeError, ValueError):
            qty = typical
        if qty <= 0:
            qty = typical
        qty = min(qty, typical * 4)
        unit_price = known.get("unit_price_cents")
        est = int(round(qty * unit_price)) if unit_price is not None else None
        accepted.append({
            "name": known.get("name") or name,
            "normalized_name": norm,
            "qty": round(qty, 3),
            "unit": known.get("unit") or "",
            # OUR price, from OUR receipts. The model's is never read.
            "unit_price_cents": unit_price,
            "est_cents": est,
            "price_source": ("your last recorded unit price" if unit_price is not None
                             else "no unit price recorded yet"),
            "flags": ([] if unit_price is not None else ["no_price"]),
            "why": str(it.get("why") or "")[:120],
            "predicted_next_date": known.get("predicted_next_date"),
            "avg_interval_days": known.get("avg_interval_days"),
        })
    return accepted, rejected


def plan_catalog(conn, today: Optional[date] = None) -> list:
    """The ONLY vocabulary the planner may use: items with a real cadence.

    Items below MIN_OBSERVATIONS are excluded — putting an item the owner bought
    once in front of the model invites it to build a list out of noise.
    """
    out = []
    for s in all_item_stats(conn, today=today):
        if s["status"] != "ok":
            continue
        out.append({
            "normalized_name": s["normalized_name"], "name": s["display_name"],
            "unit": s.get("unit") or "", "typical_qty": s.get("avg_qty") or 1,
            "unit_price_cents": (s.get("last_unit_price_cents")
                                 if s.get("last_unit_price_cents") is not None
                                 else s.get("avg_unit_price_cents")),
            "avg_interval_days": s.get("avg_interval_days"),
            "days_until_next": s.get("days_until_next"),
            "predicted_next_date": s.get("predicted_next_date"),
            "confidence": s.get("confidence"),
            "price_trend": (s.get("price_trend") or {}).get("direction"),
            "price_change_pct": (s.get("price_trend") or {}).get("change_pct"),
        })
    out.sort(key=lambda c: (c["days_until_next"] if c["days_until_next"] is not None else 999))
    return out


def computed_observations(snap: dict, catalog: list) -> list:
    """FACTS we derived ourselves, never the model's. These are always shown, even
    when the LLM is unavailable — they are the part of the advice that is provably
    traceable to recorded rows."""
    obs = []
    for env in snap.get("envelopes") or []:
        if env.get("over"):
            obs.append({"kind": "envelope_over",
                        "text": f"{env['category']} is over its envelope for this period.",
                        "category": env["category"]})
        elif env.get("pct_used") is not None and snap["period"]["days_total"]:
            pace = snap["period"]["days_elapsed"] / snap["period"]["days_total"] * 100
            if env["pct_used"] > pace + 20:
                obs.append({"kind": "envelope_pace",
                            "text": (f"{env['category']} is {round(env['pct_used'])}% spent "
                                     f"with {round(pace)}% of the period gone."),
                            "category": env["category"]})
    for c in catalog:
        if c.get("price_trend") == "rising" and (c.get("price_change_pct") or 0) >= 5:
            obs.append({"kind": "price_rising",
                        "text": (f"{c['name']} unit price is up "
                                 f"{c['price_change_pct']}% versus your earlier purchases."),
                        "item": c["normalized_name"]})
    if snap.get("committed", {}).get("unknown_count"):
        obs.append({"kind": "variable_bills",
                    "text": (f"{snap['committed']['unknown_count']} bill(s) have a variable "
                             f"amount, so committed outgoings are understated.")})
    return obs[:12]


@router.post("/api/budget/plan")
def generate_plan():
    """Draft a grocery list with the LLM, grounded in the real numbers.

    The model call goes through orch.submit_llm like every other model call in this
    app — the orchestrator owns model loading and the queue, so nothing here ever
    talks to LM Studio directly. Returns a task_id and the plan row id immediately;
    the row fills in when the queued work runs.

    The result is ADVISORY. It lands at status 'draft' and changes no budget, no
    envelope and no purchase until the owner accepts it — and turning an accepted
    plan into a purchase is a separate action after that.
    """
    if not _toggle("budget_planner_enabled"):
        raise HTTPException(400, "The AI grocery planner is turned off "
                                 "(Budget → toggles → budget_planner_enabled).")
    conn = get_conn()
    try:
        snap = compute_period(conn)
        catalog = plan_catalog(conn)
        food_env = next((e for e in snap["envelopes"]
                         if (e["category"] or "").lower() == FOOD_CATEGORY), None)
        remaining = food_env["remaining_cents"] if food_env else None
        if not catalog:
            raise HTTPException(400,
                                f"No item has {MIN_OBSERVATIONS} recorded purchases yet, so "
                                f"there is nothing to plan from. Log a few shopping trips "
                                f"with line items first.")
        cur = conn.execute(
            "INSERT INTO budget_plans (period_start,period_end,envelope_cents,status) "
            "VALUES (?,?,?,'generating')",
            (snap["period"]["start"], snap["period"]["end"], remaining))
        plan_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    facts = computed_observations(snap, catalog)
    budget_line = (f"REMAINING FOOD BUDGET THIS PERIOD: ${remaining / 100:.2f}"
                   if remaining is not None else
                   "REMAINING FOOD BUDGET THIS PERIOD: not known — no food envelope is set "
                   "up, so keep the list to what is predicted to run out.")
    cat_lines = "\n".join(
        f"- {c['name']}"
        + (f" (unit: {c['unit']})" if c["unit"] else "")
        + f" | they buy about {c['typical_qty']} every {c['avg_interval_days']} days"
        + (f" | last unit price ${c['unit_price_cents'] / 100:.2f}"
           if c["unit_price_cents"] is not None else " | no price recorded")
        + (f" | predicted to run out in {c['days_until_next']} days"
           if c["days_until_next"] is not None else "")
        for c in catalog[:60])
    user = (f"{budget_line}\n\nPERIOD: {snap['period']['start']} to {snap['period']['end']} "
            f"({snap['period']['days_left']} days left)\n\n"
            f"CATALOG ({len(catalog)} items they actually buy):\n{cat_lines}")

    def _work():
        c = get_conn()
        try:
            try:
                raw = _call_lmstudio(_plan_prompt(), user, max_tokens=1600, json_mode=True)
            except Exception as e:
                c.execute("UPDATE budget_plans SET status='failed', error=?, "
                          "updated_at=datetime('now') WHERE id=?", (str(e)[:400], plan_id))
                c.commit()
                raise
            parsed = _parse_plan_json(raw)
            accepted, rejected = validate_plan_items(parsed["items"], catalog)
            total = sum(a["est_cents"] or 0 for a in accepted)
            unpriced = sum(1 for a in accepted if a["est_cents"] is None)
            notes = [{"kind": "llm", "text": o, "advisory": True}
                     for o in parsed["observations"]]
            facts_out = list(facts)
            if remaining is not None and total > remaining:
                facts_out.insert(0, {
                    "kind": "over_envelope",
                    "text": (f"This list estimates over the food envelope's remaining "
                             f"${remaining / 100:.2f}. Nothing was trimmed automatically — "
                             f"edit the lines you do not need.")})
            if unpriced:
                facts_out.append({
                    "kind": "unpriced",
                    "text": (f"{unpriced} line(s) have no recorded unit price, so they are "
                             f"NOT in the estimated total. The real total will be higher.")})
            if rejected:
                facts_out.append({
                    "kind": "rejected",
                    "text": (f"{len(rejected)} suggested line(s) were dropped because they "
                             f"are not in your purchase history.")})
            c.execute(
                "UPDATE budget_plans SET status='draft', items=?, rejected_items=?, "
                "est_total_cents=?, observations=?, llm_notes=?, updated_at=datetime('now') "
                "WHERE id=?",
                (_json.dumps(accepted), _json.dumps(rejected), total,
                 _json.dumps(facts_out), _json.dumps(notes), plan_id))
            c.commit()
        finally:
            c.close()
        return {"plan_id": plan_id, "items": len(accepted), "rejected": len(rejected),
                "est_total_cents": total}

    # Rides the unified queue exactly like every other model call in the app:
    #   • task=  → the prompt-registry key, which is ALSO what model_registry.for_task
    #             keys the per-feature model picker off (Settings → Prompts → model)
    #   • source= → explicit attribution for the persistent queue history, so this
    #             lands under "money" with the rest of the finance work rather than
    #             under a derived first-token guess ("grocery")
    tid = orch.submit_llm(_work, desc=f"Grocery plan: {len(catalog)} known items",
                          priority=2, task="budget_grocery_plan", source="money")
    conn = get_conn()
    try:
        conn.execute("UPDATE budget_plans SET task_id=? WHERE id=?", (tid, plan_id))
        conn.commit()
    finally:
        conn.close()
    return {"task_id": tid, "plan_id": plan_id, "catalog_items": len(catalog),
            "food_remaining_cents": remaining}


def _plan_row(r) -> dict:
    d = dict(r)
    for k in ("items", "rejected_items", "observations", "llm_notes"):
        try:
            d[k] = _json.loads(d.get(k) or "[]")
        except ValueError:
            d[k] = []
    return d


def _get_plan(conn, pid: int):
    row = conn.execute("SELECT * FROM budget_plans WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "plan not found")
    return row


@router.get("/api/budget/plans")
def list_plans(limit: int = 20):
    limit = max(1, min(100, int(limit)))
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM budget_plans ORDER BY id DESC LIMIT ?",
                            (limit,)).fetchall()
        return {"plans": [_plan_row(r) for r in rows],
                "toggles": {k: _toggle(k) for k in TOGGLES}}
    finally:
        conn.close()


@router.get("/api/budget/plans/{pid}")
def get_plan(pid: int):
    conn = get_conn()
    try:
        return _plan_row(_get_plan(conn, pid))
    finally:
        conn.close()


@router.patch("/api/budget/plans/{pid}")
def edit_plan(pid: int, data: dict = Body(...)):
    """Edit the draft's lines. Quantities are re-priced from OUR recorded prices —
    an edit can change what and how much, never what something costs."""
    items = (data or {}).get("items")
    if not isinstance(items, list):
        raise HTTPException(400, "items list required")
    conn = get_conn()
    try:
        row = _get_plan(conn, pid)
        if row["status"] in ("accepted", "rejected"):
            raise HTTPException(400, f"this plan is already {row['status']}")
        catalog = plan_catalog(conn)
        accepted, rejected = validate_plan_items(items, catalog)
        total = sum(a["est_cents"] or 0 for a in accepted)
        conn.execute("UPDATE budget_plans SET items=?, rejected_items=?, est_total_cents=?, "
                     "updated_at=datetime('now') WHERE id=?",
                     (_json.dumps(accepted), _json.dumps(rejected), total, pid))
        conn.commit()
        return _plan_row(_get_plan(conn, pid))
    finally:
        conn.close()


@router.post("/api/budget/plans/{pid}/accept")
def accept_plan(pid: int):
    """Owner accepts the list. This changes NO budget and creates NO purchase — it
    only marks the draft as one he intends to shop from."""
    conn = get_conn()
    try:
        row = _get_plan(conn, pid)
        if row["status"] not in ("draft", "accepted"):
            raise HTTPException(400, f"cannot accept a plan that is {row['status']}")
        conn.execute("UPDATE budget_plans SET status='accepted', updated_at=datetime('now') "
                     "WHERE id=?", (pid,))
        conn.commit()
        return _plan_row(_get_plan(conn, pid))
    finally:
        conn.close()


@router.post("/api/budget/plans/{pid}/reject")
def reject_plan(pid: int):
    conn = get_conn()
    try:
        _get_plan(conn, pid)
        conn.execute("UPDATE budget_plans SET status='rejected', updated_at=datetime('now') "
                     "WHERE id=?", (pid,))
        conn.commit()
        return _plan_row(_get_plan(conn, pid))
    finally:
        conn.close()


class ToPurchaseIn(BaseModel):
    merchant: str
    purchased_at: Optional[str] = None
    category: str = FOOD_CATEGORY
    method: str = ""


@router.post("/api/budget/plans/{pid}/purchase")
def plan_to_purchase(pid: int, p: ToPurchaseIn):
    """Pre-fill a real purchase from an ACCEPTED plan — an explicit owner action.

    The amounts written are the ESTIMATES from his own price history; he is expected
    to correct them against the receipt. Nothing about this is automatic, and a plan
    can only reach here after he accepted it.
    """
    merchant = (p.merchant or "").strip()
    if not merchant:
        raise HTTPException(400, "merchant required")
    when = (p.purchased_at or date.today().isoformat())[:10]
    try:
        date.fromisoformat(when)
    except ValueError:
        raise HTTPException(400, f"bad date {p.purchased_at!r} — use YYYY-MM-DD")
    conn = get_conn()
    try:
        row = _get_plan(conn, pid)
        if row["status"] != "accepted":
            raise HTTPException(400, "accept the plan first — drafts are not turned into purchases")
        if row["purchase_id"]:
            raise HTTPException(400, "this plan was already turned into a purchase")
        plan = _plan_row(row)
        lines = clean_items([{ "name": i["name"], "qty": i["qty"], "unit": i.get("unit") or "",
                               "unit_price_cents": i.get("unit_price_cents"),
                               "line_total_cents": i.get("est_cents"),
                               "category": p.category}
                             for i in plan["items"] if i.get("est_cents") is not None],
                            p.category)
        if not lines:
            raise HTTPException(400, "no priced lines on this plan to pre-fill a purchase with")
        total = items_total_cents(lines)
        cur = conn.execute(
            "INSERT INTO purchases (purchased_at,merchant,amount_cents,category,method,notes,extra) "
            "VALUES (?,?,?,?,?,?,'{}')",
            (when, merchant, total, p.category, (p.method or "").strip(),
             f"Pre-filled from grocery plan #{pid} — check against your receipt."))
        purchase_id = cur.lastrowid
        replace_purchase_items(conn, purchase_id, lines)
        conn.execute("UPDATE budget_plans SET purchase_id=?, updated_at=datetime('now') "
                     "WHERE id=?", (purchase_id, pid))
        conn.commit()
        return {"ok": True, "purchase_id": purchase_id, "amount_cents": total,
                "lines": len(lines),
                "note": "Estimated from your own recorded prices — edit it to match the receipt."}
    finally:
        conn.close()


# ══ 6. SAMPLE DATA — seed a playground, purge it exactly ══════════════════════
# The owner wanted to see the budget working before he has months of his own
# history in it. That means writing rows into a database that also holds his REAL
# money records, which makes the purge the dangerous half of this feature, not the
# seed.
#
# The contract, and the reason it is safe:
#   • every seeded row carries extra["sample"] == SAMPLE_TAG. No exceptions.
#   • the purge deletes ONLY rows carrying that exact tag, matched on the parsed
#     JSON — never "recent rows", never "rows that look like samples", never a
#     date range. A row he typed himself has no tag and is therefore unreachable
#     by this code path, which is what makes it safe to run against live data.
#   • the purge reports exactly what it removed, per table.
#   • nothing seeds itself. There is no cadence, no startup hook, no default-on
#     toggle — sample data exists only if he presses the button.
SAMPLE_TAG = "budget_sample_data"
_SAMPLE_TABLES = ("purchases", "paychecks", "bills")


def _tagged_extra(**extra) -> str:
    return _json.dumps({"sample": SAMPLE_TAG, **{k: str(v) for k, v in extra.items()}})


def _sample_ids(conn, table: str) -> list:
    """Ids of the tagged rows in one table. Parsed JSON, not a LIKE over text —
    a substring match could in principle be satisfied by a note the owner typed."""
    try:
        rows = conn.execute(f"SELECT id, extra FROM {table}").fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        try:
            if (_json.loads(r["extra"] or "{}") or {}).get("sample") == SAMPLE_TAG:
                out.append(r["id"])
        except (ValueError, TypeError):
            continue          # unparseable extra = not ours, leave it alone
    return out


@router.get("/api/budget/sample")
def sample_status():
    conn = get_conn()
    try:
        counts = {t: len(_sample_ids(conn, t)) for t in _SAMPLE_TABLES}
        env = 0
        try:
            env = conn.execute("SELECT COUNT(*) FROM budget_envelopes WHERE notes=?",
                               (SAMPLE_TAG,)).fetchone()[0]
        except Exception:
            pass
        counts["budget_envelopes"] = env
        return {"tag": SAMPLE_TAG, "counts": counts,
                "present": any(counts.values()),
                "note": ("Sample rows are tagged and can be removed exactly. Your own "
                         "records are never touched by the purge.")}
    finally:
        conn.close()


@router.post("/api/budget/sample/seed")
def sample_seed(data: dict = Body(default={})):
    """Insert a clearly-tagged demo history so the budget has something to show.

    Amounts and dates are generated relative to today from a fixed, boring pattern
    — this is illustrative sample data, not a claim about anything the owner buys.
    """
    months = max(1, min(6, int((data or {}).get("months") or 3)))
    conn = get_conn()
    try:
        if _sample_ids(conn, "purchases"):
            raise HTTPException(400, "sample data is already loaded — purge it first")
        today = date.today()
        start = today - timedelta(days=months * 30)
        made = {"paychecks": 0, "purchases": 0, "purchase_items": 0, "bills": 0,
                "budget_envelopes": 0}

        # Income: a steady biweekly paycheck.
        d = start
        while d <= today:
            conn.execute(
                "INSERT INTO paychecks (source,amount_cents,received_at,cycle,notes,extra) "
                "VALUES (?,?,?,?,?,?)",
                ("Sample Employer", 185000, d.isoformat(), "biweekly",
                 "sample data", _tagged_extra()))
            made["paychecks"] += 1
            d += timedelta(days=14)

        # Recurring obligations.
        for name, cents, day, cat in (("Sample Power", 14200, 5, "utilities"),
                                      ("Sample Internet", 7500, 12, "utilities"),
                                      ("Sample Phone", 5500, 20, "utilities")):
            nd = _add_months(today.replace(day=1), 0, day)
            if nd < today:
                nd = _add_months(nd, 1, day)
            conn.execute(
                "INSERT INTO bills (name,category,amount_cents,cycle,due_day,next_due,extra) "
                "VALUES (?,?,?,'monthly',?,?,?)",
                (name, cat, cents, day, nd.isoformat(), _tagged_extra()))
            made["bills"] += 1

        # Envelopes (only if he has none — never overwrite a real budget).
        if not conn.execute("SELECT COUNT(*) FROM budget_envelopes").fetchone()[0]:
            for cat, kind, amt, pct, srt in (("food", "fixed", 40000, 0, 1),
                                             ("gas", "fixed", 16000, 0, 2),
                                             ("savings", "percent", 0, 10.0, 3),
                                             ("other", "fixed", 12000, 0, 4)):
                conn.execute(
                    "INSERT INTO budget_envelopes (category,kind,amount_cents,percent,sort,notes) "
                    "VALUES (?,?,?,?,?,?)", (cat, kind, amt, pct, srt, SAMPLE_TAG))
                made["budget_envelopes"] += 1

        def _trip(when: date, merchant: str, category: str, lines: list):
            items = clean_items(lines, category)
            total = items_total_cents(items)
            cur = conn.execute(
                "INSERT INTO purchases (purchased_at,merchant,amount_cents,category,method,"
                "notes,extra) VALUES (?,?,?,?,'card','sample data',?)",
                (when.isoformat(), merchant, total, category, _tagged_extra()))
            replace_purchase_items(conn, cur.lastrowid, items)
            made["purchases"] += 1
            made["purchase_items"] += len(items)

        # Milk: a gallon roughly every 3 days, with a mild price climb over time —
        # the "am I really going through that much?" case.
        n, d = 0, start
        while d <= today:
            weeks = (d - start).days / 30.0
            milk_price = 389 + int(round(weeks * 12))       # creeps up month over month
            lines = [{"name": "Milk 1 gal", "qty": 1, "unit": "gal",
                      "unit_price_cents": milk_price}]
            if n % 2 == 0:
                lines.append({"name": "Large Eggs 12 ct", "qty": 1, "unit": "ct",
                              "unit_price_cents": 329})
            if n % 3 == 0:
                lines.append({"name": "Dr Pepper 12 pk", "qty": 2, "unit": "pk",
                              "unit_price_cents": 749})
            if n % 4 == 0:
                lines.append({"name": "Bread", "qty": 1, "unit": "", "unit_price_cents": 279})
            _trip(d, "Sample Grocery", "food", lines)
            n += 1
            d += timedelta(days=3)

        # Gas: a fill-up about once a week.
        d = start + timedelta(days=2)
        while d <= today:
            _trip(d, "Sample Fuel", "gas",
                  [{"name": "Unleaded", "qty": 12, "unit": "gal", "unit_price_cents": 289}])
            d += timedelta(days=7)

        # Two deliberately THIN items so the insufficient-data path is visible in
        # the UI rather than only in a test.
        _trip(today - timedelta(days=9), "Sample Grocery", "food",
              [{"name": "Coffee 12 oz", "qty": 1, "unit": "oz", "unit_price_cents": 899}])
        _trip(today - timedelta(days=4), "Sample Grocery", "food",
              [{"name": "Coffee 12 oz", "qty": 1, "unit": "oz", "unit_price_cents": 949},
               {"name": "Paper Towels 6 ct", "qty": 1, "unit": "ct", "unit_price_cents": 1199}])
        conn.commit()
        return {"ok": True, "tag": SAMPLE_TAG, "seeded": made,
                "note": ("Every row above is tagged as sample data and can be removed "
                         "exactly, without touching anything you entered yourself.")}
    finally:
        conn.close()


@router.post("/api/budget/sample/purge")
def sample_purge():
    """Remove ONLY the tagged sample rows. Safe against a live database.

    A row with no `sample` tag is unreachable from here — the delete is driven by
    the id list gathered from the parsed tag, never by a WHERE clause over dates,
    merchants or notes.
    """
    conn = get_conn()
    try:
        removed = {}
        pids = _sample_ids(conn, "purchases")
        if pids:
            qm = ",".join("?" * len(pids))
            try:
                conn.execute(f"DELETE FROM purchase_items WHERE purchase_id IN ({qm})", pids)
            except Exception:
                pass
            conn.execute(f"DELETE FROM purchases WHERE id IN ({qm})", pids)
        removed["purchases"] = len(pids)

        bids = _sample_ids(conn, "bills")
        if bids:
            qm = ",".join("?" * len(bids))
            # Payments logged against a sample bill are sample data too.
            conn.execute(f"DELETE FROM bill_payments WHERE bill_id IN ({qm})", bids)
            conn.execute(f"DELETE FROM bills WHERE id IN ({qm})", bids)
        removed["bills"] = len(bids)

        chids = _sample_ids(conn, "paychecks")
        if chids:
            qm = ",".join("?" * len(chids))
            conn.execute(f"DELETE FROM paychecks WHERE id IN ({qm})", chids)
        removed["paychecks"] = len(chids)

        try:
            removed["budget_envelopes"] = conn.execute(
                "DELETE FROM budget_envelopes WHERE notes=?", (SAMPLE_TAG,)).rowcount
        except Exception:
            removed["budget_envelopes"] = 0
        conn.commit()
        return {"ok": True, "removed": removed, "total": sum(removed.values()),
                "note": "Only rows tagged as sample data were removed."}
    finally:
        conn.close()
