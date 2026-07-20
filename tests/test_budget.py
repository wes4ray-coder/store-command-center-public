"""🧮 budget + grocery planner (routers/money/budget.py — /api/budget/*).

This module reasons about the owner's REAL money, so the tests are weighted toward
the ways it could be wrong QUIETLY:

  • the item-name normalizer — the join key everything else depends on. A wrong
    merge silently corrupts every consumption number downstream.
  • the insufficient-data floor — fewer than MIN_OBSERVATIONS purchases must
    produce NO prediction at all, not a soft one. Asserted as `is None`, because
    a missing key that a caller reads as 0 is the exact failure mode we are
    guarding against.
  • envelope + safe-to-spend arithmetic across a real pay period.
  • no double counting between bills and purchases (the invariant ledger.py
    documents and the budget engine has to preserve).
  • the calendar's new event types: flagged `projected`, and ICS UIDs stable
    across calls so subscribers do not re-notify on every refresh.
  • the planner: hallucinated items are DROPPED, model-supplied prices are never
    used, and the model call rides orch.submit_llm rather than LM Studio directly.
  • the sample-data purge: it must be safe to run against a database holding real
    records — an untagged row is unreachable from it.

Sibling of tests/test_bills.py, tests/test_money_ledger.py and tests/test_calendar.py.
"""
from datetime import date, timedelta

import db
import routers.money.budget as bg
from routers.money.budget import (normalize_item_name, consumption_stats,
                                  validate_plan_items, period_bounds,
                                  compute_period, MIN_OBSERVATIONS)


# ── helpers ───────────────────────────────────────────────────────────────────
def _clear():
    conn = db.get_conn()
    for t in ("purchase_items", "purchases", "paychecks", "bill_payments", "bills",
              "budget_envelopes", "budget_plans"):
        try:
            conn.execute(f"DELETE FROM {t}")
        except Exception:
            pass
    conn.execute("DELETE FROM settings WHERE key LIKE 'budget_%'")
    conn.commit()
    conn.close()


def _iso(d: date) -> str:
    return d.isoformat()


