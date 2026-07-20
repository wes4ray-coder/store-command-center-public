"""calendar — 🗓️ one dated view of the whole personal ledger, plus a real
iCalendar export/subscription so the same dates show up in Nextcloud, Thunderbird,
Apple Calendar, GNOME Calendar, DAVx5 … anything that speaks .ics.

The 📆 Bills pane always had a calendar *icon* and no calendar. This module is the
calendar: it derives dated events from the three tables that already exist and
adds NO tables of its own.

  bills          → `bill_due`     (the scheduled obligation, projected forward)
  bill_payments  → `bill_paid`    (money that actually left, logged by bills.py)
  paychecks      → `paycheck`     (money in — ledger.py)
  purchases      → `purchase`     (non-bill money out — ledger.py)

Recurrence: a bill stores ONE `next_due`. To fill a month grid we walk that date
forward with bills.advance_due — the exact same cycle/anchor/clamp logic that
mark-paid uses, called one step at a time (`today=<the date itself>` makes it
advance exactly once). The first occurrence is the REAL stored row
(`projected: false`); everything after it is flagged `projected: true` so the UI
and the reader can tell a scheduled fact from an extrapolation. Nothing here
writes to the DB — projection is pure arithmetic over the stored next_due.

Endpoints
  GET  /api/calendar/events?from=&to=   the events feed the month grid draws
  GET  /api/calendar/export.ics         one-off download of the same events
  GET  /api/calendar/feed               the subscription URL + its token
  POST /api/calendar/feed/rotate        new token — every old URL stops working
  GET  /api/public/calendar.ics?token=  the SUBSCRIBABLE feed (see below)

Security stance for the public feed: `/api/public/*` bypasses the session guard in
main.py (Nextcloud fetches it with no cookie), so the endpoint self-enforces the
token with hmac.compare_digest — the same shape as routers/jellycoin.py's
`_check_miner`, with the token minted on first use and stored Fernet-encrypted in
settings like `_miner_token()`. There is deliberately NO localhost bypass here:
the URL is the only credential, so it must be checked every single time. Anyone
holding that URL can read every amount in this calendar — the UI says so and
tells the owner to keep it on the LAN.

ICS is emitted by hand (no dependency): CRLF line endings, folding at 75 OCTETS,
stable UIDs, all-day VALUE=DATE events, and a real RRULE per recurring bill rather
than thousands of exploded rows. Month-end bills get the closest correct rule —
"due the 31st" becomes BYMONTHDAY=28,29,30,31;BYSETPOS=-1 (last day of the month),
never a plain BYMONTHDAY=31 that would silently skip February.
"""
import hmac as _hmac
import secrets as _secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request, Response

from deps import *          # get_conn, get_setting, logger, PUBLIC_BASE_URL, STORE_BASE
from ._base import router
from .bills import advance_due, _bill_row   # cycle math is REUSED, never reimplemented

# ── tunables ─────────────────────────────────────────────────────────────────
PRODID = "-//Store Command Center//Money Calendar 1.0//EN"
CAL_NAME = "Store — Money"
UID_DOMAIN = "money.store.local"
FEED_TOKEN_KEY = "calendar_feed_token"
FEED_PATH = "/api/public/calendar.ics"

_MAX_RANGE_DAYS = 800        # a sane ceiling on ?from/?to so one call can't spin
_MAX_OCCURRENCES = 400       # per-bill projection hard stop (also the ICS walk)
_ICS_HORIZON_DAYS = 400      # how far the .ics projects one-off/unknown cycles


# ── token (minted on first use, encrypted at rest — cf. jellycoin._miner_token) ─
def _feed_token() -> str:
    tok = get_setting(FEED_TOKEN_KEY)        # get_setting transparently decrypts
    if not tok:
        tok = _new_feed_token()
    return tok


