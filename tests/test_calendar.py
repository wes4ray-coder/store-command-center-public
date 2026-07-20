"""🗓️ money calendar (routers/money/calendar.py — /api/calendar/*).

Locks down:
  • event aggregation across ALL THREE sources (bills due, bill_payments,
    paychecks, purchases) with the right direction/type/amount per row
  • recurrence PROJECTION inside a range — the stored next_due comes back
    projected:false, walked-forward dates projected:true, and the walk uses the
    same month-end anchor as bills.advance_due (31 → Feb 28 → Mar 31)
  • ICS structure: CRLF everywhere, folding at 75 OCTETS, stable UIDs across
    calls, a real RRULE for recurring bills (and the BYSETPOS month-end rule),
    all-day VALUE=DATE, VERSION/PRODID/X-WR-CALNAME
  • the public subscription feed's token: missing/wrong rejected, right accepted,
    and rotation killing the old one

No `icalendar` package is available in the venv and we do NOT add a dependency —
the ICS is parsed back with the small unfolder below, which implements RFC 5545
§3.1 folding in reverse and is itself asserted against the raw octet lengths.

Sibling of tests/test_bills.py and tests/test_money_ledger.py.
"""
from datetime import date, timedelta

import db
from routers.money.calendar import fold, occurrences, _rrule