def _trip(client, when, lines, merchant="Corner Store", category="food", **kw):
    body = {"merchant": merchant, "purchased_at": when, "category": category,
            "items": lines, **kw}
    r = client.post("/api/ledger/purchases", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _milk(qty=1, price=400):
    return [{"name": "Milk 1 gal", "qty": qty, "unit": "gal", "unit_price_cents": price}]


# ══ 1. THE NORMALIZER ════════════════════════════════════════════════════════
def test_normalizer_collapses_size_and_unit_wording():
    # The brief's own example: these are the same item to a human, and must be
    # the same key to the consumption model.
    assert normalize_item_name("Milk 1 gal") == "milk"
    assert normalize_item_name("milk gallon") == "milk"
    assert normalize_item_name("MILK") == "milk"
    assert normalize_item_name("  Milk, 2%  ") == "milk"
    assert normalize_item_name("Milk (1 gallon)") == "milk"


def test_normalizer_strips_counts_packs_and_filler():
    assert normalize_item_name("Large Eggs 12 ct") == "egg"
    assert normalize_item_name("eggs") == "egg"
    assert normalize_item_name("Organic Large Eggs") == "egg"
    assert normalize_item_name("Dr Pepper 12pk") == "dr pepper"
    assert normalize_item_name("Dr Pepper 12 pack") == "dr pepper"
    assert normalize_item_name("Paper Towels 6 ct") == "paper towel"


def test_normalizer_keeps_distinct_items_apart():
    # Over-merging is the expensive failure: it would average two different
    # products' prices and cadences together.
    assert normalize_item_name("whole milk") != normalize_item_name("almond milk")
    assert normalize_item_name("chicken breast") != normalize_item_name("chicken thigh")
    assert normalize_item_name("Glass Cleaner") == "glass cleaner"   # -ss not stripped


def test_normalizer_never_empties_a_real_name():
    # A name made ENTIRELY of packaging words must still get a stable key rather
    # than collapsing to "" and merging with every other such item.
    assert normalize_item_name("12 pack") != ""
    assert normalize_item_name("") == ""
    assert normalize_item_name("   ") == ""


def test_normalizer_is_deterministic():
    for s in ("Milk 1 gal", "Dr Pepper 12pk", "Large Eggs 12 ct"):
        assert normalize_item_name(s) == normalize_item_name(s)


# ══ 2. CONSUMPTION ═══════════════════════════════════════════════════════════
def test_two_purchases_never_predict(client):
    """The core honesty rule: below MIN_OBSERVATIONS, nothing is predicted."""
    _clear()
    today = date.today()
    _trip(client, _iso(today - timedelta(days=6)), _milk())
    _trip(client, _iso(today - timedelta(days=3)), _milk())

    conn = db.get_conn()
    s = consumption_stats(conn, "milk", today=today)
    conn.close()

    assert s["status"] == "insufficient_data"
    assert s["observations"] == 2
    assert s["needed"] == MIN_OBSERVATIONS - 2
    # Explicitly None — NOT absent, and never a number a caller could plot.
    assert s["avg_interval_days"] is None
    assert s["predicted_next_date"] is None
    assert s["days_until_next"] is None
    assert s["confidence"] == "none"
    # …but the points we DO have are still returned, so a sparse item can be
    # plotted honestly instead of hidden.
    assert len(s["points"]) == 2


def test_one_purchase_reports_how_many_more_are_needed(client):
    _clear()
    _trip(client, _iso(date.today() - timedelta(days=2)), _milk())
    conn = db.get_conn()
    s = consumption_stats(conn, "milk")
    conn.close()
    assert s["status"] == "insufficient_data"
    assert s["observations"] == 1
    assert s["needed"] == MIN_OBSERVATIONS - 1
    assert "1 purchase recorded" in s["message"]


def test_three_purchases_predict_the_interval(client):
    """Exactly at the floor: 3 buys, 2 intervals, a real cadence."""
    _clear()
    today = date.today()
    for back in (9, 6, 3):          # every 3 days
        _trip(client, _iso(today - timedelta(days=back)), _milk())

    conn = db.get_conn()
    s = consumption_stats(conn, "milk", today=today)
    conn.close()

    assert s["status"] == "ok"
    assert s["observations"] == 3
    assert s["avg_interval_days"] == 3.0
    assert s["intervals"] == [3, 3]
    # last buy was 3 days ago + a 3-day cadence = due today
    assert s["predicted_next_date"] == _iso(today)
    assert s["days_until_next"] == 0
    # Perfectly regular, but only 3 samples — 3 trips is not yet a proven habit.
    assert s["confidence"] == "medium"
    assert s["interval_cv"] == 0.0


def test_confidence_rises_with_samples_and_falls_with_spread(client):
    _clear()
    today = date.today()
    for back in (18, 15, 12, 9, 6, 3):      # 6 buys, dead regular
        _trip(client, _iso(today - timedelta(days=back)), _milk())
    conn = db.get_conn()
    steady = consumption_stats(conn, "milk", today=today)
    conn.close()
    assert steady["confidence"] == "high"

    _clear()
    for back in (40, 39, 20, 3):            # same count-ish, wildly irregular
        _trip(client, _iso(today - timedelta(days=back)), _milk())
    conn = db.get_conn()
    erratic = consumption_stats(conn, "milk", today=today)
    conn.close()
    assert erratic["status"] == "ok"
    assert erratic["confidence"] == "low"
    assert erratic["interval_cv"] > steady["interval_cv"]


def test_same_day_lines_are_one_shopping_event(client):
    """Two gallons in one trip is ONE event. Counting it as two would inject a
    fake 0-day interval and halve the measured cadence."""
    _clear()
    today = date.today()
    for back in (9, 6, 3):
        _trip(client, _iso(today - timedelta(days=back)), _milk())
    # a second milk line on the SAME day as the last trip
    _trip(client, _iso(today - timedelta(days=3)), _milk(), merchant="Other Store")

    conn = db.get_conn()
    s = consumption_stats(conn, "milk", today=today)
    conn.close()
    assert s["observations"] == 3          # not 4
    assert 0 not in s["intervals"]
    assert s["avg_interval_days"] == 3.0
    assert s["total_qty"] == 4.0           # quantities still all counted


def test_price_trend_needs_three_points_then_reports_direction(client):
    _clear()
    today = date.today()
    _trip(client, _iso(today - timedelta(days=12)), _milk(price=300))
    _trip(client, _iso(today - timedelta(days=9)), _milk(price=310))
    conn = db.get_conn()
    thin = consumption_stats(conn, "milk", today=today)
    conn.close()
    assert thin["price_trend"]["status"] == "insufficient_data"

    _trip(client, _iso(today - timedelta(days=6)), _milk(price=400))
    _trip(client, _iso(today - timedelta(days=3)), _milk(price=420))
    conn = db.get_conn()
    s = consumption_stats(conn, "milk", today=today)
    conn.close()
    assert s["price_trend"]["status"] == "ok"
    assert s["price_trend"]["direction"] == "rising"
    assert s["price_trend"]["change_pct"] > 0
    assert s["last_unit_price_cents"] == 420


def test_consumption_endpoint_separates_ready_from_thin(client):
    _clear()
    today = date.today()
    for back in (9, 6, 3):
        _trip(client, _iso(today - timedelta(days=back)), _milk())
    _trip(client, _iso(today - timedelta(days=2)),
          [{"name": "Coffee 12 oz", "qty": 1, "unit_price_cents": 899}])

    r = client.get("/api/budget/consumption")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["predictable"] == 1
    assert body["counts"]["insufficient"] == 1
    by = {i["normalized_name"]: i for i in body["items"]}
    assert by["milk"]["status"] == "ok"
    assert by["coffee"]["status"] == "insufficient_data"
    assert by["coffee"]["predicted_next_date"] is None


def test_single_total_purchase_still_works_unchanged(client):
    """Items are purely additive — a trip logged as one total behaves as before."""
    _clear()
    r = client.post("/api/ledger/purchases",
                    json={"merchant": "Corner Store", "amount_cents": 4321,
                          "category": "food"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount_cents"] == 4321
    assert body["item_count"] == 0


def test_itemized_purchase_sums_its_lines(client):
    _clear()
    body = _trip(client, _iso(date.today()),
                 [{"name": "Milk 1 gal", "qty": 2, "unit_price_cents": 400},
                  {"name": "Bread", "qty": 1, "unit_price_cents": 279}])
    assert body["amount_cents"] == 2 * 400 + 279
    assert body["item_count"] == 2


def test_explicit_total_beats_the_line_sum(client):
    """A receipt total legitimately exceeds the lines (tax). The stated amount is
    the money; the lines stay detail."""
    _clear()
    body = _trip(client, _iso(date.today()), _milk(price=400), amount_cents=437)
    assert body["amount_cents"] == 437
    assert body["items_total_cents"] == 400


# ══ 3. PAY PERIOD + ENVELOPES ════════════════════════════════════════════════
def test_period_bounds_biweekly_walks_from_the_anchor():
    a = "2026-01-01"
    s, e = period_bounds("biweekly", a, date(2026, 1, 1))
    assert (s.isoformat(), e.isoformat()) == ("2026-01-01", "2026-01-14")
    s, e = period_bounds("biweekly", a, date(2026, 1, 14))
    assert (s.isoformat(), e.isoformat()) == ("2026-01-01", "2026-01-14")
    s, e = period_bounds("biweekly", a, date(2026, 1, 15))
    assert (s.isoformat(), e.isoformat()) == ("2026-01-15", "2026-01-28")
    # before the anchor, floor division must still land on a whole period
    s, e = period_bounds("biweekly", a, date(2025, 12, 31))
    assert (s.isoformat(), e.isoformat()) == ("2025-12-18", "2025-12-31")


def test_period_bounds_monthly_clamps_a_month_end_anchor():
    # A 31st anchor must behave exactly like a 31st bill: clamp, never skip.
    s, e = period_bounds("monthly", "2026-01-31", date(2026, 2, 10))
    assert s.isoformat() == "2026-01-31"
    s, e = period_bounds("monthly", "2026-01-31", date(2026, 3, 1))
    assert s.isoformat() == "2026-02-28"       # February clamps
    assert e.isoformat() == "2026-03-30"


def test_period_bounds_unconfigured_falls_back_to_calendar_month():
    s, e = period_bounds("", "", date(2026, 7, 19))
    assert (s.isoformat(), e.isoformat()) == ("2026-07-01", "2026-07-31")


def test_no_income_means_insufficient_data_not_zero(client):
    """A zero income basis would make every percent envelope $0 and safe-to-spend
    look like a real answer. It must refuse instead."""
    _clear()
    conn = db.get_conn()
    snap = compute_period(conn)
    conn.close()
    assert snap["status"] == "insufficient_data"
    assert snap["income"]["basis_cents"] is None
    assert snap["safe_to_spend_cents"] is None
    assert snap["disposable_cents"] is None
    assert snap["needs"]


def _setup_period(client, today=None):
    """A confirmed monthly cycle anchored on the 1st, with one recorded paycheck."""
    today = today or date.today()
    start = today.replace(day=1)
    r = client.post("/api/budget/config",
                    json={"pay_cycle": "monthly", "anchor": _iso(start)})
    assert r.status_code == 200, r.text
    r = client.post("/api/ledger/paychecks",
                    json={"source": "Employer", "amount_cents": 300000,
                          "received_at": _iso(start), "cycle": "monthly"})
    assert r.status_code == 200, r.text
    return start


def test_envelope_allocations_fixed_and_percent(client):
    _clear()
    _setup_period(client)
    client.post("/api/budget/envelopes",
                json={"category": "food", "kind": "fixed", "amount_cents": 50000})
    client.post("/api/budget/envelopes",
                json={"category": "savings", "kind": "percent", "percent": 10})

    conn = db.get_conn()
    snap = compute_period(conn)
    conn.close()
    envs = {e["category"]: e for e in snap["envelopes"]}
    assert envs["food"]["allocation_cents"] == 50000
    # 10% of the $3000 recorded paycheck
    assert envs["savings"]["allocation_cents"] == 30000
    assert snap["savings_target_cents"] == 30000
    assert snap["income"]["basis"] == "recorded"


def test_envelope_spend_and_remaining_track_purchases(client):
    _clear()
    start = _setup_period(client)
    client.post("/api/budget/envelopes",
                json={"category": "food", "kind": "fixed", "amount_cents": 50000})
    _trip(client, _iso(start), _milk(price=1200), category="food")
    _trip(client, _iso(start), _milk(price=800), category="food")

    conn = db.get_conn()
    snap = compute_period(conn)
    conn.close()
    food = next(e for e in snap["envelopes"] if e["category"] == "food")
    assert food["spent_cents"] == 2000
    assert food["remaining_cents"] == 48000
    assert food["over"] is False


def test_envelope_flags_going_over(client):
    _clear()
    start = _setup_period(client)
    client.post("/api/budget/envelopes",
                json={"category": "gas", "kind": "fixed", "amount_cents": 1000})
    _trip(client, _iso(start), [{"name": "Unleaded", "qty": 10, "unit_price_cents": 300}],
          category="gas")
    conn = db.get_conn()
    snap = compute_period(conn)
    conn.close()
    gas = next(e for e in snap["envelopes"] if e["category"] == "gas")
    assert gas["spent_cents"] == 3000
    assert gas["remaining_cents"] == -2000
    assert gas["over"] is True


def test_safe_to_spend_formula_is_traceable(client):
    """safe = income − bills due − savings target − purchases so far, and every
    part is reported so the figure can be checked by hand."""
    _clear()
    start = _setup_period(client)
    # one bill due inside the period
    r = client.post("/api/bills", json={"name": "Power", "cycle": "monthly",
                                        "amount_cents": 12000,
                                        "next_due": _iso(start + timedelta(days=4))})
    assert r.status_code == 200, r.text
    client.post("/api/budget/envelopes",
                json={"category": "savings", "kind": "fixed", "amount_cents": 20000})
    _trip(client, _iso(start), _milk(price=5000), category="food")

    conn = db.get_conn()
    snap = compute_period(conn)
    conn.close()

    parts = snap["safe_to_spend_parts"]
    assert parts["income_basis_cents"] == 300000
    assert parts["less_committed_cents"] == 12000
    assert parts["less_savings_target_cents"] == 20000
    assert parts["less_spent_cents"] == 5000
    assert snap["safe_to_spend_cents"] == 300000 - 12000 - 20000 - 5000
    # and the parts really do reconstruct the headline number
    assert snap["safe_to_spend_cents"] == (parts["income_basis_cents"]
                                           - parts["less_committed_cents"]
                                           - parts["less_savings_target_cents"]
                                           - parts["less_spent_cents"])


def test_bills_and_purchases_are_never_double_counted(client):
    """The invariant ledger.py documents: bill money comes from bills, everything
    else from purchases, and paying a bill must not move the purchase-side spend."""
    _clear()
    start = _setup_period(client)
    r = client.post("/api/bills", json={"name": "Power", "cycle": "monthly",
                                        "amount_cents": 12000,
                                        "next_due": _iso(start + timedelta(days=4))})
    bid = r.json()["id"]
    _trip(client, _iso(start), _milk(price=5000), category="food")

    conn = db.get_conn()
    before = compute_period(conn)
    conn.close()

    # Pay the bill: that writes a bill_payments row.
    r = client.post(f"/api/bills/{bid}/pay", json={"paid_at": _iso(start + timedelta(days=4))})
    assert r.status_code == 200, r.text

    conn = db.get_conn()
    after = compute_period(conn)
    conn.close()

    # The purchase-side spend is untouched — a bill payment is NOT a purchase.
    assert after["spend"]["total_cents"] == before["spend"]["total_cents"] == 5000
    # Counted ONCE either way: once as due, then once as paid — never both, never
    # neither. Marking it paid advances next_due out of the period, so a naive
    # "sum the remaining due dates" would drop it here and make safe-to-spend jump
    # UP by $120 immediately after $120 left the account.
    assert before["committed"]["cents"] == 12000
    assert after["committed"]["cents"] == 12000
    assert after["safe_to_spend_cents"] == before["safe_to_spend_cents"]
    assert after["committed"]["count"] == 1


def test_variable_amount_bills_are_not_treated_as_zero(client):
    _clear()
    start = _setup_period(client)
    client.post("/api/bills", json={"name": "Water", "cycle": "monthly",
                                    "amount_cents": None,
                                    "next_due": _iso(start + timedelta(days=3))})
    conn = db.get_conn()
    snap = compute_period(conn)
    conn.close()
    assert snap["committed"]["unknown_count"] == 1
    assert snap["committed"]["cents"] == 0
    assert "variable" in snap["committed"]["note"]


def test_cycle_candidates_refuse_to_guess_from_two_paychecks(client):
    _clear()
    today = date.today()
    for back in (14, 0):
        client.post("/api/ledger/paychecks",
                    json={"source": "Employer", "amount_cents": 100000,
                          "received_at": _iso(today - timedelta(days=back))})
    conn = db.get_conn()
    c = bg.cycle_candidates(conn)
    conn.close()
    assert c["status"] == "insufficient_data"
    assert c["observed"] is None

    for back in (28, 42):
        client.post("/api/ledger/paychecks",
                    json={"source": "Employer", "amount_cents": 100000,
                          "received_at": _iso(today - timedelta(days=back))})
    conn = db.get_conn()
    c = bg.cycle_candidates(conn)
    conn.close()
    assert c["status"] == "ok"
    assert c["observed"] == "biweekly"
    assert c["median_gap_days"] == 14


# ══ 4. CALENDAR EVENTS ═══════════════════════════════════════════════════════
def _cal(client, frm, to):
    r = client.get(f"/api/calendar/events?from={frm}&to={to}")
    assert r.status_code == 200, r.text
    return r.json()


def test_budget_and_restock_events_appear_and_are_flagged_projected(client):
    _clear()
    today = date.today()
    start = _setup_period(client)
    client.post("/api/budget/envelopes",
                json={"category": "savings", "kind": "fixed", "amount_cents": 20000})
    for back in (9, 6, 3):
        _trip(client, _iso(today - timedelta(days=back)), _milk())

    body = _cal(client, _iso(start - timedelta(days=1)), _iso(today + timedelta(days=40)))
    types = {e["type"] for e in body["events"]}
    assert "budget_period" in types
    assert "savings_target" in types
    assert "safe_to_spend" in types
    assert "restock" in types

    # A prediction must ALWAYS be flagged as one.
    for e in body["events"]:
        if e["type"] == "restock":
            assert e["projected"] is True
            assert "likely out" in e["title"]
    # The recorded rows keep their existing shape and flags.
    for e in body["events"]:
        if e["type"] in ("paycheck", "purchase"):
            assert e["projected"] is False


def test_budget_markers_do_not_pollute_calendar_totals(client):
    """budget_period restates income the paycheck row already carries; if it were
    summed the calendar's income total would read double."""
    _clear()
    today = date.today()
    start = _setup_period(client)
    body = _cal(client, _iso(start - timedelta(days=1)), _iso(today + timedelta(days=20)))
    assert body["totals"]["income_cents"] == 300000     # the paycheck, once
    assert any(e["type"] == "budget_period" for e in body["events"])


def test_existing_event_ids_and_shape_are_unchanged(client):
    _clear()
    today = date.today()
    _setup_period(client)
    p = _trip(client, _iso(today), _milk(price=1234))
    body = _cal(client, _iso(today - timedelta(days=1)), _iso(today + timedelta(days=1)))
    pur = next(e for e in body["events"] if e["type"] == "purchase")
    assert pur["id"] == f"purchase-{p['id']}"
    assert pur["direction"] == "out" and pur["state"] == "spent"


def test_ics_carries_budget_events_with_stable_uids(client):
    _clear()
    today = date.today()
    _setup_period(client)
    for back in (9, 6, 3):
        _trip(client, _iso(today - timedelta(days=back)), _milk())

    def _uids():
        r = client.get("/api/calendar/export.ics")
        assert r.status_code == 200, r.text
        text = r.text
        assert "\r\n" in text
        return text, {ln[4:] for ln in text.split("\r\n") if ln.startswith("UID:")}

    text_a, uids_a = _uids()
    text_b, uids_b = _uids()
    # Same data in, same UIDs out — a UID that churned would re-notify every
    # subscriber on every refresh.
    assert uids_a == uids_b
    assert any(u.startswith("budget-restock-") for u in uids_a), uids_a
    assert any(u.startswith("budget-period-") for u in uids_a), uids_a
    # And the prediction says so in the body, so nobody reads it as a fact.
    assert "PREDICTED from your own purchase history" in text_a


def test_prediction_events_respect_their_toggle(client):
    _clear()
    today = date.today()
    _setup_period(client)
    for back in (9, 6, 3):
        _trip(client, _iso(today - timedelta(days=back)), _milk())

    r = client.post("/api/budget/toggles",
                    json={"key": "budget_calendar_predictions", "on": False})
    assert r.status_code == 200, r.text
    body = _cal(client, _iso(today - timedelta(days=10)), _iso(today + timedelta(days=20)))
    assert not any(e["type"] == "restock" for e in body["events"])

    client.post("/api/budget/toggles", json={"key": "budget_calendar_predictions", "on": True})
    body = _cal(client, _iso(today - timedelta(days=10)), _iso(today + timedelta(days=20)))
    assert any(e["type"] == "restock" for e in body["events"])


# ══ 5. THE PLANNER ═══════════════════════════════════════════════════════════
_CATALOG = [
    {"normalized_name": "milk", "name": "Milk 1 gal", "unit": "gal",
     "typical_qty": 1, "unit_price_cents": 400, "avg_interval_days": 3.0,
     "days_until_next": 0, "predicted_next_date": "2026-07-19"},
    {"normalized_name": "egg", "name": "Large Eggs 12 ct", "unit": "ct",
     "typical_qty": 1, "unit_price_cents": 329, "avg_interval_days": 6.0,
     "days_until_next": 2, "predicted_next_date": "2026-07-21"},
    {"normalized_name": "bread", "name": "Bread", "unit": "",
     "typical_qty": 1, "unit_price_cents": None, "avg_interval_days": 7.0,
     "days_until_next": 3, "predicted_next_date": "2026-07-22"},
]


def test_planner_drops_items_that_are_not_in_the_history():
    """The anti-hallucination gate. Caviar is a perfectly sensible grocery item;
    it is not in HIS history, so it does not get onto HIS list."""
    accepted, rejected = validate_plan_items(
        [{"name": "Milk 1 gal", "qty": 1},
         {"name": "Caviar", "qty": 1},
         {"name": "Truffle Oil", "qty": 2}], _CATALOG)
    assert [a["normalized_name"] for a in accepted] == ["milk"]
    assert {r["name"] for r in rejected} == {"Caviar", "Truffle Oil"}
    assert all(r["reason"] == "unknown_item" for r in rejected)


def test_planner_matches_through_the_normalizer():
    """The model spelling it differently is not hallucination — "milk gallon" is
    the same item and must be accepted, not dropped."""
    accepted, rejected = validate_plan_items([{"name": "milk gallon", "qty": 2}], _CATALOG)
    assert len(accepted) == 1 and not rejected
    assert accepted[0]["normalized_name"] == "milk"
    assert accepted[0]["name"] == "Milk 1 gal"       # OUR display name wins


def test_planner_ignores_any_price_the_model_supplies():
    """Prices come from his receipts. A model-invented price must never survive."""
    accepted, _ = validate_plan_items(
        [{"name": "Milk 1 gal", "qty": 2, "unit_price_cents": 99999,
          "est_cents": 99999, "price": "$999.99"}], _CATALOG)
    assert accepted[0]["unit_price_cents"] == 400          # ours, not theirs
    assert accepted[0]["est_cents"] == 800                 # 2 × 400
    assert "your last recorded unit price" in accepted[0]["price_source"]


def test_planner_flags_rather_than_invents_a_missing_price():
    accepted, _ = validate_plan_items([{"name": "Bread", "qty": 1}], _CATALOG)
    assert accepted[0]["est_cents"] is None
    assert accepted[0]["unit_price_cents"] is None
    assert "no_price" in accepted[0]["flags"]


def test_planner_clamps_absurd_quantities_and_dedupes():
    accepted, rejected = validate_plan_items(
        [{"name": "Milk 1 gal", "qty": 999},
         {"name": "milk", "qty": 1}], _CATALOG)
    assert len(accepted) == 1
    assert accepted[0]["qty"] == 4                  # 4× typical, not 999
    assert rejected[0]["reason"] == "duplicate"


def test_planner_handles_junk_from_the_model():
    accepted, rejected = validate_plan_items(
        ["just a string", {"qty": 3}, None], _CATALOG)
    assert accepted == []
    assert len(rejected) == 3


def test_plan_generation_rides_the_orchestrator_not_lmstudio(client, monkeypatch):
    """Every model call in this app goes through orch.submit_llm. A direct
    LM Studio call would bypass the queue, the model registry and the GPU guard."""
    _clear()
    today = date.today()
    _setup_period(client)
    client.post("/api/budget/envelopes",
                json={"category": "food", "kind": "fixed", "amount_cents": 50000})
    for back in (9, 6, 3):
        _trip(client, _iso(today - timedelta(days=back)), _milk())

    seen = {}

    def _fake_submit(func, desc="", **kw):
        seen["desc"] = desc
        seen["task"] = kw.get("task")
        seen["result"] = func()          # run the queued work inline
        return 4242

    # If the planner reached past the orchestrator, THIS would fire first.
    def _boom(*a, **k):
        raise AssertionError("planner called LM Studio directly — it must use orch.submit_llm")

    monkeypatch.setattr(bg._call_lmstudio, "__call__", _boom, raising=False)
    monkeypatch.setattr(bg.orch, "submit_llm", _fake_submit)
    monkeypatch.setattr(bg, "_call_lmstudio",
                        lambda system, user, **kw: '{"items": [{"name": "Milk 1 gal", '
                                                   '"qty": 1, "why": "out today"}, '
                                                   '{"name": "Caviar", "qty": 1}], '
                                                   '"observations": ["milk is your steadiest buy"]}')

    r = client.post("/api/budget/plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"] == 4242
    assert seen["task"] == "budget_grocery_plan"

    plan = client.get(f"/api/budget/plans/{body['plan_id']}").json()
    assert plan["status"] == "draft"
    assert [i["normalized_name"] for i in plan["items"]] == ["milk"]
    assert plan["rejected_items"][0]["name"] == "Caviar"
    assert plan["est_total_cents"] == 400
    # The model's notes are kept, but labelled advisory and separate from our facts.
    assert plan["llm_notes"][0]["advisory"] is True


def test_plan_is_advisory_only_and_needs_acceptance(client, monkeypatch):
    _clear()
    today = date.today()
    _setup_period(client)
    for back in (9, 6, 3):
        _trip(client, _iso(today - timedelta(days=back)), _milk())
    monkeypatch.setattr(bg.orch, "submit_llm", lambda func, desc="", **kw: (func(), 1)[1])
    monkeypatch.setattr(bg, "_call_lmstudio",
                        lambda s, u, **k: '{"items": [{"name": "Milk 1 gal", "qty": 1}]}')
    pid = client.post("/api/budget/plan").json()["plan_id"]

    # A DRAFT cannot become a purchase — acceptance is a separate owner action.
    r = client.post(f"/api/budget/plans/{pid}/purchase", json={"merchant": "Corner Store"})
    assert r.status_code == 400
    assert "accept the plan first" in r.text

    assert client.post(f"/api/budget/plans/{pid}/accept").json()["status"] == "accepted"
    r = client.post(f"/api/budget/plans/{pid}/purchase", json={"merchant": "Corner Store"})
    assert r.status_code == 200, r.text
    assert r.json()["amount_cents"] == 400
    # …and only once.
    assert client.post(f"/api/budget/plans/{pid}/purchase",
                       json={"merchant": "Corner Store"}).status_code == 400


def test_planner_toggle_blocks_generation(client):
    _clear()
    _setup_period(client)
    r = client.post("/api/budget/toggles", json={"key": "budget_planner_enabled", "on": False})
    assert r.status_code == 200, r.text
    r = client.post("/api/budget/plan")
    assert r.status_code == 400
    assert "turned off" in r.text
    client.post("/api/budget/toggles", json={"key": "budget_planner_enabled", "on": True})


def test_planner_refuses_when_no_item_has_enough_history(client):
    _clear()
    _setup_period(client)
    _trip(client, _iso(date.today()), _milk())      # one purchase only
    r = client.post("/api/budget/plan")
    assert r.status_code == 400
    assert str(MIN_OBSERVATIONS) in r.text


# ══ 6. SAMPLE DATA ═══════════════════════════════════════════════════════════
def test_sample_seed_then_purge_round_trips(client):
    _clear()
    assert client.get("/api/budget/sample").json()["present"] is False
    r = client.post("/api/budget/sample/seed", json={"months": 2})
    assert r.status_code == 200, r.text
    seeded = r.json()["seeded"]
    assert seeded["purchases"] > 10 and seeded["paychecks"] >= 4 and seeded["bills"] == 3

    status = client.get("/api/budget/sample").json()
    assert status["present"] is True

    r = client.post("/api/budget/sample/purge")
    assert r.status_code == 200, r.text
    assert r.json()["removed"]["purchases"] == seeded["purchases"]
    assert client.get("/api/budget/sample").json()["present"] is False

    conn = db.get_conn()
    left = conn.execute("SELECT COUNT(*) FROM purchase_items").fetchone()[0]
    conn.close()
    assert left == 0            # the sample lines went with their purchases


def test_purge_never_touches_the_owners_real_rows(client):
    """The safety property that matters: this runs against a DB holding real money
    records, and an untagged row must be unreachable from the purge."""
    _clear()
    # Real, owner-entered rows — no sample tag anywhere.
    real_p = client.post("/api/ledger/purchases",
                         json={"merchant": "Corner Store", "amount_cents": 1999,
                               "category": "food"}).json()
    real_c = client.post("/api/ledger/paychecks",
                         json={"source": "Employer", "amount_cents": 250000}).json()
    real_b = client.post("/api/bills", json={"name": "Power", "amount_cents": 9900,
                                             "cycle": "monthly"}).json()
    # A real row that even MENTIONS the tag in free text must survive: the purge
    # matches the parsed tag field, never a substring of user prose.
    decoy = client.post("/api/ledger/purchases",
                        json={"merchant": "Corner Store", "amount_cents": 500,
                              "notes": f"not sample: {bg.SAMPLE_TAG}",
                              "extra": {"note": bg.SAMPLE_TAG}}).json()

    client.post("/api/budget/sample/seed", json={"months": 1})
    r = client.post("/api/budget/sample/purge")
    assert r.status_code == 200, r.text

    for url in (f"/api/ledger/purchases", "/api/ledger/paychecks", "/api/bills"):
        assert client.get(url).status_code == 200
    conn = db.get_conn()
    assert conn.execute("SELECT COUNT(*) FROM purchases WHERE id=?", (real_p["id"],)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM purchases WHERE id=?", (decoy["id"],)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM paychecks WHERE id=?", (real_c["id"],)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM bills WHERE id=?", (real_b["id"],)).fetchone()[0] == 1
    conn.close()


def test_seeded_data_produces_a_real_milk_cadence(client):
    """End-to-end over the seed: the demo history must actually measure ~3 days."""
    _clear()
    client.post("/api/budget/sample/seed", json={"months": 2})
    r = client.get("/api/budget/consumption/item?name=milk")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["status"] == "ok"
    assert 2.5 <= s["avg_interval_days"] <= 3.5
    assert s["price_trend"]["direction"] == "rising"     # the seed climbs on purpose
    # and the thin item stays honest
    assert client.get("/api/budget/consumption/item?name=coffee").json()["status"] \
        == "insufficient_data"
    client.post("/api/budget/sample/purge")
    _clear()
