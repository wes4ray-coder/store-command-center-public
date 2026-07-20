"""💵 personal money ledger (routers/money/ledger.py — /api/ledger/*).

Named test_money_ledger (not test_ledger) because tests/test_ledger.py already
belongs to the God Console's world_ops ledger — a totally unrelated table.

Locks down:
  • paycheck CRUD, incl. the hours × hourly-rate auto-calculated amount (the rate
    is per-entry — no rate is ever hardcoded) and cycle validation
  • purchase CRUD (non-bill spending) + the per-category month breakdown
  • summary math: income − (purchases + bill_payments) = net, for this month and
    YTD, with the bill-payment side read from the EXISTING bill_payments table
    that bills.py writes — proving the two outgoing sets never double-count
  • series bucketing by month (income vs purchases vs bill payments vs outgoings)
  • CSV export → import round-trip for both entities

Sibling of tests/test_bills.py.
"""
from datetime import date, timedelta

import db


def _clear():
    conn = db.get_conn()
    for t in ("paychecks", "purchases", "bill_payments", "bills"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()


def _iso(d: date) -> str:
    return d.isoformat()


def _pay(client, **kw):
    body = {"source": "Client A", "amount_cents": 50000, **kw}
    r = client.post("/api/ledger/paychecks", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _buy(client, **kw):
    body = {"merchant": "Hardware store", "amount_cents": 2500, **kw}
    r = client.post("/api/ledger/purchases", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _bill_paid(client, amount_cents, paid_at=None, name="Power", category="utilities"):
    """A REAL bill payment, written through bills.py into bill_payments."""
    b = client.post("/api/bills", json={"name": name, "category": category,
                                        "amount_cents": amount_cents,
                                        "next_due": _iso(date.today())}).json()
    r = client.post(f"/api/bills/{b['id']}/pay",
                    json={"amount_cents": amount_cents, "paid_at": paid_at or _iso(date.today())})
    assert r.status_code == 200, r.text
    return b


# ── paychecks ─────────────────────────────────────────────────────────────────
def test_paycheck_crud(client):
    _clear()
    p = _pay(client, source="Client A", amount_cents=120000, gross_cents=145000,
             received_at="2026-07-10", cycle="biweekly", notes="deck job",
             extra={"invoice": "1042"})
    assert p["amount_cents"] == 120000 and p["gross_cents"] == 145000
    assert p["received_at"] == "2026-07-10" and p["cycle"] == "biweekly"
    assert p["extra"] == {"invoice": "1042"}

    _pay(client, source="Client B", amount_cents=30000, received_at="2026-07-01")
    lst = client.get("/api/ledger/paychecks").json()
    assert [x["source"] for x in lst["paychecks"]] == ["Client A", "Client B"]  # newest first
    assert lst["sources"] == ["Client A", "Client B"]
    assert client.get("/api/ledger/paychecks?source=Client B").json()["paychecks"][0]["amount_cents"] == 30000

    r = client.patch(f"/api/ledger/paychecks/{p['id']}",
                     json={"source": "Client A LLC", "notes": "paid by check", "cycle": "monthly"})
    assert r.status_code == 200 and r.json()["source"] == "Client A LLC"
    assert r.json()["cycle"] == "monthly" and r.json()["notes"] == "paid by check"

    # validation
    assert client.post("/api/ledger/paychecks", json={"source": " ", "amount_cents": 100}).status_code == 400
    assert client.post("/api/ledger/paychecks", json={"source": "x"}).status_code == 400   # no amount, no hours×rate
    assert client.post("/api/ledger/paychecks",
                       json={"source": "x", "amount_cents": 1, "cycle": "fortnightly"}).status_code == 400
    assert client.post("/api/ledger/paychecks",
                       json={"source": "x", "amount_cents": 1, "received_at": "nope"}).status_code == 400
    assert client.patch(f"/api/ledger/paychecks/{p['id']}", json={"cycle": "bogus"}).status_code == 400
    assert client.patch("/api/ledger/paychecks/999999", json={"source": "x"}).status_code == 404
    assert client.patch(f"/api/ledger/paychecks/{p['id']}", json={}).status_code == 400

    assert client.delete(f"/api/ledger/paychecks/{p['id']}").status_code == 200
    assert client.delete(f"/api/ledger/paychecks/{p['id']}").status_code == 404


def test_paycheck_hours_times_rate(client):
    _clear()
    # amount omitted → hours × per-entry rate fills it in (rate is data, not a constant)
    p = _pay(client, source="Carpentry", amount_cents=None, hours=12.5, hourly_rate_cents=4000)
    assert p["amount_cents"] == 50000 and p["hours"] == 12.5 and p["hourly_rate_cents"] == 4000

    # a different entry can carry a completely different rate
    q = _pay(client, source="Other client", amount_cents=None, hours=8, hourly_rate_cents=6250)
    assert q["amount_cents"] == 50000

    # rounding to the nearest cent
    r = _pay(client, source="Odd hours", amount_cents=None, hours=1.333, hourly_rate_cents=4000)
    assert r["amount_cents"] == round(1.333 * 4000)

    # an explicit amount always wins over hours × rate (overtime, bonus, net vs gross)
    e = _pay(client, source="Bonus week", amount_cents=99999, hours=10, hourly_rate_cents=4000)
    assert e["amount_cents"] == 99999

    # patching hours re-derives the amount when no explicit amount is sent
    up = client.patch(f"/api/ledger/paychecks/{p['id']}", json={"hours": 20}).json()
    assert up["amount_cents"] == 80000
    # …and patching the rate does too
    up2 = client.patch(f"/api/ledger/paychecks/{p['id']}", json={"hourly_rate_cents": 5000}).json()
    assert up2["amount_cents"] == 100000
    # an explicit amount in the same patch still wins
    up3 = client.patch(f"/api/ledger/paychecks/{p['id']}",
                       json={"hours": 1, "amount_cents": 12345}).json()
    assert up3["amount_cents"] == 12345

    assert client.post("/api/ledger/paychecks",
                       json={"source": "x", "hours": -1, "hourly_rate_cents": 100}).status_code == 400


def test_paycheck_month_and_ytd_totals(client):
    _clear()
    today = date.today()
    _pay(client, source="A", amount_cents=10000, received_at=_iso(today))
    _pay(client, source="B", amount_cents=20000, received_at=_iso(today))
    _pay(client, source="C", amount_cents=70000, received_at=f"{today.year}-01-05")
    lst = client.get("/api/ledger/paychecks").json()
    in_jan = today.month == 1
    assert lst["month_cents"] == (100000 if in_jan else 30000)
    assert lst["month_count"] == (3 if in_jan else 2)
    assert lst["ytd_cents"] == 100000 and lst["ytd_count"] == 3


# ── purchases ─────────────────────────────────────────────────────────────────
def test_purchase_crud(client):
    _clear()
    today = date.today()
    p = _buy(client, merchant="Lumber yard", amount_cents=8450, category="materials",
             method="card", notes="2x4s", extra={"receipt": "R-99"})
    assert p["amount_cents"] == 8450 and p["category"] == "materials"
    assert p["method"] == "card" and p["extra"] == {"receipt": "R-99"}
    assert p["purchased_at"] == _iso(today)          # date defaults to today

    _buy(client, merchant="Grocery", amount_cents=5000, category="food",
         purchased_at=_iso(today - timedelta(days=1)))
    lst = client.get("/api/ledger/purchases").json()
    assert [x["merchant"] for x in lst["purchases"]] == ["Lumber yard", "Grocery"]
    assert client.get("/api/ledger/purchases?category=food").json()["purchases"][0]["merchant"] == "Grocery"
    assert len(client.get(f"/api/ledger/purchases?month={_iso(today)[:7]}").json()["purchases"]) >= 1

    r = client.patch(f"/api/ledger/purchases/{p['id']}",
                     json={"merchant": "Lumber Yard Co", "amount_cents": 9000})
    assert r.status_code == 200 and r.json()["amount_cents"] == 9000

    assert client.post("/api/ledger/purchases", json={"merchant": " ", "amount_cents": 1}).status_code == 400
    assert client.post("/api/ledger/purchases", json={"merchant": "x"}).status_code == 400
    assert client.post("/api/ledger/purchases",
                       json={"merchant": "x", "amount_cents": 1, "purchased_at": "nope"}).status_code == 400
    assert client.patch("/api/ledger/purchases/999999", json={"merchant": "x"}).status_code == 404

    assert client.delete(f"/api/ledger/purchases/{p['id']}").status_code == 200
    assert client.delete(f"/api/ledger/purchases/{p['id']}").status_code == 404


def test_purchase_month_category_breakdown(client):
    _clear()
    today = _iso(date.today())
    _buy(client, merchant="A", amount_cents=1000, category="food", purchased_at=today)
    _buy(client, merchant="B", amount_cents=2500, category="food", purchased_at=today)
    _buy(client, merchant="C", amount_cents=9000, category="materials", purchased_at=today)
    _buy(client, merchant="D", amount_cents=500, purchased_at=today)          # no category
    lst = client.get("/api/ledger/purchases").json()
    cats = {c["cat"]: c for c in lst["month_categories"]}
    assert cats["materials"]["total"] == 9000 and cats["materials"]["n"] == 1
    assert cats["food"]["total"] == 3500 and cats["food"]["n"] == 2
    assert cats["uncategorized"]["total"] == 500
    assert [c["cat"] for c in lst["month_categories"]][0] == "materials"      # biggest first
    assert lst["month_cents"] == 13000


# ── summary: income − (purchases + bill payments) = net ───────────────────────
def test_summary_math_no_double_counting(client):
    _clear()
    today = date.today()
    t = _iso(today)
    jan = f"{today.year}-01-15"

    _pay(client, source="A", amount_cents=200000, received_at=t)
    _pay(client, source="B", amount_cents=100000, received_at=jan)
    _buy(client, merchant="Store", amount_cents=25000, purchased_at=t)
    _buy(client, merchant="Store", amount_cents=5000, purchased_at=jan)
    _bill_paid(client, 15000, paid_at=t, name="Power")
    _bill_paid(client, 3000, paid_at=jan, name="Water")

    s = client.get("/api/ledger/summary").json()
    in_jan = today.month == 1
    # the scope dicts live under "month"/"ytd"; the plain strings are month_key/year
    assert s["month_key"] == t[:7] and s["year"] == str(today.year)

    m = s["month"]
    exp_income = 300000 if in_jan else 200000
    exp_pur = 30000 if in_jan else 25000
    exp_bills = 18000 if in_jan else 15000
    assert m["income_cents"] == exp_income
    assert m["purchases_cents"] == exp_pur
    # bill payments come from the EXISTING bill_payments table, not from purchases
    assert m["bill_payments_cents"] == exp_bills
    assert m["outgoings_cents"] == exp_pur + exp_bills
    assert m["net_cents"] == exp_income - (exp_pur + exp_bills)

    y = s["ytd"]
    assert y["income_cents"] == 300000 and y["income_count"] == 2
    assert y["purchases_cents"] == 30000 and y["purchases_count"] == 2
    assert y["bill_payments_cents"] == 18000 and y["bill_payments_count"] == 2
    assert y["outgoings_cents"] == 48000
    assert y["net_cents"] == 300000 - 48000 == 252000

    # the two outgoing sets are disjoint: a bill payment is NOT a purchase row
    conn = db.get_conn()
    assert conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM bill_payments").fetchone()[0] == 2
    conn.close()

    # a negative month reads as a negative net (spent more than earned)
    _buy(client, merchant="Big spend", amount_cents=999999, purchased_at=t)
    assert client.get("/api/ledger/summary").json()["month"]["net_cents"] < 0


def test_summary_empty_is_zeroed(client):
    _clear()
    s = client.get("/api/ledger/summary").json()
    for scope in ("month", "ytd"):
        assert s[scope] == {"income_cents": 0, "income_count": 0, "purchases_cents": 0,
                            "purchases_count": 0, "bill_payments_cents": 0,
                            "bill_payments_count": 0, "outgoings_cents": 0, "net_cents": 0}


# ── series ────────────────────────────────────────────────────────────────────
def test_series_buckets_by_month(client):
    _clear()
    today = date.today()
    last_month = today.replace(day=1) - timedelta(days=1)

    _pay(client, source="A", amount_cents=100000, received_at=_iso(today))
    _pay(client, source="A", amount_cents=80000, received_at=_iso(last_month))
    _buy(client, merchant="S", amount_cents=4000, purchased_at=_iso(today))
    _buy(client, merchant="S", amount_cents=1000, purchased_at=_iso(last_month))
    _bill_paid(client, 7000, paid_at=_iso(today), name="Power")
    _bill_paid(client, 6000, paid_at=_iso(last_month), name="Water")

    s = client.get("/api/ledger/series?months=3").json()
    assert len(s["months"]) == 3
    assert s["months"][-1] == _iso(today)[:7] and s["months"][-2] == _iso(last_month)[:7]
    assert s["income_cents"][-1] == 100000 and s["income_cents"][-2] == 80000
    assert s["purchases_cents"][-1] == 4000 and s["purchases_cents"][-2] == 1000
    assert s["bill_payments_cents"][-1] == 7000 and s["bill_payments_cents"][-2] == 6000
    assert s["outgoings_cents"][-1] == 11000 and s["outgoings_cents"][-2] == 7000
    assert s["net_cents"][-1] == 89000 and s["net_cents"][-2] == 73000
    assert s["income_cents"][0] == 0 and s["outgoings_cents"][0] == 0   # untouched month
    # bounds
    assert len(client.get("/api/ledger/series?months=0").json()["months"]) == 1
    assert len(client.get("/api/ledger/series?months=999").json()["months"]) == 60


# ── CSV round-trips ───────────────────────────────────────────────────────────
def test_paycheck_csv_roundtrip(client):
    _clear()
    _pay(client, source="Client A", amount_cents=120050, gross_cents=145000,
         received_at="2026-07-10", cycle="biweekly", notes="deck job", extra={"invoice": "1042"})
    _pay(client, source="Hourly client", amount_cents=None, hours=10.5,
         hourly_rate_cents=4000, received_at="2026-07-12", cycle="weekly")

    csv_text = client.get("/api/ledger/paychecks/export.csv").text
    assert "Client A" in csv_text and "biweekly" in csv_text and "1200.50" in csv_text

    _clear()
    r = client.post("/api/ledger/paychecks/import", json={"csv": csv_text})
    assert r.status_code == 200 and r.json() == {"imported": 2, "errors": []}

    got = {p["source"]: p for p in client.get("/api/ledger/paychecks").json()["paychecks"]}
    a = got["Client A"]
    assert a["amount_cents"] == 120050 and a["gross_cents"] == 145000
    assert a["received_at"] == "2026-07-10" and a["cycle"] == "biweekly"
    assert a["notes"] == "deck job" and a["extra"] == {"invoice": "1042"}
    h = got["Hourly client"]
    assert h["hours"] == 10.5 and h["hourly_rate_cents"] == 4000 and h["amount_cents"] == 42000

    # hours × rate with a blank amount is computed at import time
    out = client.post("/api/ledger/paychecks/import", json={
        "csv": "source,amount,hours,hourly_rate,date\nJob,,4,40.00,2026-07-14\n"}).json()
    assert out == {"imported": 1, "errors": []}
    assert client.get("/api/ledger/paychecks?source=Job").json()["paychecks"][0]["amount_cents"] == 16000

    # bad rows reported and skipped; good rows still import
    bad = ("source,amount,cycle,date\nOK,10.00,weekly,2026-09-01\n,5.00,weekly,2026-09-02\n"
           "X,1.00,fortnightly,2026-09-03\nY,,weekly,2026-09-04\n")
    out = client.post("/api/ledger/paychecks/import", json={"csv": bad}).json()
    assert out["imported"] == 1 and len(out["errors"]) == 3
    assert client.post("/api/ledger/paychecks/import", json={"csv": "  "}).status_code == 400


def test_purchase_csv_roundtrip(client):
    _clear()
    _buy(client, merchant="Lumber yard", amount_cents=8450, category="materials",
         method="card", notes="2x4s", purchased_at="2026-07-11", extra={"receipt": "R-99"})
    _buy(client, merchant="Grocery", amount_cents=5000, category="food",
         purchased_at="2026-07-12")

    csv_text = client.get("/api/ledger/purchases/export.csv").text
    assert "Lumber yard" in csv_text and "84.50" in csv_text and "materials" in csv_text

    _clear()
    r = client.post("/api/ledger/purchases/import", json={"csv": csv_text})
    assert r.status_code == 200 and r.json() == {"imported": 2, "errors": []}

    got = {p["merchant"]: p for p in client.get("/api/ledger/purchases").json()["purchases"]}
    lm = got["Lumber yard"]
    assert lm["amount_cents"] == 8450 and lm["category"] == "materials" and lm["method"] == "card"
    assert lm["purchased_at"] == "2026-07-11" and lm["extra"] == {"receipt": "R-99"}
    assert got["Grocery"]["amount_cents"] == 5000

    # header aliases + currency formatting
    out = client.post("/api/ledger/purchases/import", json={
        "csv": "store,total,date,payment_method\nCorner shop,\"$1,234.56\",2026-07-13,cash\n"}).json()
    assert out == {"imported": 1, "errors": []}
    cs = client.get("/api/ledger/purchases").json()["purchases"]
    assert [p for p in cs if p["merchant"] == "Corner shop"][0]["amount_cents"] == 123456

    bad = "merchant,amount,date\nOK,10.00,2026-09-01\n,5.00,2026-09-02\nX,,2026-09-03\n"
    out = client.post("/api/ledger/purchases/import", json={"csv": bad}).json()
    assert out["imported"] == 1 and len(out["errors"]) == 2
    assert client.post("/api/ledger/purchases/import", json={"csv": "  "}).status_code == 400
    _clear()
