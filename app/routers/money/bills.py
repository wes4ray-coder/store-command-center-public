"""money — 📆 REAL personal bills tracker (Finance → Bills pane).

Track actual household bills: the biller's portal link, fixed or variable amount,
due dates on any cycle, autopay flag, what's been paid, payment history, and
per-month spending series for the graphs. Flexible by design — free-text
categories and an `extra` JSON column of arbitrary user-defined key/values, so
retail installs can track whatever their bills need without schema changes.

Security stance: NO passwords/credentials are stored — portal_url + notes only.
If you ever need a secret near a bill, put it in Settings (those are Fernet-
encrypted at rest via crypto.SECRET_KEYS), not in a bill note.

NOT the game world's in-game bills (world_bills.py) — completely unrelated.

Cycle-advance rules (mark-paid moves next_due forward):
  weekly          +7 days
  monthly         +1 month, day clamped to the month's length but anchored on
                  `due_day` — a bill due the 31st goes Jan 31 → Feb 28 → Mar 31
  quarterly       +3 months, same due_day anchor/clamp
  yearly          +12 months, same anchor/clamp (Feb 29 → Feb 28 off-leap-years)
  custom-N-days   +N days
  once            no next date; the bill auto-deactivates when paid
If the bill was overdue by more than one cycle, advancing repeats from the
scheduled date until the result lands strictly after today (catch-up).
"""
import csv as _csv
import io as _io
import json as _json
import re as _re
from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException, Body
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from deps import *          # get_conn, logger, …
from ._base import router

# ── schema (defined in db_schema.py; ensured once here at import, exactly like
#    the money package's own _base._ensure_schema) ────────────────────────────
from db_schema import create_bills_tables as _create_bills_tables


def _ensure_bills_schema():
    conn = get_conn()
    try:
        _create_bills_tables(conn)   # commits internally
    finally:
        conn.close()


_ensure_bills_schema()


# ── cycles ────────────────────────────────────────────────────────────────────
CYCLES = ("monthly", "weekly", "yearly", "quarterly", "once")
_CUSTOM_RE = _re.compile(r"^custom-(\d{1,4})-days$")

# average days per month — used only for the monthly-cost estimate of custom cycles
_AVG_MONTH_DAYS = 30.44
_MONTHLY_FACTOR = {"monthly": 1.0, "weekly": 52.0 / 12.0, "yearly": 1.0 / 12.0,
                   "quarterly": 1.0 / 3.0, "once": 0.0}


def _valid_cycle(cycle: str) -> bool:
    return cycle in CYCLES or bool(_CUSTOM_RE.match(cycle or ""))


def _custom_days(cycle: str) -> Optional[int]:
    m = _CUSTOM_RE.match(cycle or "")
    if not m:
        return None
    n = int(m.group(1))
    return n if n > 0 else None


def _add_months(d: date, n: int, anchor_day: int) -> date:
    """d + n months, day = min(anchor_day, length of target month)."""
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, min(max(1, anchor_day), monthrange(y, m)[1]))


def advance_due(next_due: str, cycle: str, due_day: Optional[int] = None,
                today: Optional[date] = None) -> Optional[str]:
    """The next scheduled date after a payment. None for 'once' (no next date).

    Steps from the SCHEDULED date (not the payment date) so the cadence never
    drifts; repeats until strictly after `today` so a long-overdue bill catches
    up in one mark-paid. The due_day anchor keeps month-end bills honest:
    due_day=31 → Jan 31, Feb 28, Mar 31 (clamped per month, never sliding to 28).
    """
    if cycle == "once":
        return None
    try:
        d = date.fromisoformat(str(next_due)[:10])
    except (ValueError, TypeError):
        d = today or date.today()
    today = today or date.today()
    anchor = int(due_day) if due_day else d.day
    ndays = _custom_days(cycle)
    for _ in range(1200):                      # hard stop; 1200 weekly steps ≈ 23y
        if cycle == "weekly":
            d = d + timedelta(days=7)
        elif cycle == "monthly":
            d = _add_months(d, 1, anchor)
        elif cycle == "quarterly":
            d = _add_months(d, 3, anchor)
        elif cycle == "yearly":
            d = _add_months(d, 12, anchor)
        elif ndays:
            d = d + timedelta(days=ndays)
        else:
            return None                        # unknown cycle — leave unscheduled
        if d > today:
            break
    return d.isoformat()