def _clear():
    conn = db.get_conn()
    for t in ("bill_payments", "bills", "paychecks", "purchases"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()


def _iso(d: date) -> str:
    return d.isoformat()


def _mk_bill(client, **kw):
    body = {"name": "Electric", "cycle": "monthly", "amount_cents": 12000,
            "category": "utilities", **kw}
    r = client.post("/api/bills", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _events(client, frm, to, **q):
    qs = "&".join([f"from={frm}", f"to={to}"] + [f"{k}={v}" for k, v in q.items()])
    r = client.get(f"/api/calendar/events?{qs}")
    assert r.status_code == 200, r.text
    return r.json()


# ══ ICS line folding (pure function — the fiddly bit worth nailing) ══════════
def test_fold_at_75_octets():
    short = "SUMMARY:hello"
    assert fold(short) == short                       # under the limit, untouched

    long = "DESCRIPTION:" + ("x" * 200)
    folded = fold(long)
    parts = folded.split("\r\n")
    assert len(parts) > 1
    # first line ≤ 75 octets; continuations carry a leading space and are ≤ 75 too
    assert len(parts[0].encode()) <= 75
    for p in parts[1:]:
        assert p.startswith(" ")
        assert len(p.encode()) <= 75
    # unfolding restores the original exactly
    assert parts[0] + "".join(p[1:] for p in parts[1:]) == long


def test_fold_never_splits_a_multibyte_char():
    line = "SUMMARY:" + ("é" * 80)                    # 2 octets each
    folded = fold(line)
    for p in folded.split("\r\n"):
        assert len(p.encode()) <= 75
        p.encode().decode("utf-8")                    # would raise if split mid-char
    parts = folded.split("\r\n")
    assert parts[0] + "".join(p[1:] for p in parts[1:]) == line


# ══ recurrence projection (pure) ════════════════════════════════════════════
def test_occurrences_walk_uses_the_bills_month_end_anchor():
    got = list(occurrences("2026-01-31", "monthly", 31, date(2026, 4, 30)))
    assert [d.isoformat() for d, _ in got] == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]
    # only the stored next_due is real; the rest are extrapolations
    assert [p for _, p in got] == [False, True, True, True]


def test_occurrences_once_yields_a_single_date():
    got = list(occurrences("2026-07-10", "once", None, date(2027, 1, 1)))
    assert [d.isoformat() for d, _ in got] == ["2026-07-10"]


def test_occurrences_weekly_and_custom():
    wk = [d.isoformat() for d, _ in occurrences("2026-07-01", "weekly", None, date(2026, 7, 22))]
    assert wk == ["2026-07-01", "2026-07-08", "2026-07-15", "2026-07-22"]
    cu = [d.isoformat() for d, _ in occurrences("2026-07-01", "custom-10-days", None, date(2026, 7, 21))]
    assert cu == ["2026-07-01", "2026-07-11", "2026-07-21"]


def test_rrule_month_end_uses_bysetpos_not_a_skipping_bymonthday():
    # day 31 must mean "last day of the month", never a BYMONTHDAY=31 that skips Feb
    r = _rrule("monthly", date(2026, 1, 31), 31)
    assert r == "FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
    assert _rrule("monthly", date(2026, 1, 30), 30) == "FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=28,29,30;BYSETPOS=-1"
    assert _rrule("monthly", date(2026, 1, 29), 29) == "FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=28,29;BYSETPOS=-1"
    # a safe day is a plain rule
    assert _rrule("monthly", date(2026, 1, 15), 15) == "FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=15"
    assert _rrule("weekly", date(2026, 7, 1), None) == "FREQ=WEEKLY;INTERVAL=1;BYDAY=WE"
    assert _rrule("quarterly", date(2026, 1, 15), 15).startswith("FREQ=MONTHLY;INTERVAL=3;")
    assert _rrule("yearly", date(2026, 3, 15), 15) == "FREQ=YEARLY;INTERVAL=1;BYMONTH=3;BYMONTHDAY=15"
    assert _rrule("custom-10-days", date(2026, 7, 1), None) == "FREQ=DAILY;INTERVAL=10"
    assert _rrule("once", date(2026, 7, 1), None) is None


# ══ events API ══════════════════════════════════════════════════════════════
def test_empty_range_is_a_friendly_empty_month_not_an_error(client):
    _clear()
    j = _events(client, "2030-01-01", "2030-01-31")
    assert j["events"] == []
    assert j["totals"]["income_cents"] == 0 and j["totals"]["net_cents"] == 0
    assert j["from"] == "2030-01-01" and j["to"] == "2030-01-31"


def test_events_aggregate_all_three_sources(client):
    _clear()
    today = date.today()
    b = _mk_bill(client, next_due=_iso(today + timedelta(days=3)))
    client.post(f"/api/bills/{b['id']}/pay", json={"amount_cents": 11000,
                                                   "paid_at": _iso(today - timedelta(days=1))})
    client.post("/api/ledger/paychecks", json={"source": "Client A", "amount_cents": 250000,
                                               "received_at": _iso(today)})
    client.post("/api/ledger/purchases", json={"merchant": "Hardware store", "amount_cents": 4500,
                                               "category": "tools", "purchased_at": _iso(today)})

    # the window reaches past one full cycle: marking the bill paid pushed its
    # next_due a month out, and that projected due date must still be in range
    frm, to = _iso(today - timedelta(days=20)), _iso(today + timedelta(days=45))
    j = _events(client, frm, to)
    by_type = {}
    for e in j["events"]:
        by_type.setdefault(e["type"], []).append(e)

    assert len(by_type["paycheck"]) == 1
    assert by_type["paycheck"][0]["direction"] == "in"
    assert by_type["paycheck"][0]["amount_cents"] == 250000
    assert by_type["paycheck"][0]["id"].startswith("paycheck-")

    assert len(by_type["purchase"]) == 1
    assert by_type["purchase"][0]["direction"] == "out"
    assert by_type["purchase"][0]["category"] == "tools"

    assert len(by_type["bill_paid"]) == 1
    assert by_type["bill_paid"][0]["amount_cents"] == 11000
    assert by_type["bill_paid"][0]["title"] == "Electric"

    assert by_type["bill_due"], "the bill's own due dates must be in the calendar"
    assert all(e["category"] == "utilities" for e in by_type["bill_due"])

    t = j["totals"]
    assert t["income_cents"] == 250000
    assert t["outgoings_cents"] == 4500 + 11000          # purchase + bill payment
    assert t["net_cents"] == 250000 - 15500
    assert t["counts"]["paycheck"] == 1

    # every event carries a stable, unique id
    ids = [e["id"] for e in j["events"]]
    assert len(ids) == len(set(ids))
    again = _events(client, frm, to)
    assert [e["id"] for e in again["events"]] == ids


def test_recurring_bill_is_projected_across_the_range(client):
    _clear()
    _mk_bill(client, name="Rent", cycle="monthly", next_due="2026-09-05", due_day=5,
             amount_cents=90000)
    j = _events(client, "2026-09-01", "2026-12-31")
    dues = [e for e in j["events"] if e["type"] == "bill_due"]
    assert [e["date"] for e in dues] == ["2026-09-05", "2026-10-05", "2026-11-05", "2026-12-05"]
    assert dues[0]["projected"] is False              # the stored next_due
    assert all(e["projected"] for e in dues[1:])      # everything after it is extrapolated
    assert all(e["amount_cents"] == 90000 for e in dues)
    assert all(e["bill_id"] == dues[0]["bill_id"] for e in dues)
    # projected=0 turns the extrapolation off entirely
    only_real = _events(client, "2026-09-01", "2026-12-31", projected=0)
    assert [e["date"] for e in only_real["events"] if e["type"] == "bill_due"] == ["2026-09-05"]


def test_bill_due_states(client):
    _clear()
    today = date.today()
    _mk_bill(client, name="Late one", next_due=_iso(today - timedelta(days=5)))
    _mk_bill(client, name="Today one", next_due=_iso(today))
    _mk_bill(client, name="Later one", next_due=_iso(today + timedelta(days=9)))
    j = _events(client, _iso(today - timedelta(days=10)), _iso(today + timedelta(days=10)))
    state = {e["title"]: e["state"] for e in j["events"]
             if e["type"] == "bill_due" and not e["projected"]}
    assert state["Late one"] == "overdue"
    assert state["Today one"] == "due_today"
    assert state["Later one"] == "upcoming"


def test_inactive_bills_are_left_out(client):
    _clear()
    b = _mk_bill(client, name="Cancelled", next_due=_iso(date.today() + timedelta(days=2)))
    client.patch(f"/api/bills/{b['id']}", json={"active": False})
    j = _events(client, _iso(date.today()), _iso(date.today() + timedelta(days=5)))
    assert not [e for e in j["events"] if e["type"] == "bill_due"]


# ══ ICS document ════════════════════════════════════════════════════════════
def _unfold(text: str) -> list:
    """RFC 5545 §3.1 unfolding: a line starting with space/tab continues the last."""
    assert "\r\n" in text, "ICS must use CRLF line endings"
    assert text.replace("\r\n", "").count("\n") == 0, "no bare LF allowed"
    out = []
    for raw in text.split("\r\n"):
        if raw == "":
            continue
        assert len(raw.encode()) <= 75, f"content line over 75 octets: {raw[:40]!r}"
        if raw[0] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _props(lines):
    d = {}
    for ln in lines:
        k, _, v = ln.partition(":")
        d.setdefault(k.split(";")[0], []).append(v)
    return d


def test_ics_structure_and_rrule(client):
    _clear()
    _mk_bill(client, name="Water bill with a deliberately long name so the summary line "
                          "must be folded by the exporter at seventy five octets",
             cycle="monthly", next_due="2026-08-31", due_day=31, amount_cents=8350,
             category="utilities")
    r = client.get("/api/calendar/export.ics")
    assert r.status_code == 200
    assert "text/calendar" in r.headers["content-type"]
    text = r.text
    lines = _unfold(text)

    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-1] == "END:VCALENDAR"
    p = _props(lines)
    assert p["VERSION"] == ["2.0"]
    assert p["PRODID"] and "Store Command Center" in p["PRODID"][0]
    assert p["X-WR-CALNAME"], "the calendar needs a display name for Nextcloud"
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") >= 1

    # all-day dates, not timestamps
    assert any(ln.startswith("DTSTART;VALUE=DATE:2026") for ln in lines)
    assert not any(ln.startswith("DTSTART:") for ln in lines)
    assert p["DTSTAMP"] and p["DTSTAMP"][0].endswith("Z")

    # the recurring bill is ONE event with an RRULE, not an exploded series
    assert p["RRULE"] == ["FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"]
    assert lines.count("BEGIN:VEVENT") == 1

    # summary carries the amount; the long line really did get folded
    assert any("$83.50" in ln for ln in lines)
    assert "\r\n " in text
    assert any(ln.startswith("DESCRIPTION:") and "utilities" in ln for ln in lines)


