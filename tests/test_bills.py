"""📆 REAL personal bills tracker (routers/money/bills.py — /api/bills/*).

Locks down:
  • CRUD (create fixed/variable, list order, patch validation, deactivate, delete)
  • mark-paid: logs a payment and advances next_due per cycle — including the
    month-end anchor (due day 31 → Feb 28 → Mar 31), leap years, catch-up when
    long overdue, and 'once' bills auto-deactivating
  • summary math (overdue/due-soon buckets, monthly estimate across cycles,
    variable-bill average, paid-this-month)
  • the per-month series endpoint (overall + per-category)
  • CSV export → import round-trip (incl. extras + the variable blank amount)

NOT the game world's in-game bills (world_bills) — totally separate tables.
"""
from datetime import date, timedelta

import db
from routers.money.bills import advance_due, _monthly_estimate_cents


def _clear():
    conn = db.get_conn()
    conn.execute("DELETE FROM bill_payments")
    conn.execute("DELETE FROM bills")
    conn.commit()
    conn.close()


def _mk(client, **kw):
    body = {"name": "Test bill", "cycle": "monthly", **kw}
    r = client.post("/api/bills", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _iso(d: date) -> str:
    return d.isoformat()


# ── cycle-advance rules (pure function, deterministic `today`) ────────────────
def test_advance_monthly_month_end_anchor():
    # due day 31: Jan 31 → Feb 28 (clamped), and the anchor survives → Mar 31
    assert advance_due("2026-01-31", "monthly", 31, today=date(2026, 2, 1)) == "2026-02-28"
    assert advance_due("2026-02-28", "monthly", 31, today=date(2026, 3, 1)) == "2026-03-31"
    # leap year February keeps the 29th
    assert advance_due("2024-01-31", "monthly", 31, today=date(2024, 2, 1)) == "2024-02-29"
    # no explicit due_day → anchor inferred from the scheduled date's day
    assert advance_due("2026-01-31", "monthly", None, today=date(2026, 2, 1)) == "2026-02-28"


def test_advance_other_cycles():
    assert advance_due("2026-07-01", "weekly", None, today=date(2026, 7, 2)) == "2026-07-08"
    assert advance_due("2026-01-31", "quarterly", 31, today=date(2026, 2, 1)) == "2026-04-30"
    assert advance_due("2024-02-29", "yearly", 29, today=date(2024, 3, 1)) == "2025-02-28"
    assert advance_due("2026-07-01", "custom-10-days", None, today=date(2026, 7, 2)) == "2026-07-11"
    assert advance_due("2026-07-01", "once", None, today=date(2026, 7, 2)) is None


def test_advance_catches_up_when_long_overdue():
    # 2+ months overdue: keeps stepping from the SCHEDULED date until after today
    assert advance_due("2026-01-31", "monthly", 31, today=date(2026, 4, 10)) == "2026-04-30"
    # lands strictly AFTER today (paying on the clamped due date itself)
    assert advance_due("2026-01-31", "monthly", 31, today=date(2026, 2, 28)) == "2026-03-31"
    # weekly keeps the original weekday: 2026-01-01 is a Thursday, so it lands on Thu Mar 5
    assert advance_due("2026-01-01", "weekly", None, today=date(2026, 3, 1)) == "2026-03-05"


def test_monthly_estimate_factors():
    assert _monthly_estimate_cents(1200, "monthly") == 1200
    assert round(_monthly_estimate_cents(1200, "weekly")) == 5200
    assert _monthly_estimate_cents(1200, "yearly") == 100
    assert _monthly_estimate_cents(1200, "quarterly") == 400
    assert _monthly_estimate_cents(1200, "once") == 0
    assert round(_monthly_estimate_cents(1000, "custom-30-days")) == 1015   # 30.44/30
    assert _monthly_estimate_cents(None, "monthly") == 0


# ── CRUD ──────────────────────────────────────────────────────────────────────
def test_bill_crud(client):
    _clear()
    b = _mk(client, name="Electric", category="utilities", amount_cents=9500,
            next_due="2026-08-31", portal_url="https://example.com/pay",
            extra={"account": "12-345"})
    assert b["amount_cents"] == 9500 and b["active"] is True
    assert b["due_day"] == 31            # anchor defaulted from the due date
    assert b["extra"] == {"account": "12-345"}

    v = _mk(client, name="Water", category="utilities", next_due="2026-08-05")
    assert v["amount_cents"] is None     # variable

    lst = client.get("/api/bills").json()
    assert [x["name"] for x in lst["bills"]] == ["Water", "Electric"]   # soonest due first
    assert lst["counts"] == {"active": 2, "inactive": 0}

    # patch: rename + custom fields + deactivate
    r = client.patch(f"/api/bills/{b['id']}",
                     json={"name": "Electric Co", "extra": {"plan": "budget"}, "active": False})
    assert r.status_code == 200
    up = r.json()
    assert up["name"] == "Electric Co" and up["active"] is False and up["extra"] == {"plan": "budget"}
    assert client.get("/api/bills?active=1").json()["counts"]["inactive"] == 1

    # validation
    assert client.post("/api/bills", json={"name": " "}).status_code == 400
    assert client.post("/api/bills", json={"name": "x", "cycle": "fortnightly"}).status_code == 400
    assert client.post("/api/bills", json={"name": "x", "next_due": "not-a-date"}).status_code == 400
    assert client.patch(f"/api/bills/{b['id']}", json={"cycle": "bogus"}).status_code == 400
    assert client.patch("/api/bills/999999", json={"name": "x"}).status_code == 404

    # delete removes the bill and its payments
    client.post(f"/api/bills/{v['id']}/pay", json={"amount_cents": 4200})
    assert client.delete(f"/api/bills/{v['id']}").status_code == 200
    assert client.get(f"/api/bills/{v['id']}/payments").status_code == 404
    conn = db.get_conn()
    assert conn.execute("SELECT COUNT(*) FROM bill_payments WHERE bill_id=?", (v["id"],)).fetchone()[0] == 0
    conn.close()


# ── mark-paid ─────────────────────────────────────────────────────────────────
def test_mark_paid_advances_and_logs(client):
    _clear()
    today = date.today()
    yesterday = today - timedelta(days=1)
    b = _mk(client, name="Internet", amount_cents=7000, cycle="monthly",
            next_due=_iso(yesterday), due_day=yesterday.day)
    r = client.post(f"/api/bills/{b['id']}/pay", json={"note": "on time-ish"})
    assert r.status_code == 200
    out = r.json()
    assert out["payment"]["amount_cents"] == 7000          # fixed amount auto-filled
    assert out["payment"]["note"] == "on time-ish"
    nd = date.fromisoformat(out["bill"]["next_due"])
    assert nd > today                                       # advanced past today
    assert nd == advance_due(_iso(yesterday), "monthly", yesterday.day, today=today) and nd is not None \
        or True
    assert out["bill"]["next_due"] == advance_due(_iso(yesterday), "monthly", yesterday.day, today=today)
    hist = client.get(f"/api/bills/{b['id']}/payments").json()["payments"]
    assert len(hist) == 1 and hist[0]["paid_at"] == _iso(today)


def test_mark_paid_variable_requires_amount(client):
    _clear()
    v = _mk(client, name="Groceries card", next_due=_iso(date.today()))
    assert client.post(f"/api/bills/{v['id']}/pay", json={}).status_code == 400
    r = client.post(f"/api/bills/{v['id']}/pay", json={"amount_cents": 12345})
    assert r.status_code == 200 and r.json()["payment"]["amount_cents"] == 12345


def test_mark_paid_once_deactivates(client):
    _clear()
    b = _mk(client, name="Car registration", amount_cents=8000, cycle="once",
            next_due=_iso(date.today()))
    out = client.post(f"/api/bills/{b['id']}/pay", json={}).json()
    assert out["bill"]["active"] is False and out["bill"]["next_due"] is None


def test_delete_payment_undo(client):
    _clear()
    b = _mk(client, name="Trash", amount_cents=3000, next_due=_iso(date.today()))
    pid = client.post(f"/api/bills/{b['id']}/pay", json={}).json()["payment"]["id"]
    assert client.delete(f"/api/bills/{b['id']}/payments/{pid}").status_code == 200
    assert client.delete(f"/api/bills/{b['id']}/payments/{pid}").status_code == 404
    assert client.get(f"/api/bills/{b['id']}/payments").json()["payments"] == []


# ── summary ───────────────────────────────────────────────────────────────────
def test_summary_math(client):
    _clear()
    today = date.today()
    _mk(client, name="Rent", amount_cents=1000, cycle="monthly", next_due=_iso(today - timedelta(days=2)))
    _mk(client, name="Gym", amount_cents=2000, cycle="weekly", next_due=_iso(today + timedelta(days=3)))
    _mk(client, name="Insurance", amount_cents=12000, cycle="yearly", next_due=_iso(today + timedelta(days=30)))
    _mk(client, name="Mystery", next_due=_iso(today + timedelta(days=10)))   # variable, no history
    _mk(client, name="Old cable", amount_cents=99999, active=False)          # inactive → excluded

    s = client.get("/api/bills/summary").json()
    assert s["overdue_count"] == 1 and s["overdue"][0]["name"] == "Rent" and s["overdue"][0]["days"] == -2
    assert s["due_soon_count"] == 1 and s["due_soon"][0]["name"] == "Gym" and s["due_soon"][0]["days"] == 3
    # 1000 (monthly) + 2000*52/12 (weekly) + 12000/12 (yearly); variable unknown → excluded but counted
    assert s["monthly_total_cents"] == round(1000 + 2000 * 52 / 12 + 1000)
    assert s["variable_unknown"] == 1
    assert s["active_count"] == 4
    assert s["paid_this_month_cents"] == 0

    # a variable bill WITH history estimates from its last 3 payments
    mystery = [b for b in client.get("/api/bills").json()["bills"] if b["name"] == "Mystery"][0]
    for amt in (1000, 2000, 3000):
        client.post(f"/api/bills/{mystery['id']}/pay", json={"amount_cents": amt})
    s2 = client.get("/api/bills/summary").json()
    assert s2["variable_unknown"] == 0
    assert s2["monthly_total_cents"] == round(1000 + 2000 * 52 / 12 + 1000 + 2000)
    assert s2["paid_this_month_cents"] == 6000 and s2["paid_this_month_count"] == 3


# ── series ────────────────────────────────────────────────────────────────────
def test_series_per_month_and_category(client):
    _clear()
    today = date.today()
    last_month = (today.replace(day=1) - timedelta(days=1))
    a = _mk(client, name="Power", category="utilities", amount_cents=5000, next_due=_iso(today))
    b = _mk(client, name="Netflix", category="fun", amount_cents=1500, next_due=_iso(today))
    client.post(f"/api/bills/{a['id']}/pay", json={"paid_at": _iso(last_month)})
    client.post(f"/api/bills/{a['id']}/pay", json={"paid_at": _iso(today)})
    client.post(f"/api/bills/{b['id']}/pay", json={"paid_at": _iso(today)})

    s = client.get("/api/bills/series?months=3").json()
    assert len(s["months"]) == 3 and s["months"][-1] == _iso(today)[:7]
    assert s["months"][-2] == _iso(last_month)[:7]
    assert s["total_cents"][-1] == 6500 and s["total_cents"][-2] == 5000
    assert s["categories"]["utilities"][-1] == 5000 and s["categories"]["utilities"][-2] == 5000
    assert s["categories"]["fun"][-1] == 1500 and s["categories"]["fun"][-2] == 0


# ── CSV round-trip ────────────────────────────────────────────────────────────
def test_csv_roundtrip(client):
    _clear()
    _mk(client, name="Electric", category="utilities", amount_cents=9550, cycle="monthly",
        next_due="2026-08-31", autopay=True, portal_url="https://example.com/pay",
        portal_note="acct nickname only", extra={"account": "12-345"})
    _mk(client, name="Water", cycle="custom-45-days", next_due="2026-08-05")   # variable amount

    csv_text = client.get("/api/bills/export.csv").text
    assert "Electric" in csv_text and "custom-45-days" in csv_text

    _clear()
    r = client.post("/api/bills/import", json={"csv": csv_text})
    assert r.status_code == 200
    assert r.json() == {"imported": 2, "errors": []}

    bills = {b["name"]: b for b in client.get("/api/bills").json()["bills"]}
    e = bills["Electric"]
    assert e["amount_cents"] == 9550 and e["cycle"] == "monthly" and e["next_due"] == "2026-08-31"
    assert e["due_day"] == 31 and e["autopay"] is True and e["active"] is True
    assert e["portal_url"] == "https://example.com/pay" and e["extra"] == {"account": "12-345"}
    w = bills["Water"]
    assert w["amount_cents"] is None and w["cycle"] == "custom-45-days" and w["next_due"] == "2026-08-05"

    # a bad row is reported and skipped; good rows still import
    bad = "name,amount,cycle,next_due\nGas,10.00,monthly,2026-09-01\n,5.00,monthly,2026-09-02\nX,1.00,bogus,2026-09-03\n"
    out = client.post("/api/bills/import", json={"csv": bad}).json()
    assert out["imported"] == 1 and len(out["errors"]) == 2
    assert client.post("/api/bills/import", json={"csv": "  "}).status_code == 400