def _new_feed_token() -> str:
    import crypto as _secrets_at_rest        # app/crypto.py — settings encryption
    tok = _secrets.token_urlsafe(24)
    conn = get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (FEED_TOKEN_KEY, _secrets_at_rest.enc(tok)))
        conn.commit()
    finally:
        conn.close()
    return tok


def _check_feed(token: str):
    """The URL is the only credential — no localhost bypass, checked every time."""
    if not token or not _hmac.compare_digest(str(token), _feed_token()):
        raise HTTPException(403, "bad or missing calendar feed token")


# ── date helpers ─────────────────────────────────────────────────────────────
def _d(v, fallback: date) -> date:
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return fallback


def _parse_range(frm: Optional[str], to: Optional[str]):
    """Defaults to the current month ± a little, and never spans more than
    _MAX_RANGE_DAYS (a bad ?from=0001-01-01 must not melt the box)."""
    today = date.today()
    a = _d(frm, today.replace(day=1) - timedelta(days=7))
    b = _d(to, (today.replace(day=1) + timedelta(days=44)).replace(day=1))
    if b < a:
        a, b = b, a
    if (b - a).days > _MAX_RANGE_DAYS:
        b = a + timedelta(days=_MAX_RANGE_DAYS)
    return a, b


def _step(cur: date, cycle: str, due_day) -> Optional[date]:
    """Exactly ONE cycle forward, via bills.advance_due (today=cur ⇒ one step)."""
    nxt = advance_due(cur.isoformat(), cycle, due_day, today=cur)
    if not nxt:
        return None
    try:
        n = date.fromisoformat(nxt)
    except (ValueError, TypeError):
        return None
    return n if n > cur else None       # paranoia: never loop on a no-op step


def occurrences(next_due: str, cycle: str, due_day, upto: date,
                limit: int = _MAX_OCCURRENCES):
    """Every scheduled date from `next_due` through `upto`, inclusive.

    Yields (date, projected) — the stored next_due is projected=False, each
    walked-forward date is projected=True.
    """
    start = _d(next_due, None) if next_due else None
    if not start:
        return
    cur, i = start, 0
    while cur <= upto and i < limit:
        yield cur, (i > 0)
        nxt = _step(cur, cycle, due_day)
        if not nxt:
            return
        cur, i = nxt, i + 1


# ── event building ───────────────────────────────────────────────────────────
def _due_state(day: date, today: date, paid: bool) -> str:
    if paid:
        return "paid"
    if day < today:
        return "overdue"
    if day == today:
        return "due_today"
    return "upcoming"