def test_ics_uids_are_stable_across_calls(client):
    _clear()
    today = date.today()
    b = _mk_bill(client, next_due=_iso(today + timedelta(days=4)))
    client.post(f"/api/bills/{b['id']}/pay", json={"amount_cents": 12000, "paid_at": _iso(today)})
    client.post("/api/ledger/paychecks", json={"source": "Client A", "amount_cents": 1000,
                                               "received_at": _iso(today)})
    uids = lambda: [ln for ln in _unfold(client.get("/api/calendar/export.ics").text)
                    if ln.startswith("UID:")]
    first = uids()
    assert first == uids(), "UIDs must not change between renders or every sync duplicates"
    assert len(first) == len(set(first)), "UIDs must be unique"
    assert any(u.startswith("UID:bill-") for u in first)
    assert any(u.startswith("UID:paycheck-") for u in first)
    assert all("@" in u for u in first)


def test_ics_with_no_data_is_still_a_valid_calendar(client):
    _clear()
    lines = _unfold(client.get("/api/calendar/export.ics").text)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    assert "BEGIN:VEVENT" not in lines


def test_ics_escapes_text(client):
    _clear()
    _mk_bill(client, name="Comma, semi; and \\ backslash", next_due="2026-08-10")
    lines = _unfold(client.get("/api/calendar/export.ics").text)
    summary = next(ln for ln in lines if ln.startswith("SUMMARY:"))
    assert "\\," in summary and "\\;" in summary and "\\\\" in summary