def _monthly_estimate_cents(amount_cents: Optional[int], cycle: str) -> float:
    """What this bill costs per month on average (0 for 'once'/unknown amounts)."""
    if not amount_cents:
        return 0.0
    ndays = _custom_days(cycle)
    if ndays:
        return amount_cents * (_AVG_MONTH_DAYS / ndays)
    return amount_cents * _MONTHLY_FACTOR.get(cycle, 0.0)


# ── validation helpers ────────────────────────────────────────────────────────
def _norm_date(v) -> Optional[str]:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except (ValueError, TypeError):
        raise HTTPException(400, f"bad date {v!r} — use YYYY-MM-DD")


def _norm_extra(v) -> str:
    """`extra` is a JSON object of user-defined fields; accept dict or JSON text."""
    if v in (None, ""):
        return "{}"
    if isinstance(v, str):
        try:
            v = _json.loads(v)
        except ValueError:
            raise HTTPException(400, "extra must be a JSON object")
    if not isinstance(v, dict):
        raise HTTPException(400, "extra must be a JSON object")
    return _json.dumps({str(k)[:80]: str(val)[:500] for k, val in v.items()})


def _bill_row(r) -> dict:
    d = dict(r)
    try:
        d["extra"] = _json.loads(d.get("extra") or "{}")
    except ValueError:
        d["extra"] = {}
    d["autopay"] = bool(d.get("autopay"))
    d["active"] = bool(d.get("active"))
    return d


def _get_bill(conn, bid: int):
    row = conn.execute("SELECT * FROM bills WHERE id=?", (bid,)).fetchone()
    if not row:
        raise HTTPException(404, "bill not found")
    return row


class BillIn(BaseModel):
    name: str
    category: str = ""
    portal_url: str = ""
    portal_note: str = ""
    amount_cents: Optional[int] = None      # None = variable
    cycle: str = "monthly"
    due_day: Optional[int] = None
    next_due: Optional[str] = None
    autopay: bool = False
    active: bool = True
    extra: Optional[dict] = None


def _validate_common(cycle: str, due_day, next_due):
    if not _valid_cycle(cycle):
        raise HTTPException(400, f"bad cycle {cycle!r} — monthly|weekly|yearly|quarterly|once|custom-N-days")
    if due_day is not None and not (1 <= int(due_day) <= 31):
        raise HTTPException(400, "due_day must be 1-31")
    return _norm_date(next_due)


# ── CRUD ──────────────────────────────────────────────────────────────────────
@router.get("/api/bills")
def list_bills(active: Optional[int] = None):
    """All bills, active first, soonest-due first (unscheduled last)."""
    conn = get_conn()
    try:
        where, args = "", []
        if active is not None:
            where, args = "WHERE active=?", [1 if active else 0]
        rows = conn.execute(
            f"SELECT * FROM bills {where} ORDER BY active DESC, "
            "CASE WHEN next_due IS NULL OR next_due='' THEN 1 ELSE 0 END, next_due, id",
            args).fetchall()
        return {"bills": [_bill_row(r) for r in rows],
                "counts": {"active": conn.execute("SELECT COUNT(*) FROM bills WHERE active=1").fetchone()[0],
                           "inactive": conn.execute("SELECT COUNT(*) FROM bills WHERE active=0").fetchone()[0]}}
    finally:
        conn.close()