def collect_events(frm: date, to: date, include_projected: bool = True,
                   include_budget: bool = True) -> list:
    """Every dated event between frm and to, from all three sources.

    Deliberately read-only and tolerant: a missing/empty table just contributes
    nothing, so an install with no data gets a friendly empty month, not a 500.
    """
    today = date.today()
    out = []
    conn = get_conn()
    try:
        # 1) bills due — the stored next_due plus projected future occurrences
        try:
            bills = [_bill_row(r) for r in
                     conn.execute("SELECT * FROM bills WHERE active=1").fetchall()]
        except Exception:
            bills = []
        for b in bills:
            if not b.get("next_due"):
                continue
            # A due date on/before today counts as paid if a payment for this bill
            # was logged on or after it (an early/manual pay that never advanced).
            try:
                last_paid = conn.execute(
                    "SELECT MAX(paid_at) FROM bill_payments WHERE bill_id=?",
                    (b["id"],)).fetchone()[0]
            except Exception:
                last_paid = None
            for day, projected in occurrences(b["next_due"], b.get("cycle") or "monthly",
                                              b.get("due_day"), to):
                if projected and not include_projected:
                    break
                if day < frm:
                    continue
                paid = bool(last_paid and day <= today and str(last_paid)[:10] >= day.isoformat())
                out.append({
                    "id": f"bill-{b['id']}-{day.isoformat()}",
                    "type": "bill_due",
                    "date": day.isoformat(),
                    "title": b.get("name") or "Bill",
                    "amount_cents": b.get("amount_cents"),
                    "category": b.get("category") or "",
                    "direction": "out",
                    "projected": projected,
                    "state": _due_state(day, today, paid),
                    "bill_id": b["id"],
                    "cycle": b.get("cycle") or "monthly",
                    "autopay": bool(b.get("autopay")),
                    "notes": b.get("portal_note") or "",
                })

        # 2) bill payments actually made
        for r in _rows(conn, "SELECT p.id AS id, p.paid_at AS d, p.amount_cents AS amt, "
                             "p.note AS note, b.name AS name, b.category AS cat "
                             "FROM bill_payments p LEFT JOIN bills b ON b.id=p.bill_id "
                             "WHERE p.paid_at >= ? AND p.paid_at <= ?", (frm.isoformat(), to.isoformat())):
            out.append({
                "id": f"billpay-{r['id']}", "type": "bill_paid", "date": str(r["d"])[:10],
                "title": r["name"] or "Bill payment", "amount_cents": r["amt"],
                "category": r["cat"] or "", "direction": "out", "projected": False,
                "state": "paid", "notes": r["note"] or "",
            })

        # 3) paychecks in
        for r in _rows(conn, "SELECT id, received_at AS d, amount_cents AS amt, source, notes "
                             "FROM paychecks WHERE received_at >= ? AND received_at <= ?",
                       (frm.isoformat(), to.isoformat())):
            out.append({
                "id": f"paycheck-{r['id']}", "type": "paycheck", "date": str(r["d"])[:10],
                "title": r["source"] or "Paycheck", "amount_cents": r["amt"],
                "category": "income", "direction": "in", "projected": False,
                "state": "received", "notes": r["notes"] or "",
            })

        # 4) purchases out
        for r in _rows(conn, "SELECT id, purchased_at AS d, amount_cents AS amt, merchant, "
                             "category AS cat, notes FROM purchases "
                             "WHERE purchased_at >= ? AND purchased_at <= ?",
                       (frm.isoformat(), to.isoformat())):
            out.append({
                "id": f"purchase-{r['id']}", "type": "purchase", "date": str(r["d"])[:10],
                "title": r["merchant"] or "Purchase", "amount_cents": r["amt"],
                "category": r["cat"] or "", "direction": "out", "projected": False,
                "state": "spent", "notes": r["notes"] or "",
            })
    finally:
        conn.close()

    # 5) budget markers + consumption predictions (routers/money/budget.py).
    #    Imported LAZILY so the import graph stays one-way: budget.py imports this
    #    module for the bill projection, never the other way round at import time.
    #    Failure here must never take the calendar down — the money rows above are
    #    facts, these are a derived layer on top.
    #
    #    `include_budget=False` is REQUIRED by budget.py's own bill-projection call.
    #    Without it the two modules recurse: collect_events → budget events →
    #    compute_period → the bill projection → collect_events → … Each level is
    #    caught by the except below, so it terminates and looks correct in a small
    #    test, while quietly doing exponential work — the .ics export (which spans
    #    400 days of biweekly periods) simply never returned.
    if include_projected and include_budget:
        try:
            from .budget import budget_calendar_events
            out.extend(budget_calendar_events(frm, to, today=today))
        except Exception as e:      # pragma: no cover — defensive
            logger.warning(f"calendar: budget events unavailable ({e}); skipping them")

    _ORDER = {"budget_period": 0, "savings_target": 1, "paycheck": 2, "bill_due": 3,
              "bill_paid": 4, "grocery_day": 5, "restock": 6, "purchase": 7,
              "safe_to_spend": 8}
    out.sort(key=lambda e: (e["date"], _ORDER.get(e["type"], 9), str(e["title"]).lower()))
    return out


def _rows(conn, sql, args=()):
    """A query that must never take the whole calendar down (table may be empty
    or, on a very old install, not yet created)."""
    try:
        return conn.execute(sql, args).fetchall()
    except Exception as e:      # pragma: no cover — defensive
        logger.warning(f"calendar: query failed ({e}); skipping that source")
        return []