# ══ public feed token ═══════════════════════════════════════════════════════
def _feed(client):
    r = client.get("/api/calendar/feed")
    assert r.status_code == 200, r.text
    return r.json()


def test_feed_info_shape_and_warning(client):
    j = _feed(client)
    assert j["token"] and len(j["token"]) >= 20
    assert j["path"].startswith("/api/public/calendar.ics?token=") or "/api/public/calendar.ics?token=" in j["path"]
    assert j["token"] in j["path"] and j["token"] in j["url"]
    assert "anyone" in j["warning"].lower()


def test_feed_rejects_missing_and_wrong_token(client):
    _feed(client)
    assert client.get("/api/public/calendar.ics").status_code == 403
    assert client.get("/api/public/calendar.ics?token=").status_code == 403
    assert client.get("/api/public/calendar.ics?token=nope").status_code == 403


def test_feed_accepts_the_right_token(client):
    tok = _feed(client)["token"]
    r = client.get(f"/api/public/calendar.ics?token={tok}")
    assert r.status_code == 200
    assert "text/calendar" in r.headers["content-type"]
    assert _unfold(r.text)[0] == "BEGIN:VCALENDAR"


def test_rotation_invalidates_the_old_token(client):
    old = _feed(client)["token"]
    assert client.get(f"/api/public/calendar.ics?token={old}").status_code == 200

    r = client.post("/api/calendar/feed/rotate")
    assert r.status_code == 200, r.text
    new = r.json()["token"]
    assert new != old

    assert client.get(f"/api/public/calendar.ics?token={old}").status_code == 403
    assert client.get(f"/api/public/calendar.ics?token={new}").status_code == 200
    assert _feed(client)["token"] == new     # the info endpoint reports the new one
