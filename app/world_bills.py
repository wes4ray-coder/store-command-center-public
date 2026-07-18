"""THE COMPANY — production BILLS (RimWorld-style "do until you have X").

A bill is a standing production target on a REAL store pipeline: "keep 12
finished images ready", "keep 3 music clips queued for the store". While a
pipeline's finished-output count is below its bill's target, the bill is
ACTIVE — the Work-Priority scheduler's 🏭 Produce column offers agents a job
filling it (world_work._wg_produce). Hysteresis mirrors RimWorld's
pause/unpause band: once the target is reached the bill pauses and stays
paused until stock falls to `unpause_at`, so the town doesn't flap between
"one more!" and "done" on every consumed unit.

Bills can also DRIVE real production (not just animate agents): when the
`world_bills_drive` toggle is on, an active bill periodically kicks
world_auto.run_cycle(kind) — the same gated autopilot the Company already
uses (budget caps, review queue, taste, endorsements all still apply). The
toggle defaults OFF and the kick is throttled, so enabling a bill can never
stampede the GPU.
"""
import threading
import time

from world_defs import mget, mset

# bill kind → how to count FINISHED, ready stock (never in-flight rows), plus
# which department fills it and which world_auto kind produces more of it.
KINDS = {
    "image": {"label": "Images ready",   "icon": "🎨", "dept": "image",
              "sql": "SELECT COUNT(*) FROM generations WHERE status='done'"},
    "music": {"label": "Music clips",    "icon": "🎵", "dept": "audio",
              "sql": "SELECT COUNT(*) FROM audio_clips WHERE status='done'"},
    "video": {"label": "Videos ready",   "icon": "🎬", "dept": "video",
              "sql": "SELECT COUNT(*) FROM videos WHERE status='done'"},
    "3d":    {"label": "3D models",      "icon": "🧊", "dept": "models3d",
              "sql": "SELECT COUNT(*) FROM models3d WHERE status='done'"},
}

DRIVE_MIN_INTERVAL_SEC = 20 * 60      # floor between real production kicks


def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS world_bills(
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT,
        label      TEXT DEFAULT '',
        target     INTEGER,
        unpause_at INTEGER,
        suspended  INTEGER DEFAULT 0,
        min_level  INTEGER DEFAULT 1,
        order_idx  INTEGER DEFAULT 0,
        filling    INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')))""")


def count(c, kind):
    meta = KINDS.get(kind)
    if not meta:
        return 0
    try:
        return int(c.execute(meta["sql"]).fetchone()[0])
    except Exception:
        return 0


def create(c, kind, target, unpause_at=None, label="", min_level=1):
    if kind not in KINDS:
        raise ValueError(f"unknown bill kind '{kind}'")
    target = max(1, int(target))
    # default band: restart filling once stock drops ~25% below target
    unpause = min(target - 1, int(unpause_at) if unpause_at is not None
                  else max(0, int(target * 0.75)))
    _ensure(c)
    nxt = c.execute("SELECT COALESCE(MAX(order_idx),-1)+1 FROM world_bills").fetchone()[0]
    return c.execute(
        "INSERT INTO world_bills (kind,label,target,unpause_at,min_level,order_idx) "
        "VALUES (?,?,?,?,?,?)",
        (kind, label or KINDS[kind]["label"], target, unpause,
         max(1, int(min_level)), nxt)).lastrowid


def update(c, bid, **fields):
    _ensure(c)
    allowed = {"target", "unpause_at", "suspended", "min_level", "order_idx", "label"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        sets.append(f"{k}=?")
        vals.append(int(v) if k != "label" else str(v))
    if not sets:
        return False
    vals.append(int(bid))
    c.execute(f"UPDATE world_bills SET {', '.join(sets)} WHERE id=?", vals)
    return c.rowcount > 0


def delete(c, bid):
    _ensure(c)
    c.execute("DELETE FROM world_bills WHERE id=?", (int(bid),))
    return c.rowcount > 0


def refresh(c):
    """Advance every bill's hysteresis state from live stock counts. Cheap
    (one COUNT per distinct kind) — safe to call per scheduler scan."""
    _ensure(c)
    rows = c.execute("SELECT id, kind, target, unpause_at, filling FROM world_bills").fetchall()
    counts = {}
    for r in rows:
        k = r["kind"]
        if k not in counts:
            counts[k] = count(c, k)
        n = counts[k]
        if r["filling"] and n >= r["target"]:
            c.execute("UPDATE world_bills SET filling=0 WHERE id=?", (r["id"],))
        elif not r["filling"] and n <= r["unpause_at"]:
            c.execute("UPDATE world_bills SET filling=1 WHERE id=?", (r["id"],))
    return counts


def active_bills(c):
    """Bills currently demanding work, in user order. Refreshes hysteresis first."""
    counts = refresh(c)
    out = []
    for r in c.execute("SELECT * FROM world_bills WHERE suspended=0 AND filling=1 "
                       "ORDER BY order_idx, id").fetchall():
        b = dict(r)
        b["count"] = counts.get(b["kind"], 0)
        out.append(b)
    return out


def job_for(c, agent):
    """The first active bill this agent qualifies for (RimWorld min-skill
    routing via agent level; own-department bills first)."""
    lvl = int(agent.get("level") or 1)
    bills = [b for b in active_bills(c) if lvl >= b["min_level"]]
    if not bills:
        return None
    dept = agent.get("dept") or ""
    mine = [b for b in bills if KINDS[b["kind"]]["dept"] == dept]
    return (mine or bills)[0]


def snapshot(c):
    """Every bill + live count/active state, for the API/UI."""
    _ensure(c)
    counts = refresh(c)
    out = []
    for r in c.execute("SELECT * FROM world_bills ORDER BY order_idx, id").fetchall():
        b = dict(r)
        b["count"] = counts.get(b["kind"], 0)
        b["active"] = bool(not b["suspended"] and b["filling"])
        b.update({k: KINDS[b["kind"]][k] for k in ("icon", "dept")})
        out.append(b)
    return out


# ── driving REAL production (optional, toggled, throttled) ────────────────────
def maybe_drive(c, now=None):
    """If enabled (Company setting `world_bills_drive`, default OFF), kick ONE
    real world_auto creation for the most urgent active bill — at most once per
    interval, and never while a cycle is running. All of world_auto's own gates
    (budget, review, taste, endorsements) still apply."""
    import world_settings as WSET
    if not WSET.b("world_bills_drive", c):
        return False
    now = now or time.time()
    interval = max(DRIVE_MIN_INTERVAL_SEC, WSET.i("world_bills_drive_interval_min", c) * 60)
    if now - float(mget(c, "bills_drive_t", 0) or 0) < interval:
        return False
    bills = active_bills(c)
    if not bills:
        return False
    import world_auto
    if not world_auto.enabled() or world_auto._state.get("running"):
        return False
    kind = bills[0]["kind"]
    mset(c, "bills_drive_t", now)
    threading.Thread(target=world_auto.run_cycle, args=(kind,), daemon=True).start()
    return True