# Derived budget/prediction markers. They are NOT money movements — a restock
# guess or a safe-to-spend figure must never be summed into an income/outgoings
# total, and the budget_period marker restates income that the paycheck rows
# already carry. Excluded from every total below; counted separately.
BUDGET_EVENT_TYPES = ("budget_period", "savings_target", "safe_to_spend",
                      "restock", "grocery_day")


def _totals(events: list) -> dict:
    money = [e for e in events if e["type"] not in BUDGET_EVENT_TYPES]
    inc = sum(e["amount_cents"] or 0 for e in money if e["direction"] == "in")
    spent = sum(e["amount_cents"] or 0 for e in money
                if e["direction"] == "out" and e["type"] != "bill_due")
    due = sum(e["amount_cents"] or 0 for e in money if e["type"] == "bill_due")
    return {"income_cents": inc, "outgoings_cents": spent, "net_cents": inc - spent,
            "due_cents": due,
            "counts": {k: sum(1 for e in events if e["type"] == k)
                       for k in ("bill_due", "bill_paid", "paycheck", "purchase",
                                 *BUDGET_EVENT_TYPES)}}


# ── events API ───────────────────────────────────────────────────────────────
@router.get("/api/calendar/events")
def calendar_events(request: Request, projected: int = 1):
    """Dated events across bills, bill payments, paychecks and purchases.

    Query: ?from=YYYY-MM-DD&to=YYYY-MM-DD (both optional; defaults to a window
    around the current month). `from`/`to` are read off the request because
    `from` is a Python keyword.
    """
    q = request.query_params
    frm, to = _parse_range(q.get("from"), q.get("to"))
    events = collect_events(frm, to, include_projected=bool(projected))
    return {"from": frm.isoformat(), "to": to.isoformat(), "today": date.today().isoformat(),
            "events": events, "totals": _totals(events)}


# ══ iCalendar ═════════════════════════════════════════════════════════════════
def _esc(s) -> str:
    """RFC 5545 TEXT escaping: backslash, semicolon, comma, newline."""
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
            .replace("\r", "\\n"))


