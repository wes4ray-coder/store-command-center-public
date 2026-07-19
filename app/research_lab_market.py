"""Research Lab — the market layer: materials → Money tab + price watch.

When a report finishes (first run or a deeper pass), the Genius who wrote it:
  1. snapshots the report's "Materials, parts & tools" costs into
     research_price_history (kind='report') — the baseline for the price graphs
  2. files each material into the Money tab as a shop-search demand signal
     (money_signals, source='research') so the company's money review can turn
     them into missions — toggle research_shop_push (on), deduped per project

Recurring research: projects can be given a recheck cadence (recur_days on
research_projects). The scheduler calls recur_tick(); due projects get a
price-check pass — the Genius re-searches every material's current price and
snapshots it (kind='check'). The runs accumulate into the 📈 price-watch graph
(carry-forward totals, per-item sparklines) in the Research tab.

Master toggle research_recur_enabled (on); every LLM call rides the
orchestrator queue at priority=2 via research_lab._llm. research_lab is
imported lazily inside functions (research_lab_media pattern) — no cycle.
"""
import json as _json
import re
import threading
from datetime import datetime

from db import get_conn


# ── prompt (registered in app/prompts.py via ref=("research_lab_market", ...)) ─
PRICE_SYS = (
    "You are a price-checking research assistant. You get a list of material/tool items "
    "for a project, each followed by fresh web search result snippets. For each item, "
    "estimate ONE current typical price in USD from its snippets — a unit price for the "
    "cheapest sensible mainstream option, not a bulk lot. Reply with STRICT JSON and "
    "nothing else:\n"
    '{"prices":[{"item":"the item name exactly as given",'
    '"price":12.34 or null if the snippets show no usable price}]}'
)


# ── materials table parsing ───────────────────────────────────────────────────
_MAT_HDR = re.compile(r"^##+\s*Materials", re.I | re.M)


def _parse_money(s: str):
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", s or "")
    if not m:
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*(?:usd|dollars)", (s or "").lower())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


def parse_materials(md: str) -> list:
    """The report's Materials section table → [{item, qty, cost}] (cost may be None).
    Header, separator and total rows are skipped."""
    m = _MAT_HDR.search(md or "")
    if not m:
        return []
    section = md[m.end():]
    nxt = re.search(r"^##+\s", section, re.M)
    if nxt:
        section = section[:nxt.start()]
    out = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        item = (cells[0] if cells else "").strip("* ")
        if not item or set(item) <= set("-: ") or item.lower() in ("item", "items") \
                or item.lower().startswith("total"):
            continue
        out.append({"item": item[:120],
                    "qty": (cells[1] if len(cells) > 1 else "")[:40],
                    "cost": _parse_money(cells[2] if len(cells) > 2 else "")})
    return out[:20]


# ── price history ─────────────────────────────────────────────────────────────
def _insert_snapshot(pid: int, rows: list, kind: str) -> int:
    """rows = [(item, price)] — one run, one shared timestamp."""
    if not rows:
        return 0
    conn = get_conn()
    # milliseconds: a report snapshot and a recheck landing in the same second
    # must stay two distinct runs in the graph
    ts = datetime.now().isoformat(sep=" ", timespec="milliseconds")
    for item, price in rows:
        conn.execute(
            "INSERT INTO research_price_history (project_id,item,price,kind,captured_at) "
            "VALUES (?,?,?,?,?)", (pid, item, float(price), kind, ts))
    conn.commit()
    conn.close()
    return len(rows)


def snapshot_report_prices(pid: int) -> int:
    """Baseline snapshot from the report's own cost column (no LLM, no web)."""
    import research_lab as rl
    p = rl._get(pid)
    mats = parse_materials((p or {}).get("report_md") or "")
    return _insert_snapshot(pid, [(m["item"], m["cost"]) for m in mats
                                  if m["cost"] is not None], "report")


# ── materials → Money tab (demand signals) ────────────────────────────────────
def _meta_tag(pid: int) -> str:
    # matches the json.dumps rendering below; the trailing comma keeps
    # project 1 from matching project 12
    return f'"project_id": {pid},'


