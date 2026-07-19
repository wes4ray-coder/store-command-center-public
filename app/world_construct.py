"""THE COMPANY — construction as a RimWorld-grade system.

The town no longer builds ONE thing at a time behind a hidden progress bar. Every
structure is a row in `world_structures` moving through a real lifecycle:

    blueprint  →  frame  →  built
    (owes mats)   (mats     (work done →
                   hauled)    quality rolled)

- BLUEPRINT: placed with a material DEBT (`material_cost`) but nothing spent yet.
  Construction workers HAUL the owed resources incrementally out of the company
  stockpile (`world_skills.spend`) into `material_have`. No stock → it waits.
- FRAME: fully-supplied. Now it's a build job: any construction worker adds
  `work_done` each tick until `work_total`, at which point it becomes...
- BUILT: permanent. Quality is rolled from the finishing agent's construction
  level (awful→legendary); a fine piece seeds an "impressive art nearby" mood
  thought for the whole town.

Several structures are in flight at once (up to CONCURRENT), so many agents build
many things in parallel — the headline change from the old single `build_project`.
The town auto-enqueues the next tier-eligible blueprint to keep itself growing;
`place_blueprint` is also the hook for future play-god placement.

State: table `world_structures` (migrated from the old built_structures/build_project
JSON blobs on first run). Decoupled; degrades gracefully.
"""
import json

from world_defs import mget, mset, log_town
import world_skills as WS
import world_tech as WT

# what the town can build, in order; `tier` = min tech tier index required.
STRUCTURES = [
    {"kind": "signpost",   "name": "Signpost",        "tier": 0, "work": 60,  "cost": {"planks": 10}},
    {"kind": "garden",     "name": "Flower Garden",   "tier": 0, "work": 90,  "cost": {"planks": 15, "crops": 20}},
    {"kind": "statue",     "name": "Stone Statue",    "tier": 1, "work": 150, "cost": {"ore": 20, "planks": 10}},
    {"kind": "fountain",   "name": "Grand Fountain",  "tier": 1, "work": 210, "cost": {"ore": 30}},
    {"kind": "watchtower", "name": "Watchtower",      "tier": 2, "work": 290, "cost": {"ore": 50, "planks": 30}},
    {"kind": "obelisk",    "name": "Iron Obelisk",    "tier": 3, "work": 400, "cost": {"ore": 80}},
    {"kind": "monument",   "name": "Steel Monument",  "tier": 4, "work": 540, "cost": {"ore": 120, "planks": 60}},
]
_CAT = {s["kind"]: s for s in STRUCTURES}

CONCURRENT = 3                 # how many structures the town builds simultaneously
HAUL_BATCH = 4                 # max material units a single work-tick moves from the stockpile

# quality tiers, low→high; the roll is centred on construction level / 4.
QUALITY = ["awful", "poor", "normal", "good", "excellent", "masterwork", "legendary"]
QUALITY_ICON = {"awful": "🥀", "poor": "▫️", "normal": "▪️", "good": "✨",
                "excellent": "🌟", "masterwork": "💎", "legendary": "👑"}


def _ensure(c):
    c.execute("""CREATE TABLE IF NOT EXISTS world_structures(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT, name TEXT, slot INTEGER,
        status TEXT DEFAULT 'blueprint',
        material_cost TEXT DEFAULT '{}',
        material_have TEXT DEFAULT '{}',
        work_done REAL DEFAULT 0, work_total REAL DEFAULT 1,
        quality TEXT, built_by TEXT)""")
    # play-god editor: an exact world-pixel override (NULL = the computed slot pos)
    for col in ("ox REAL", "oy REAL"):
        try:
            c.execute(f"ALTER TABLE world_structures ADD COLUMN {col}")
        except Exception:
            pass
    _migrate(c)


def _migrate(c):
    """One-time: fold the legacy JSON blobs into rows, then retire the blobs."""
    if mget(c, "structures_migrated", "") == "1":
        return
    try:
        legacy_built = json.loads(mget(c, "built_structures", "[]") or "[]")
    except Exception:
        legacy_built = []
    for b in legacy_built:
        spec = _CAT.get(b.get("kind"), {})
        c.execute("""INSERT INTO world_structures
            (kind,name,slot,status,material_cost,material_have,work_done,work_total,quality,built_by)
            VALUES (?,?,?,'built',?,?,?,?,?,?)""",
            (b.get("kind"), b.get("name") or spec.get("name"), b.get("slot", 0),
             json.dumps(spec.get("cost", {})), json.dumps(spec.get("cost", {})),
             spec.get("work", 1), spec.get("work", 1), b.get("quality"), b.get("built_by")))
    try:
        proj = json.loads(mget(c, "build_project", "null") or "null")
    except Exception:
        proj = None
    if proj:
        spec = _CAT.get(proj.get("kind"), {})
        c.execute("""INSERT INTO world_structures
            (kind,name,slot,status,material_cost,material_have,work_done,work_total)
            VALUES (?,?,?,'frame',?,?,?,?)""",
            (proj.get("kind"), proj.get("name"), proj.get("slot", len(legacy_built)),
             json.dumps(spec.get("cost", {})), json.dumps(spec.get("cost", {})),
             proj.get("progress", 0), proj.get("work", spec.get("work", 1))))
    mset(c, "build_project", "null")
    mset(c, "built_structures", "[]")
    mset(c, "structures_migrated", "1")