def fold(line: str) -> str:
    """Fold a content line at 75 OCTETS (not characters), continuations prefixed
    with one space, per RFC 5545 §3.1. Multi-byte characters are never split."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur, limit = [], b"", 75
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > limit:
            parts.append(cur.decode("utf-8"))
            cur, limit = b, 74          # continuations carry a leading space
        else:
            cur += b
    if cur:
        parts.append(cur.decode("utf-8"))
    return parts[0] + "".join("\r\n " + p for p in parts[1:])


def _usd(c) -> str:
    return "" if c in (None, "") else f"${(int(c) / 100):.2f}"


def _rrule(cycle: str, start: date, due_day) -> Optional[str]:
    """The recurrence rule for a bill cycle, or None for one-offs.

    Month-anchored cycles clamp to the month's length in advance_due (due day 31
    → Feb 28). A plain BYMONTHDAY=31 would instead SKIP short months, so days
    29-31 become "the last of these days that exists this month":
        31 → BYMONTHDAY=28,29,30,31;BYSETPOS=-1   (= last day of the month)
        30 → BYMONTHDAY=28,29,30;BYSETPOS=-1
        29 → BYMONTHDAY=28,29;BYSETPOS=-1         (Feb 29 in leap years, 28 otherwise)
    which reproduces advance_due exactly.
    """
    from .bills import _custom_days
    day = int(due_day) if due_day else start.day

    def _bymonthday() -> str:
        if day >= 29:
            days = ",".join(str(x) for x in range(28, min(day, 31) + 1))
            return f"BYMONTHDAY={days};BYSETPOS=-1"
        return f"BYMONTHDAY={day}"

    if cycle == "weekly":
        return "FREQ=WEEKLY;INTERVAL=1;BYDAY=" + ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][start.weekday()]
    if cycle == "monthly":
        return "FREQ=MONTHLY;INTERVAL=1;" + _bymonthday()
    if cycle == "quarterly":
        return "FREQ=MONTHLY;INTERVAL=3;" + _bymonthday()
    if cycle == "yearly":
        return f"FREQ=YEARLY;INTERVAL=1;BYMONTH={start.month};" + _bymonthday()
    n = _custom_days(cycle)
    if n:
        return f"FREQ=DAILY;INTERVAL={n}"
    return None                                   # 'once' / unknown → single event


def _vevent(uid: str, day: date, summary: str, description: str,
            dtstamp: str, categories: str = "", rrule: Optional[str] = None,
            transp: str = "TRANSPARENT") -> list:
    """One all-day VEVENT as a list of UNFOLDED content lines."""
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{_esc(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    if categories:
        lines.append(f"CATEGORIES:{_esc(categories)}")
    if rrule:
        lines.append(f"RRULE:{rrule}")
    lines += [f"TRANSP:{transp}", "END:VEVENT"]
    return lines


def build_ics(frm: date, to: date, name: str = CAL_NAME) -> str:
    """The whole calendar as an iCalendar document (CRLF, folded at 75 octets).

    Recurring bills are emitted ONCE with an RRULE — never exploded into a row
    per occurrence — so a decade of monthly bills is one VEVENT, not 120.
    """
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(name)}",
        "X-WR-CALDESC:Bills due, bill payments, paychecks and purchases from the Store "
        "Command Center money ledger.",
        "X-PUBLISHED-TTL:PT6H",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
    ]

    conn = get_conn()
    try:
        try:
            bills = [_bill_row(r) for r in
                     conn.execute("SELECT * FROM bills WHERE active=1").fetchall()]
        except Exception:
            bills = []
    finally:
        conn.close()

    # 1) bills — one VEVENT each, with a real RRULE for recurring cycles.
    for b in bills:
        nd = b.get("next_due")
        if not nd:
            continue
        start = _d(nd, None)
        if not start:
            continue
        cycle = b.get("cycle") or "monthly"
        rule = _rrule(cycle, start, b.get("due_day"))
        amt = _usd(b.get("amount_cents"))
        summary = f"{b.get('name') or 'Bill'} due" + (f" — {amt}" if amt else " — amount varies")
        desc = " | ".join(x for x in [
            f"Category: {b.get('category') or 'uncategorized'}",
            f"Cycle: {cycle}",
            "Autopay: yes" if b.get("autopay") else None,
            f"Portal: {b.get('portal_url')}" if b.get("portal_url") else None,
            b.get("portal_note") or None,
        ] if x)
        if rule:
            lines += _vevent(f"bill-{b['id']}@{UID_DOMAIN}", start, summary, desc,
                             dtstamp, b.get("category") or "bill", rule)
        else:
            # 'once' (or an unknown cycle): a single dated event, no RRULE.
            lines += _vevent(f"bill-{b['id']}@{UID_DOMAIN}", start, summary, desc,
                             dtstamp, b.get("category") or "bill")

    # 2) the things that actually happened, inside the requested window.
    _VERB = {"bill_paid": "paid", "paycheck": "received", "purchase": ""}
    _ICON = {"bill_paid": "Paid", "paycheck": "Paycheck", "purchase": "Purchase"}
    for e in collect_events(frm, to, include_projected=False):
        if e["type"] == "bill_due":
            continue                       # already covered by the RRULE events above
        if e["type"] in BUDGET_EVENT_TYPES:
            continue                       # emitted below, from the projected pass
        amt = _usd(e.get("amount_cents"))
        verb = _VERB.get(e["type"], "")
        icon = _ICON.get(e["type"], e["type"].replace("_", " ").title())
        summary = f"{icon}: {e['title']}" + (f" — {amt}" if amt else "")
        desc = " | ".join(x for x in [
            f"Category: {e.get('category') or 'uncategorized'}",
            f"Status: {verb}" if verb else None,
            e.get("notes") or None,
        ] if x)
        uid = f"{e['id']}@{UID_DOMAIN}"
        lines += _vevent(uid, _d(e["date"], frm), summary, desc, dtstamp,
                         e.get("category") or e["type"])

    # 3) budget markers + predicted restocks. These are PROJECTED by nature, so
    #    they come from the projected pass (the loop above deliberately runs with
    #    include_projected=False and skips them). Each summary says out loud that
    #    it is a prediction — a subscriber glancing at their phone must never read
    #    "milk likely out" as a fact the way "Paid: …" is one.
    _BUDGET_LABEL = {
        "budget_period": "Budget", "savings_target": "Save",
        "safe_to_spend": "Safe to spend", "restock": "Predicted",
        "grocery_day": "Shopping",
    }
    for e in collect_events(frm, to, include_projected=True):
        if e["type"] not in BUDGET_EVENT_TYPES:
            continue
        amt = _usd(e.get("amount_cents"))
        summary = f"{_BUDGET_LABEL.get(e['type'], 'Budget')}: {e['title']}" \
                  + (f" — {amt}" if amt else "")
        desc = " | ".join(x for x in [
            ("PREDICTED from your own purchase history — not a scheduled fact"
             if e.get("projected") else None),
            e.get("notes") or None,
            f"Category: {e.get('category') or 'budget'}",
        ] if x)
        lines += _vevent(f"{e['id']}@{UID_DOMAIN}", _d(e["date"], frm), summary, desc,
                         dtstamp, e["type"])

    lines.append("END:VCALENDAR")
    return "".join(fold(ln) + "\r\n" for ln in lines)


def _ics_response(frm: date, to: date, filename: str) -> Response:
    return Response(build_ics(frm, to), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})


@router.get("/api/calendar/export.ics")
def calendar_export(request: Request):
    """One-off download. Same events as /api/calendar/events; session-guarded."""
    q = request.query_params
    frm, to = _parse_range(q.get("from"), q.get("to") or
                           (date.today() + timedelta(days=_ICS_HORIZON_DAYS)).isoformat())
    return _ics_response(frm, to, "store-money.ics")


@router.get(FEED_PATH)
def calendar_feed(token: str = ""):
    """The SUBSCRIBABLE feed. Lives under /api/public/, which main.py lets past the
    session guard, so the token in the URL is the entire access control — checked
    here on every request with hmac.compare_digest, no localhost exemption."""
    _check_feed(token)
    today = date.today()
    return _ics_response(today - timedelta(days=365),
                         today + timedelta(days=_ICS_HORIZON_DAYS), "store-money.ics")


@router.get("/api/calendar/feed")
def calendar_feed_info():
    """The URL to paste into Nextcloud (Calendar → New calendar → subscription).

    `path` is relative so the UI can build a SAME-ORIGIN (LAN) URL; `url` is the
    public-hostname form for the rare case the store is reachable from outside.
    Anyone with either URL can read every amount in the calendar.
    """
    tok = _feed_token()
    return {"path": f"{STORE_BASE}{FEED_PATH}?token={tok}",
            "url": f"{PUBLIC_BASE_URL}{STORE_BASE}{FEED_PATH}?token={tok}",
            "token": tok,
            "warning": ("This link needs no password — anyone who has it can read every "
                        "bill, paycheck and purchase amount in this calendar. Keep it on "
                        "your local network and rotate it if it ever leaks.")}


@router.post("/api/calendar/feed/rotate")
def calendar_feed_rotate():
    """Mint a new token. Every previously-shared URL stops working immediately."""
    tok = _new_feed_token()
    logger.info("calendar: feed token rotated — old subscription URLs are now dead")
    return {"ok": True, "path": f"{STORE_BASE}{FEED_PATH}?token={tok}",
            "url": f"{PUBLIC_BASE_URL}{STORE_BASE}{FEED_PATH}?token={tok}", "token": tok}