def file_to_money(pid: int) -> int:
    """The Genius files the report's materials as Money-tab shop searches
    (money_signals, source='research'), skipping items already filed. Advisory
    only — the normal searches→review→missions→approval flow stays in charge."""
    import research_lab as rl
    p = rl._get(pid)
    if not p or not (p.get("report_md") or "").strip():
        return 0
    mats = parse_materials(p["report_md"])
    if not mats:
        return 0
    conn = get_conn()
    try:
        conn.execute("SELECT 1 FROM money_signals LIMIT 1")
    except Exception:
        conn.close()
        return 0
    existing = {(r["query"] or "").strip().lower() for r in conn.execute(
        "SELECT query FROM money_signals WHERE source='research' AND meta LIKE ?",
        (f"%{_meta_tag(pid)}%",)).fetchall()}
    n = 0
    for m in mats:
        if m["item"].strip().lower() in existing:
            continue
        meta = _json.dumps({"project_id": pid, "project": p["title"][:80],
                            "qty": m["qty"], "est_cost": m["cost"]})
        conn.execute("INSERT INTO money_signals (source,query,results_count,meta) "
                     "VALUES (?,?,?,?)", ("research", m["item"], 0, meta))
        n += 1
    conn.commit()
    conn.close()
    if n:
        rl._ev(pid, "market",
               f"{p['genius_name']} filed {n} materials into the Money tab as shop searches")
        rl._world_note(p["genius_key"], p["genius_name"],
                       f"Sent {n} materials from “{p['title']}” to the Money desk "
                       f"as shop searches.",
                       thought="sent the shopping list to the money desk", mood=3)
    return n


def after_report(pid: int):
    """Pipeline hook — runs whenever a report (or deeper pass) completes."""
    import research_lab as rl
    snapshot_report_prices(pid)
    if rl._toggle("research_shop_push", "on"):
        file_to_money(pid)


# ── the price-check pass (manual + recurring) ─────────────────────────────────
def start_price_check(pid: int) -> bool:
    """Kick a price recheck (daemon thread). False if the project is busy."""
    import research_lab as rl
    with rl._lock:
        if pid in rl._running:
            return False
        rl._running.add(pid)
    threading.Thread(target=_run_price_check, args=(pid,), daemon=True,
                     name=f"research-price-{pid}").start()
    return True


def _run_price_check(pid: int):
    import research_lab as rl
    try:
        p = rl._get(pid)
        if not p or not (p.get("report_md") or "").strip():
            return
        mats = parse_materials(p["report_md"])[:10]
        if not mats:
            rl._ev(pid, "market", "price recheck skipped — no materials table in the report")
            return
        rl._ev(pid, "market",
               f"{p['genius_name']} is re-checking prices on {len(mats)} materials…")
        blocks = []
        for m in mats:
            if rl._cancelled(pid):
                return
            snips = rl._searx(f"{m['item']} price buy", 4)
            lines = "\n".join(f"  - {h['title']}: {h['snippet']}"
                              for h in snips if h.get("snippet")) or "  (no results)"
            blocks.append(f"ITEM: {m['item']}\n{lines}")
        raw = rl._llm("research_price", f"PROJECT: {p['title']}\n\n" + "\n\n".join(blocks),
                      max_tokens=800, desc=f"research prices · {p['title'][:36]}")
        d = rl._parse_json(raw or "") or {}
        got = {str(x.get("item", "")).strip().lower(): x.get("price")
               for x in (d.get("prices") or []) if isinstance(x, dict)}
        rows = []
        for m in mats:
            v = got.get(m["item"].strip().lower())
            if isinstance(v, (int, float)) and v > 0:
                rows.append((m["item"], float(v)))
        n = _insert_snapshot(pid, rows, "check")
        rl._ev(pid, "market", f"price recheck done — fresh prices for {n}/{len(mats)} items")
        if rl._toggle("research_price_alerts", "on"):
            try:
                _check_alerts(pid, p, rows)
            except Exception as e:
                rl._ev(pid, "market", f"price-alert check skipped: {str(e)[:120]}")
        if n:
            rl._world_note(p["genius_key"], p["genius_name"],
                           f"Re-checked market prices on {n} materials for “{p['title']}”.",
                           thought="kept the shopping-list prices fresh", mood=3)
    except Exception as e:
        rl.logger.warning("research price check #%d failed: %s", pid, e)
        try:
            rl._ev(pid, "market", f"price recheck failed: {str(e)[:150]}")
        except Exception:
            pass
    finally:
        with rl._lock:
            rl._running.discard(pid)