def _rows(c, status=None):
    if status:
        q = "SELECT * FROM world_structures WHERE status=? ORDER BY id"
        rows = c.execute(q, (status,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM world_structures ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _event(c, kind, text):
    try:
        c.execute("INSERT INTO world_events (agent_key, kind, text) VALUES (?,?,?)", ("", kind, text))
    except Exception:
        pass


# ── placement ──────────────────────────────────────────────────────────────
def place_blueprint(c, kind, slot=None):
    """Drop a ghost: a debt-carrying blueprint. No stockpile spend yet (RimWorld
    commits nothing until materials are actually hauled)."""
    _ensure(c)
    spec = _CAT.get(kind)
    if not spec:
        return None
    if slot is None:
        slot = c.execute("SELECT COALESCE(MAX(slot),-1)+1 FROM world_structures").fetchone()[0]
    c.execute("""INSERT INTO world_structures
        (kind,name,slot,status,material_cost,material_have,work_done,work_total)
        VALUES (?,?,?,'blueprint',?, '{}', 0, ?)""",
        (kind, spec["name"], slot, json.dumps(spec["cost"]), spec["work"]))
    _event(c, "build", f"📐 A {spec['name']} is planned — hauling materials.")
    return c.lastrowid


# ── play-god placement: drag a finished/in-flight structure to an exact spot ──
def move_structure(c, sid, x, y):
    """Persist a world-pixel override (ox/oy) for one structure so it renders at
    the dragged spot instead of its computed slot. Returns True if a row moved."""
    _ensure(c)
    if x is None or y is None:
        c.execute("UPDATE world_structures SET ox=NULL, oy=NULL WHERE id=?", (int(sid),))
    else:
        c.execute("UPDATE world_structures SET ox=?, oy=? WHERE id=?",
                  (float(x), float(y), int(sid)))
    return c.rowcount > 0


# ── production orders (RimWorld "Bills"): user says WHAT to build ──────────────
def _ensure_orders(c):
    c.execute("""CREATE TABLE IF NOT EXISTS world_build_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT, mode TEXT DEFAULT 'make',      -- 'make' N total, or 'keep' N standing
        target INTEGER DEFAULT 1, produced INTEGER DEFAULT 0,
        paused INTEGER DEFAULT 0, order_idx INTEGER DEFAULT 0)""")


def orders(c):
    _ensure_orders(c)
    return [dict(r) for r in c.execute(
        "SELECT * FROM world_build_orders ORDER BY order_idx, id").fetchall()]


def add_order(c, kind, mode="make", target=1):
    _ensure_orders(c)
    if kind not in _CAT:
        return None
    mode = "keep" if mode == "keep" else "make"
    idx = c.execute("SELECT COALESCE(MAX(order_idx),-1)+1 FROM world_build_orders").fetchone()[0]
    c.execute("INSERT INTO world_build_orders(kind,mode,target,order_idx) VALUES(?,?,?,?)",
              (kind, mode, max(1, int(target)), idx))
    return c.lastrowid


def update_order(c, oid, **fields):
    _ensure_orders(c)
    if fields.get("delete"):
        c.execute("DELETE FROM world_build_orders WHERE id=?", (oid,))
        return
    sets, vals = [], []
    for col in ("mode", "target", "paused", "order_idx"):
        if col in fields and fields[col] is not None:
            sets.append(f"{col}=?")
            vals.append(int(fields[col]) if col in ("target", "paused", "order_idx") else fields[col])
    if sets:
        vals.append(oid)
        c.execute(f"UPDATE world_build_orders SET {','.join(sets)} WHERE id=?", vals)


def _count_built(c, kind):
    return c.execute("SELECT COUNT(*) FROM world_structures WHERE kind=? AND status='built'", (kind,)).fetchone()[0]


def _count_inflight(c, kind):
    return c.execute("SELECT COUNT(*) FROM world_structures WHERE kind=? AND status IN ('blueprint','frame')", (kind,)).fetchone()[0]


def _order_want(c, o):
    """How many MORE of this kind the order still wants in flight."""
    built, inflight = _count_built(c, o["kind"]), _count_inflight(c, o["kind"])
    if o["mode"] == "keep":                          # maintain N standing (rebuilds losses)
        return o["target"] - built - inflight
    return o["target"] - (o.get("produced") or 0) - inflight   # 'make': N total ever, no auto-rebuild


def _note_completion(c, kind):
    """Credit a finished build against the first active 'make' order for its kind."""
    r = c.execute("""SELECT id, target, produced FROM world_build_orders
        WHERE kind=? AND mode='make' AND paused=0 AND produced<target ORDER BY order_idx, id LIMIT 1""",
        (kind,)).fetchone()
    if r:
        c.execute("UPDATE world_build_orders SET produced=produced+1 WHERE id=?", (r[0],))


def maybe_enqueue(c):
    """Keep up to CONCURRENT structures in flight, tier-gated. Active production
    ORDERS decide what to build; with no orders the town auto-grows up the ladder."""
    _ensure_orders(c)
    inflight = c.execute("SELECT COUNT(*) FROM world_structures WHERE status IN ('blueprint','frame')").fetchone()[0]
    if inflight >= CONCURRENT:
        return
    tier = WT.tier_index(c)
    active = [o for o in orders(c) if not o["paused"]]
    if active:                                       # user orders take over from auto-grow
        for o in active:
            spec = _CAT.get(o["kind"])
            if not spec or spec["tier"] > tier:
                continue
            want = _order_want(c, o)
            while want > 0 and inflight < CONCURRENT:
                place_blueprint(c, o["kind"])
                inflight += 1
                want -= 1
            if inflight >= CONCURRENT:
                return
        return
    have = {r["kind"] for r in _rows(c)}             # no orders → auto-grow: next new tier-eligible kind
    for s in STRUCTURES:
        if s["kind"] in have or s["tier"] > tier:
            continue
        place_blueprint(c, s["kind"])
        return                                        # one per call; next tick tops up


# ── the work firehose (called from world_sim while an agent skills 'construction') ──
def advance(c, points, agent=None):
    """One construction work-tick from `agent`: haul materials to a starved
    blueprint, or add build-work to a frame. Completing a frame rolls quality."""
    if points <= 0:
        return
    _ensure(c)
    maybe_enqueue(c)

    frame = _neediest_frame(c)
    if frame:
        _build(c, frame, points, agent)
        return
    bp = _haulable_blueprint(c)
    if bp:
        _haul(c, bp)


def _neediest_frame(c):
    """The in-progress frame with the least work done (round-robins attention)."""
    frames = _rows(c, "frame")
    if not frames:
        return None
    return min(frames, key=lambda f: (f["work_done"] / max(1.0, f["work_total"])))


def _haulable_blueprint(c):
    """A blueprint still owing a resource the stockpile can currently supply."""
    sp = WS.stockpile(c)
    for bp in _rows(c, "blueprint"):
        cost = json.loads(bp["material_cost"] or "{}")
        have = json.loads(bp["material_have"] or "{}")
        for r, need in cost.items():
            owe = int(need) - int(have.get(r, 0))
            if owe > 0 and int(sp.get(r, 0)) > 0:
                return bp
    return None


def _haul(c, bp):
    """Move up to HAUL_BATCH units of owed materials from the stockpile into this
    blueprint. When fully supplied it graduates to a frame."""
    cost = json.loads(bp["material_cost"] or "{}")
    have = json.loads(bp["material_have"] or "{}")
    sp = WS.stockpile(c)
    budget = HAUL_BATCH
    for r, need in cost.items():
        if budget <= 0:
            break
        owe = int(need) - int(have.get(r, 0))
        move = min(owe, int(sp.get(r, 0)), budget)
        if move > 0 and WS.spend(c, {r: move}):
            have[r] = int(have.get(r, 0)) + move
            budget -= move
    done = all(int(have.get(r, 0)) >= int(n) for r, n in cost.items())
    if done:
        c.execute("UPDATE world_structures SET material_have=?, status='frame' WHERE id=?",
                  (json.dumps(have), bp["id"]))
        _event(c, "build", f"🏗️ Materials delivered — framing the {bp['name']}.")
    else:
        c.execute("UPDATE world_structures SET material_have=? WHERE id=?", (json.dumps(have), bp["id"]))


def _roll_quality(level):
    """Distribution centred on construction level/4, clamped to [awful..masterwork].
    (Legendary is reserved for a future 'inspiration' event.)"""
    center = min(5.0, (level or 0) / 4.0)
    # spread: deterministic-ish blend of level with slot parity via the id caller passes none — keep simple
    idx = int(round(center))
    return QUALITY[max(0, min(5, idx))]


def _build(c, frame, points, agent):
    """Add construction work to a frame; finishing rolls quality + places it."""
    total = float(frame["work_total"] or 1)
    done = min(total, float(frame["work_done"]) + points)
    if done < total:
        c.execute("UPDATE world_structures SET work_done=? WHERE id=?", (done, frame["id"]))
        return
    lvl = 0
    if agent:
        try:
            lvl = WS.level_of(WS.get_xp(c, agent["key"], "construction"))
        except Exception:
            lvl = 0
    q = _roll_quality(lvl)
    who = (agent or {}).get("name")
    c.execute("UPDATE world_structures SET work_done=?, status='built', quality=?, built_by=? WHERE id=?",
              (total, q, who, frame["id"]))
    icon = QUALITY_ICON.get(q, "")
    _event(c, "build", f"🏛️ The {frame['name']} is complete! {icon} {q} quality"
                       + (f" (by {who})" if who else "") + ".")
    _note_completion(c, frame["kind"])
    log_town(f"CONSTRUCTION: a {q} {frame['name']} now stands at the build site.")
    # a fine piece lifts the whole town's mood (RimWorld 'impressive art nearby')
    if q in ("good", "excellent", "masterwork", "legendary"):
        try:
            import world_mood
            keys = [r[0] for r in c.execute(
                "SELECT key FROM world_agents WHERE kind IN ('worker','openclaw')").fetchall()]
            world_mood.add_thought_all(c, keys, f"{icon} a {q} {frame['name']} nearby", 5, hours=10)
        except Exception:
            pass
    maybe_enqueue(c)


def has_work(c):
    """True if there's any haulable/buildable construction right now (for the WorkGiver)."""
    _ensure(c)
    maybe_enqueue(c)
    if _rows(c, "frame"):
        return True
    return _haulable_blueprint(c) is not None or bool(_rows(c, "blueprint"))


# ── read model ───────────────────────────────────────────────────────────────
def snapshot(c):
    """Back-compat shape for the renderer/HUD, plus the full concurrent project list.

    - built:    finished structures (kind/name/slot/quality)         [unchanged]
    - current:  most-progressed in-flight project (legacy single)    [unchanged]
    - projects: EVERY in-flight structure with material + work bars   [new]
    """
    _ensure(c)
    built, projects = [], []
    for r in _rows(c):
        cost = json.loads(r["material_cost"] or "{}")
        have = json.loads(r["material_have"] or "{}")
        need_total = sum(cost.values()) or 1
        have_total = sum(min(int(have.get(k, 0)), int(v)) for k, v in cost.items())
        wp = int(r["work_done"] / max(1.0, r["work_total"]) * 100)
        if r["status"] == "built":
            built.append({"id": r["id"], "kind": r["kind"], "name": r["name"], "slot": r["slot"],
                          "quality": r["quality"], "ox": r.get("ox"), "oy": r.get("oy")})
        else:
            projects.append({
                "id": r["id"], "kind": r["kind"], "name": r["name"], "slot": r["slot"],
                "status": r["status"], "pct": wp,
                "mat_pct": int(have_total / need_total * 100),
                "cost": cost, "have": have, "ox": r.get("ox"), "oy": r.get("oy")})
    # legacy 'current' = the in-flight project furthest along (frames first)
    cur = None
    if projects:
        top = max(projects, key=lambda p: (p["status"] == "frame", p["pct"], p["mat_pct"]))
        cur = {"kind": top["kind"], "name": top["name"], "slot": top["slot"], "pct": top["pct"]}
    # production orders + their live status, and the catalog for the "add order" picker
    tier = WT.tier_index(c)
    ords = []
    for o in orders(c):
        spec = _CAT.get(o["kind"], {})
        built_n, inflight_n = _count_built(c, o["kind"]), _count_inflight(c, o["kind"])
        locked = spec.get("tier", 0) > tier
        want = _order_want(c, o)
        if o["paused"]:
            status = "paused"
        elif locked:
            status = "locked"
        elif want <= 0:
            status = "met"
        else:
            status = "building"
        ords.append({**o, "name": spec.get("name", o["kind"]), "built": built_n,
                     "inflight": inflight_n, "status": status, "locked": locked})
    catalog = [{"kind": s["kind"], "name": s["name"], "tier": s["tier"],
                "available": s["tier"] <= tier} for s in STRUCTURES]
    return {"current": cur, "built": built, "projects": projects,
            "concurrent": CONCURRENT, "in_flight": len(projects),
            "orders": ords, "catalog": catalog, "tier": tier}