@router.post("/api/bills")
def create_bill(b: BillIn):
    name = (b.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    next_due = _validate_common(b.cycle, b.due_day, b.next_due)
    # Default the month-anchor from the due date so "due Jan 31, monthly" keeps
    # meaning "the 31st (or month-end)" forever without the user setting due_day.
    due_day = b.due_day
    if due_day is None and next_due and b.cycle in ("monthly", "quarterly", "yearly"):
        due_day = date.fromisoformat(next_due).day
    amount = None if b.amount_cents in (None, "") else max(0, int(b.amount_cents))
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO bills (name,category,portal_url,portal_note,amount_cents,cycle,"
            "due_day,next_due,autopay,active,extra) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name, (b.category or "").strip(), (b.portal_url or "").strip(),
             (b.portal_note or "").strip(), amount, b.cycle, due_day, next_due,
             1 if b.autopay else 0, 1 if b.active else 0, _norm_extra(b.extra)))
        conn.commit()
        return _bill_row(conn.execute("SELECT * FROM bills WHERE id=?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


_PATCHABLE = {"name", "category", "portal_url", "portal_note", "amount_cents",
              "cycle", "due_day", "next_due", "autopay", "active", "extra"}


@router.patch("/api/bills/{bid}")
def update_bill(bid: int, data: dict = Body(...)):
    fields = {k: v for k, v in (data or {}).items() if k in _PATCHABLE}
    if not fields:
        raise HTTPException(400, "nothing to update")
    conn = get_conn()
    try:
        row = _get_bill(conn, bid)
        cycle = fields.get("cycle", row["cycle"])
        due_day = fields.get("due_day", row["due_day"])
        nd = _validate_common(cycle, due_day, fields.get("next_due", None))
        if "next_due" in fields:
            fields["next_due"] = nd
        if "name" in fields:
            fields["name"] = str(fields["name"]).strip()
            if not fields["name"]:
                raise HTTPException(400, "name required")
        if "extra" in fields:
            fields["extra"] = _norm_extra(fields["extra"])
        if "amount_cents" in fields:
            v = fields["amount_cents"]
            fields["amount_cents"] = None if v in (None, "") else max(0, int(v))
        for k in ("autopay", "active"):
            if k in fields:
                fields[k] = 1 if fields[k] else 0
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE bills SET {sets} WHERE id=?", (*fields.values(), bid))
        conn.commit()
        return _bill_row(conn.execute("SELECT * FROM bills WHERE id=?", (bid,)).fetchone())
    finally:
        conn.close()


@router.delete("/api/bills/{bid}")
def delete_bill(bid: int):
    """Hard delete (bill + its payment history). Prefer PATCH active=false to keep history."""
    conn = get_conn()
    try:
        _get_bill(conn, bid)
        conn.execute("DELETE FROM bill_payments WHERE bill_id=?", (bid,))
        conn.execute("DELETE FROM bills WHERE id=?", (bid,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ── payments ──────────────────────────────────────────────────────────────────
class PayIn(BaseModel):
    amount_cents: Optional[int] = None      # required when the bill is variable
    note: str = ""
    paid_at: Optional[str] = None           # YYYY-MM-DD, default today


@router.post("/api/bills/{bid}/pay")
def mark_paid(bid: int, p: PayIn = Body(default=PayIn())):
    """Log a payment and advance next_due one (or more, if long overdue) cycles."""
    conn = get_conn()
    try:
        row = _get_bill(conn, bid)
        amount = p.amount_cents if p.amount_cents is not None else row["amount_cents"]
        if amount is None:
            raise HTTPException(400, "amount_cents required — this bill's amount varies")
        amount = max(0, int(amount))
        paid_at = _norm_date(p.paid_at) or date.today().isoformat()
        cur = conn.execute(
            "INSERT INTO bill_payments (bill_id,paid_at,amount_cents,note) VALUES (?,?,?,?)",
            (bid, paid_at, amount, (p.note or "").strip()))
        nxt = advance_due(row["next_due"] or paid_at, row["cycle"], row["due_day"])
        if row["cycle"] == "once":
            conn.execute("UPDATE bills SET next_due=NULL, active=0 WHERE id=?", (bid,))
        else:
            conn.execute("UPDATE bills SET next_due=? WHERE id=?", (nxt, bid))
        conn.commit()
        return {"ok": True,
                "payment": dict(conn.execute("SELECT * FROM bill_payments WHERE id=?",
                                             (cur.lastrowid,)).fetchone()),
                "bill": _bill_row(conn.execute("SELECT * FROM bills WHERE id=?", (bid,)).fetchone())}
    finally:
        conn.close()


@router.get("/api/bills/{bid}/payments")
def list_payments(bid: int, limit: int = 100):
    conn = get_conn()
    try:
        _get_bill(conn, bid)
        rows = conn.execute("SELECT * FROM bill_payments WHERE bill_id=? "
                            "ORDER BY paid_at DESC, id DESC LIMIT ?", (bid, limit)).fetchall()
        return {"payments": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.delete("/api/bills/{bid}/payments/{pid}")
def delete_payment(bid: int, pid: int):
    """Undo a mis-click. next_due is NOT rolled back — edit the bill if needed."""
    conn = get_conn()
    try:
        n = conn.execute("DELETE FROM bill_payments WHERE id=? AND bill_id=?", (pid, bid)).rowcount
        conn.commit()
        if not n:
            raise HTTPException(404, "payment not found")
        return {"ok": True}
    finally:
        conn.close()


# ── summary / series (dashboards + graphs) ────────────────────────────────────
@router.get("/api/bills/summary")
def bills_summary():
    today = date.today()
    soon_cut = (today + timedelta(days=7)).isoformat()
    t = today.isoformat()
    month_key = t[:7]
    conn = get_conn()
    try:
        act = conn.execute("SELECT * FROM bills WHERE active=1").fetchall()
        brief = lambda r, days: {"id": r["id"], "name": r["name"], "category": r["category"],
                                 "next_due": r["next_due"], "amount_cents": r["amount_cents"],
                                 "autopay": bool(r["autopay"]), "days": days}
        overdue, due_soon = [], []
        monthly_total = 0.0
        variable_unknown = 0
        for r in act:
            amt = r["amount_cents"]
            if amt is None:
                # variable bill — estimate from the average of its last 3 payments
                avg = conn.execute("SELECT AVG(amount_cents) FROM (SELECT amount_cents FROM "
                                   "bill_payments WHERE bill_id=? ORDER BY paid_at DESC, id DESC LIMIT 3)",
                                   (r["id"],)).fetchone()[0]
                if avg is None:
                    variable_unknown += 1
                else:
                    amt = int(avg)
            monthly_total += _monthly_estimate_cents(amt, r["cycle"])
            nd = r["next_due"]
            if not nd:
                continue
            days = (date.fromisoformat(nd[:10]) - today).days
            if nd < t:
                overdue.append(brief(r, days))
            elif nd <= soon_cut:
                due_soon.append(brief(r, days))
        overdue.sort(key=lambda x: x["next_due"])
        due_soon.sort(key=lambda x: x["next_due"])
        paid = conn.execute("SELECT COALESCE(SUM(amount_cents),0), COUNT(*) FROM bill_payments "
                            "WHERE substr(paid_at,1,7)=?", (month_key,)).fetchone()
        return {"overdue": overdue, "overdue_count": len(overdue),
                "due_soon": due_soon, "due_soon_count": len(due_soon),
                "monthly_total_cents": int(round(monthly_total)),
                "variable_unknown": variable_unknown,
                "paid_this_month_cents": paid[0], "paid_this_month_count": paid[1],
                "active_count": len(act), "today": t}
    finally:
        conn.close()


@router.get("/api/bills/series")
def bills_series(months: int = 12):
    """Per-month paid totals (overall + per category) for the over-time chart."""
    months = max(1, min(60, int(months)))
    today = date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT substr(p.paid_at,1,7) AS ym, COALESCE(NULLIF(b.category,''),'uncategorized') AS cat, "
            "SUM(p.amount_cents) AS total FROM bill_payments p JOIN bills b ON b.id=p.bill_id "
            "WHERE substr(p.paid_at,1,7) >= ? GROUP BY ym, cat", (keys[0],)).fetchall()
    finally:
        conn.close()
    idx = {k: i for i, k in enumerate(keys)}
    total = [0] * len(keys)
    cats: dict = {}
    for r in rows:
        i = idx.get(r["ym"])
        if i is None:
            continue
        total[i] += r["total"] or 0
        cats.setdefault(r["cat"], [0] * len(keys))[i] += r["total"] or 0
    return {"months": keys, "total_cents": total,
            "categories": {k: v for k, v in sorted(cats.items())}}


# ── CSV export / import ───────────────────────────────────────────────────────
_CSV_COLS = ["name", "category", "amount", "cycle", "next_due", "due_day",
             "autopay", "active", "portal_url", "portal_note", "extra"]


@router.get("/api/bills/export.csv")
def export_csv():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM bills ORDER BY active DESC, next_due, id").fetchall()
    finally:
        conn.close()
    out = _io.StringIO()
    w = _csv.writer(out)
    w.writerow(_CSV_COLS)
    for r in rows:
        w.writerow([r["name"], r["category"] or "",
                    "" if r["amount_cents"] is None else f"{r['amount_cents'] / 100:.2f}",
                    r["cycle"] or "monthly", r["next_due"] or "", r["due_day"] or "",
                    1 if r["autopay"] else 0, 1 if r["active"] else 0,
                    r["portal_url"] or "", r["portal_note"] or "", r["extra"] or "{}"])
    return PlainTextResponse(out.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=bills.csv"})


@router.post("/api/bills/import")
def import_csv(data: dict = Body(...)):
    """Import bills from CSV text {csv: "..."}. Header aliases accepted:
    amount|amount_usd, next_due|due|due_date. Bad rows are skipped and reported."""
    text = (data or {}).get("csv") or ""
    if not text.strip():
        raise HTTPException(400, "csv text required")
    reader = _csv.DictReader(_io.StringIO(text))
    imported, errors = 0, []
    conn = get_conn()
    try:
        for i, row in enumerate(reader, start=2):    # start=2: header is line 1
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in (row or {}).items()}
            try:
                name = row.get("name", "")
                if not name:
                    raise ValueError("missing name")
                amount_s = row.get("amount") or row.get("amount_usd") or ""
                amount = None if amount_s == "" else max(0, int(round(float(amount_s) * 100)))
                cycle = row.get("cycle") or "monthly"
                if not _valid_cycle(cycle):
                    raise ValueError(f"bad cycle {cycle!r}")
                nd = _norm_date(row.get("next_due") or row.get("due") or row.get("due_date"))
                due_day = int(row["due_day"]) if row.get("due_day") else (
                    date.fromisoformat(nd).day if nd and cycle in ("monthly", "quarterly", "yearly") else None)
                if due_day is not None and not (1 <= due_day <= 31):
                    raise ValueError("due_day must be 1-31")
                autopay = 1 if row.get("autopay", "0").lower() in ("1", "true", "yes", "y") else 0
                active = 0 if row.get("active", "1").lower() in ("0", "false", "no", "n") else 1
                extra = _norm_extra(row.get("extra") or "{}")
                conn.execute(
                    "INSERT INTO bills (name,category,portal_url,portal_note,amount_cents,cycle,"
                    "due_day,next_due,autopay,active,extra) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (name, row.get("category", ""), row.get("portal_url", ""),
                     row.get("portal_note", ""), amount, cycle, due_day, nd, autopay, active, extra))
                imported += 1
            except (ValueError, HTTPException) as e:
                detail = getattr(e, "detail", None) or str(e)
                errors.append(f"line {i}: {detail}")
        conn.commit()
    finally:
        conn.close()
    return {"imported": imported, "errors": errors}