# ── 💸 price-drop alerts (buy windows) ────────────────────────────────────────
def _check_alerts(pid: int, p: dict, fresh_rows: list) -> int:
    """After a recheck: any item at least research_price_alert_pct % below its
    report baseline becomes a buy-window alert — a God-Console community-board
    post + a money_signals row (source='research-alert') for the money review.
    Re-alerts only when the price falls a further ~5% below the last alert."""
    import research_lab as rl
    if not fresh_rows:
        return 0
    try:
        pct_min = float(rl.get_setting("research_price_alert_pct", "10") or 10)
    except Exception:
        pct_min = 10.0
    conn = get_conn()
    n = 0
    for item, price in fresh_rows:
        base = conn.execute(
            "SELECT price FROM research_price_history WHERE project_id=? AND item=? "
            "AND kind='report' ORDER BY id LIMIT 1", (pid, item)).fetchone()
        if not base or not base["price"] or base["price"] <= 0:
            continue
        drop = (base["price"] - price) / base["price"] * 100
        if drop < pct_min:
            continue
        last = conn.execute(
            "SELECT price FROM research_price_alerts WHERE project_id=? AND item=? "
            "ORDER BY id DESC LIMIT 1", (pid, item)).fetchone()
        if last and price >= (last["price"] or 0) * 0.95:
            continue
        conn.execute(
            "INSERT INTO research_price_alerts (project_id,item,baseline,price,pct) "
            "VALUES (?,?,?,?,?)", (pid, item, base["price"], price, round(drop, 1)))
        conn.commit()
        n += 1
        msg = (f"💸 Buy window: “{item}” for “{p['title']}” is ${price:.2f} — "
               f"{drop:.0f}% below the report's ${base['price']:.2f}")
        rl._ev(pid, "market", msg)
        try:                                   # God Console community board
            import world_ops as wo
            wo.note(msg, kind="research", from_agent=p["genius_name"])
        except Exception:
            pass
        try:                                   # demand signal for the money review
            conn.execute(
                "INSERT INTO money_signals (source,query,results_count,meta) VALUES (?,?,?,?)",
                ("research-alert", f"{item} (price drop)", 0,
                 _json.dumps({"project_id": pid, "project": p["title"][:80],
                              "alert": "price_drop", "baseline": base["price"],
                              "price": price, "pct": round(drop, 1)})))
            conn.commit()
        except Exception:
            pass
    conn.close()
    if n:
        rl._world_note(p["genius_key"], p["genius_name"],
                       f"Spotted {n} price-drop buy window(s) for “{p['title']}”.",
                       thought="found a bargain for the project", mood=5)
    return n


# ── recurring research (scheduler hook) ───────────────────────────────────────
def set_recurrence(pid: int, days: int):
    conn = get_conn()
    if days > 0:
        conn.execute("UPDATE research_projects SET recur_days=?, "
                     "next_run_at=datetime('now', ?) WHERE id=?",
                     (days, f"+{int(days)} days", pid))
    else:
        conn.execute("UPDATE research_projects SET recur_days=0, next_run_at=NULL "
                     "WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def recur_tick(max_start: int = 2) -> dict:
    """Called by the scheduler: start price checks on due recurring projects.
    next_run_at is bumped BEFORE starting so a failing project can't hot-loop."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, recur_days FROM research_projects WHERE recur_days > 0 "
        "AND status='done' AND (next_run_at IS NULL OR next_run_at <= datetime('now')) "
        "ORDER BY id LIMIT 10").fetchall()
    conn.close()
    started = []
    for r in rows:
        if len(started) >= max_start:
            break
        conn = get_conn()
        conn.execute("UPDATE research_projects SET next_run_at=datetime('now', ?) "
                     "WHERE id=?", (f"+{int(r['recur_days'])} days", r["id"]))
        conn.commit()
        conn.close()
        if start_price_check(r["id"]):
            started.append(r["id"])
    return {"due": len(rows), "started": started}


# ── data for the 📈 price-watch UI ────────────────────────────────────────────
def market_info(pid: int) -> dict:
    """Everything the Materials & price-watch section renders in one call.
    Run totals use carry-forward (a check run re-prices a subset; missing items
    keep their last known price) so the total line is apples-to-apples."""
    import research_lab as rl
    p = rl._get(pid) or {}
    mats = parse_materials(p.get("report_md") or "")
    conn = get_conn()
    hist = [dict(r) for r in conn.execute(
        "SELECT item, price, kind, captured_at FROM research_price_history "
        "WHERE project_id=? ORDER BY captured_at, id", (pid,)).fetchall()]
    alerts = [dict(r) for r in conn.execute(
        "SELECT item, baseline, price, pct, created_at FROM research_price_alerts "
        "WHERE project_id=? ORDER BY id DESC LIMIT 12", (pid,)).fetchall()]
    filed = 0
    try:
        filed = conn.execute(
            "SELECT COUNT(*) FROM money_signals WHERE source='research' AND meta LIKE ?",
            (f"%{_meta_tag(pid)}%",)).fetchone()[0]
    except Exception:
        pass
    conn.close()

    by_ts, series = {}, {}
    for h in hist:
        run = by_ts.setdefault(h["captured_at"], {"kind": h["kind"], "items": {}})
        run["items"][h["item"]] = h["price"]
        series.setdefault(h["item"], []).append({"ts": h["captured_at"], "price": h["price"]})
    runs, last_price = [], {}
    for ts in sorted(by_ts):
        run = by_ts[ts]
        last_price.update(run["items"])
        runs.append({"ts": ts, "kind": run["kind"], "n": len(run["items"]),
                     "total": round(sum(v for v in last_price.values() if v is not None), 2)})
    return {"materials": mats, "filed": filed, "alerts": alerts,
            "recur_days": p.get("recur_days") or 0,
            "next_run_at": p.get("next_run_at") or "",
            "runs": runs, "series": series, "checking": rl.is_running(pid)}
