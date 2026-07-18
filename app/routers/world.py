"""
The Company — HTTP surface (thin).

Endpoints only. All behaviour lives in the world modules:
  world_defs   → constants, roster, seeding, live activity, the LLM-queue gateway
  world_sim    → simulation tick (needs, economy, bills, behaviour, mood)
  world_gov    → thoughts, opinions, town meetings & voting (LLM via the queue)
  world_build  → pixel-art asset generation + autobuild (image gen via the queue)
"""
import time, json, logging
from fastapi import APIRouter, HTTPException, Body, BackgroundTasks

from deps import get_conn
import world_defs as wd
import world_gov, world_build, world_systems, world_settings as ws
import world_skills, world_orchestra, world_raid, world_learn, world_security, world_tech, world_construct, world_work, world_mood, world_research, world_schedule, world_items
import world_balance as wb

router = APIRouter()
logger = logging.getLogger("store")


@router.get("/api/world/settings")
def get_world_settings():
    """The Company settings: LLM schedule + real-world guardrails."""
    return {"settings": ws.get_all(), "defaults": ws.DEFAULTS}


@router.post("/api/world/settings")
def save_world_settings(body: dict = Body(...)):
    ws.save(body.get("settings") or body)
    return {"ok": True, "settings": ws.get_all()}


@router.post("/api/world/cognition")
def run_cognition_now():
    """Manually trigger a cognition batch (respects the enabled/guardrail flags)."""
    if not ws.b("world_llm_enabled"):
        raise HTTPException(400, "Cognition is disabled in Company settings.")
    conn = get_conn()
    try:
        n = world_gov.run_cognition(conn)
    finally:
        conn.close()
    return {"ok": True, "queued": n}


@router.get("/api/world/state")
def world_state():
    """Read-only snapshot. The background ticker (world_ticker) owns advancement;
    this endpoint never mutates the sim, so any number of viewers is cheap."""
    conn = get_conn()
    wd.seed(conn)              # idempotent safety (first boot before the ticker runs)
    c = conn.cursor()
    agents = [dict(r) for r in c.execute("SELECT * FROM world_agents ORDER BY id").fetchall()]
    for a in agents:                                   # RuneScape-style skills (system A)
        a["skills"] = world_skills.skills_for(c, a["key"])
        a["primary_skill"] = world_skills.primary_skill(a)
        a["competence"] = round(world_learn.competence(c, a), 2)   # merit weight (system E)
        _pol = world_learn.policy_for(c, a["key"])                  # what the bandit has learned it likes
        a["prefers"] = max(_pol, key=lambda k: _pol[k]["value"]) if _pol else None
        a["beat"] = world_security.agent_tasks(c, a["key"])         # their security beat + open debug tasks
        a["work_priority"] = world_work.get_priorities(c, a)        # Work-Priority row (work_type → 0-4)
        a["mood_value"] = round(world_mood.mood_of(c, a))          # thought-ledger mood 0-100 (chunk 4)
        a["thoughts"] = world_mood.thoughts_for(c, a["key"])       # active mood modifiers
        a["broken"] = world_mood.is_broken(a)
        a["inventory"] = world_items.inventory_for(c, a["key"])   # what they carry (item economy)
        a["thriving"] = all((a.get(n) or 0) >= 68 for n in wd.NEEDS)   # all-green = max-reward state
        a["blessed"] = (a.get("blessed_until") or 0) > time.time()     # god's temp buff active
        try:
            import world_genome
            _g = world_genome.genome(a)
            a["style"] = {"label": world_genome.STYLE(_g), "epsilon": round(_g["epsilon"], 2),
                          "focus": round(_g["focus"], 2), "spend": round(_g["spend"], 2)}
        except Exception:
            a["style"] = None
        _streak = time.time() - (a.get("streak_since") or time.time())  # monotony readout
        a["streak_min"] = int(_streak / 60)
        a["output_pct"] = int(max(wb.MONOTONY_FLOOR,
                                  1 - max(0.0, _streak - wb.MONOTONY_GRACE_SEC) * wb.MONOTONY_SLOPE) * 100)
    props  = [dict(r) for r in c.execute("SELECT * FROM world_props ORDER BY id").fetchall()]
    events = [dict(r) for r in c.execute("SELECT * FROM world_events ORDER BY id DESC LIMIT 24").fetchall()]
    suggestions = [dict(r) for r in c.execute(
        "SELECT * FROM world_suggestions WHERE status='open' ORDER BY id DESC LIMIT 8").fetchall()]
    meeting = c.execute("SELECT * FROM world_meetings ORDER BY id DESC LIMIT 1").fetchone()
    directive = c.execute("SELECT * FROM world_directives WHERE status='active' "
                          "ORDER BY id DESC LIMIT 1").fetchone()
    achievements = [dict(r) for r in c.execute(
        "SELECT * FROM world_achievements ORDER BY earned_at DESC").fetchall()]
    company = world_systems.company_summary(c)
    company["stockpile"] = world_skills.stockpile(c)   # company-wide gathered resources
    company["stock_targets"] = world_skills.stock_targets(c)   # keep floor..ceil per resource (chunk 3)
    company["intelligence"] = world_learn.intelligence(c)   # collective learning score (system E)
    company["specialists"] = world_learn.leaderboard(c)     # top agent per skill
    company["tech"] = world_tech.snapshot(c)                # material/research tier (chunk 4)
    company["research"] = world_research.snapshot(c)        # research TREE with prerequisites (#7)
    try:
        import world_rank
        company["rankings"] = world_rank.standings(c)       # the leaderboard — they compete to top it
    except Exception:
        company["rankings"] = []
    company["schedule"] = world_schedule.snapshot(c, __import__("time").strftime("%H"))  # town timetable (#6)
    company["construction"] = world_construct.snapshot(c)   # ghost-build projects + finished structures
    orchestra = world_orchestra.snapshot(c)            # season + town phase (system C)
    raid = world_raid.snapshot(c)                      # active threats / combat (system D)
    security = {"systems": world_security.scan_systems(c),   # whole-store log health (chunk 2)
                "posture": world_security.real_posture(c)}   # the REAL Command Center (grade/shield/attackers)
    placements_out = world_items.placements(c)          # furniture/yard pieces agents bought (item economy)
    art = []                                            # real generated images → wall art in houses (chunk 5)
    try:
        for r in c.execute("SELECT image_path FROM generations WHERE status='done' AND image_path IS NOT NULL "
                           "ORDER BY id DESC LIMIT 12").fetchall():
            p = r[0] or ""
            if "/designs/" in p:
                art.append("/store/designs/" + p.split("/designs/", 1)[1])
    except Exception:
        pass
    conn.close()
    activity, _ = wd.live_activity()
    return {
        "now": time.strftime("%Y-%m-%d %H:%M:%S"),
        "clock_hour": int(time.strftime("%H")),
        "departments": [{"key": k, "label": v[0], "color": v[1]} for k, v in wd.DEPARTMENTS.items()],
        "work_types": [{"key": wt, **world_work.WT_META[wt]} for wt in world_work.WORK_TYPES],
        "agents": agents, "props": props, "activity": activity, "events": events,
        "economy": {"item_cost": wd.ITEM_COST, "upgrades": wd.UPGRADES,
                    "treasury": company["treasury"], "debt": company["total_debt"],
                    "company_fund": company["company_fund"]},
        "company": company,
        "orchestra": orchestra,
        "raid": raid,
        "security": security,
        "art": art,
        "placements": placements_out,
        "achievements": achievements,
        "governance": {"priority": directive["text"] if directive else None,
                       "directive": dict(directive) if directive else None,
                       "suggestions": suggestions,
                       "last_meeting": dict(meeting) if meeting else None},
    }


@router.post("/api/world/agent/{agent_id}/makeover")
def agent_makeover_ep(agent_id: int):
    """Commission a custom generated sprite for this agent (paid from their coins;
    all GPU guards inside world_build.agent_makeover)."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM world_agents WHERE id=?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no such agent")
        res = world_build.agent_makeover(conn.cursor(), dict(row))
        conn.commit()
        return res
    finally:
        conn.close()


@router.post("/api/world/agent/{agent_id}/rename")
def rename_agent(agent_id: int, body: dict = Body(...)):
    name = (body.get("name") or "").strip()[:32]
    if not name:
        raise HTTPException(400, "name required")
    conn = get_conn()
    conn.execute("UPDATE world_agents SET name=?, updated_at=datetime('now') WHERE id=?", (name, agent_id))
    conn.commit(); conn.close()
    return {"ok": True, "name": name}


@router.post("/api/world/agent/{agent_id}/assign")
def world_assign_agent(agent_id: int, body: dict = Body(...)):
    """RCT-style pick-up/drop: POST an agent to a spot or a work task.
    {location, kind:'skill'|'spot', col, row, minutes} — kind 'skill' sends them to
    work a resource node (location = node kind, e.g. 'mine'/'build'); 'spot' parks
    them on a free tile (col,row). {location:null} releases them back to autonomy."""
    conn = get_conn()
    try:
        c = conn.cursor()
        r = c.execute("SELECT key, name FROM world_agents WHERE id=?", (agent_id,)).fetchone()
        if not r:
            raise HTTPException(404, "no such agent")
        loc = body.get("location")
        if not loc:                                            # release
            c.execute("UPDATE world_agents SET posted_to=NULL, posted_kind=NULL, posted_until=0 WHERE id=?", (agent_id,))
            conn.commit()
            return {"ok": True, "released": True, "name": r["name"]}
        kind = "skill" if body.get("kind") == "skill" else "spot"
        minutes = max(1, min(180, int(body.get("minutes") or 20)))
        until = time.time() + minutes * 60
        col, row = int(body.get("col") or 0), int(body.get("row") or 0)
        c.execute("""UPDATE world_agents SET posted_to=?, posted_kind=?, posted_until=?,
                     posted_col=?, posted_row=? WHERE id=?""",
                  (loc, kind, until, col, row, agent_id))
        where = (f"the {loc}" if kind == "skill" else "the spot you chose")
        verb = "gets to work at" if kind == "skill" else "heads to"
        try:
            c.execute("INSERT INTO world_events (agent_key, kind, text) VALUES (?,?,?)",
                      (r["key"], "system", f"✋ {r['name']} {verb} {where} (you posted them there)."))
        except Exception:
            pass
        conn.commit()
        return {"ok": True, "name": r["name"], "posted_to": loc, "kind": kind, "minutes": minutes}
    finally:
        conn.close()


@router.post("/api/world/placement/move")
def world_move_placement(body: dict = Body(...)):
    """Play-god editor: drag a bought furniture/yard piece to an exact spot.
    {agent_key, spot, slot, ox, oy} — ox/oy null resets to the default slot."""
    key, spot = body.get("agent_key"), body.get("spot")
    if not key or spot not in ("house", "yard") or body.get("slot") is None:
        raise HTTPException(400, "agent_key, spot and slot required")
    ox, oy = body.get("ox"), body.get("oy")
    if (ox is None) != (oy is None):
        raise HTTPException(400, "ox and oy go together")
    conn = get_conn()
    try:
        c = conn.cursor()
        moved = world_items.move_placement(c, key, spot, int(body["slot"]),
                                           None if ox is None else float(ox),
                                           None if oy is None else float(oy))
        if not moved:
            raise HTTPException(404, "no such placement")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.post("/api/world/stock/target")
def world_set_stock_target(body: dict = Body(...)):
    """Set keep floor..ceil for a resource. Agents auto-gather it when below floor, stop at ceil."""
    conn = get_conn()
    try:
        world_skills.set_stock_target(conn.cursor(), body.get("resource"), body.get("floor", 0), body.get("ceil", 200))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/world/schedule")
def world_set_schedule(body: dict = Body(...)):
    """Set the town timetable (#6). {hour, band} sets one hour; {schedule:[...24]} sets all.
    band ∈ sleep|work|rec|any."""
    conn = get_conn()
    try:
        c = conn.cursor()
        if isinstance(body.get("schedule"), list):
            world_schedule.set_all(c, body["schedule"])
        elif body.get("hour") is not None:
            world_schedule.set_hour(c, body["hour"], body.get("band"))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/world/research")
def world_set_research(body: dict = Body(...)):
    """Pick the active research project (#7). {key: <project>}. Must have its prereqs done."""
    conn = get_conn()
    try:
        ok = world_research.set_active(conn.cursor(), body.get("key"))
        conn.commit()
    finally:
        conn.close()
    return {"ok": ok}


@router.post("/api/world/build/order")
def world_build_order(body: dict = Body(...)):
    """Production orders (RimWorld bills) for the construction queue.
    action=add {kind, mode:'make'|'keep', target}; action=update {id, paused|target|mode|order_idx};
    action=remove {id}. Active orders decide WHAT the town builds (else it auto-grows)."""
    action = body.get("action", "add")
    conn = get_conn()
    try:
        c = conn.cursor()
        if action == "add":
            world_construct.add_order(c, body.get("kind"), body.get("mode", "make"), body.get("target", 1))
        elif action == "remove":
            world_construct.update_order(c, int(body["id"]), delete=True)
        elif action == "update":
            world_construct.update_order(c, int(body["id"]),
                mode=body.get("mode"), target=body.get("target"),
                paused=body.get("paused"), order_idx=body.get("order_idx"))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/world/work/priority")
def world_set_work_priority(body: dict = Body(...)):
    """Set an agent's priority for a work type (0=off, 1-4). {agent_key|agent_id, work_type, priority}.
    Pass work_type + priority with no agent to set the WHOLE COLUMN for every worker/openclaw agent."""
    wt, prio = body.get("work_type"), body.get("priority")
    conn = get_conn()
    try:
        c = conn.cursor()
        if body.get("agent_key") or body.get("agent_id"):
            key = body.get("agent_key")
            if not key:
                r = c.execute("SELECT key FROM world_agents WHERE id=?", (body["agent_id"],)).fetchone()
                key = r["key"] if r else None
            if key:
                world_work.set_priority(c, key, wt, prio)
        else:                                              # whole column
            for r in c.execute("SELECT key FROM world_agents WHERE kind IN ('worker','openclaw')").fetchall():
                world_work.set_priority(c, r["key"], wt, prio)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.get("/api/world/bills")
def world_bills_list():
    """All production bills + live stock counts and active/paused state."""
    import world_bills
    conn = get_conn()
    try:
        c = conn.cursor()
        snap = world_bills.snapshot(c)
        conn.commit()                       # refresh() may advance hysteresis state
        return {"bills": snap, "kinds": [{"key": k, **{f: v[f] for f in ("label", "icon", "dept")}}
                                         for k, v in world_bills.KINDS.items()]}
    finally:
        conn.close()


@router.post("/api/world/bills")
def world_bills_create(body: dict = Body(...)):
    """Create a bill: {kind, target, unpause_at?, label?, min_level?}."""
    import world_bills
    if body.get("kind") not in world_bills.KINDS:
        raise HTTPException(400, f"kind must be one of {list(world_bills.KINDS)}")
    if not body.get("target"):
        raise HTTPException(400, "target (how many to keep ready) is required")
    conn = get_conn()
    try:
        c = conn.cursor()
        bid = world_bills.create(c, body["kind"], body["target"], body.get("unpause_at"),
                                 body.get("label") or "", body.get("min_level") or 1)
        conn.commit()
        return {"ok": True, "id": bid}
    finally:
        conn.close()


@router.post("/api/world/bills/{bid}")
def world_bills_update(bid: int, body: dict = Body(...)):
    """Update a bill: any of {target, unpause_at, suspended, min_level, order_idx, label}."""
    import world_bills
    conn = get_conn()
    try:
        c = conn.cursor()
        ok = world_bills.update(c, bid, **{k: body.get(k) for k in
                                           ("target", "unpause_at", "suspended",
                                            "min_level", "order_idx", "label")})
        if not ok:
            raise HTTPException(404, "no such bill (or nothing to change)")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.delete("/api/world/bills/{bid}")
def world_bills_delete(bid: int):
    import world_bills
    conn = get_conn()
    try:
        c = conn.cursor()
        if not world_bills.delete(c, bid):
            raise HTTPException(404, "no such bill")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.get("/api/world/tileset")
def world_tileset_status():
    """Generated-terrain-tileset status (state/progress + whether one is installed)."""
    import world_tileset
    return world_tileset.status()


@router.post("/api/world/tileset")
def world_tileset_generate(body: dict = Body(default={})):
    """Generate a terrain tileset from the world theme (or a custom one) with the
    pixel-art pipeline. Runs in the background; poll GET for progress."""
    import world_tileset
    if not world_tileset.start_generate(body.get("theme")):
        raise HTTPException(409, "A tileset generation is already running.")
    return {"ok": True, "note": "Generating 6 terrain tiles — watch the status."}


@router.delete("/api/world/tileset")
def world_tileset_remove():
    """Back to procedural terrain (removes the generated atlas + tile mappings)."""
    import world_tileset
    world_tileset.remove()
    return {"ok": True}


@router.post("/api/world/raid")
def world_raid_trigger(body: dict = Body(default={})):
    """Manually raise a raid. {'drill': true} spawns practice dummies when there are
    no real threats — so you can always see the defense in action."""
    conn = get_conn()
    try:
        res = world_raid.trigger_raid(conn.cursor(), reason=body.get("reason") or "manual alert",
                                      drill=bool(body.get("drill")))
        conn.commit()
    finally:
        conn.close()
    return res


@router.post("/api/world/raid/standdown")
def world_raid_standdown():
    conn = get_conn()
    try:
        world_orchestra.set_phase(conn.cursor(), "recovery", "manual stand-down")
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/world/think")
def world_think(body: dict = Body(default={})):
    res = world_gov.agent_think(body.get("agent_id"))
    if not res:
        raise HTTPException(404, "no agents")
    return res


@router.post("/api/world/opinion")
def world_opinion(body: dict = Body(default={})):
    res = world_gov.generate_opinion(body.get("agent_id"), wait=60)
    if not res:
        raise HTTPException(404, "no agents")
    return res


@router.post("/api/world/meeting")
def world_meeting():
    conn = get_conn()
    try:
        res = world_gov.hold_meeting(conn)
        wd.mset(conn.cursor(), "last_meeting_ts", time.time()); conn.commit()
    finally:
        conn.close()
    if not res:
        raise HTTPException(400, "No suggestions to vote on yet — let the crew think first.")
    return res


@router.post("/api/world/directive/{directive_id}/resolve")
def resolve_directive(directive_id: int, body: dict = Body(default={})):
    """Mark the town's current mandate done (or dropped)."""
    status = "dropped" if (body.get("status") == "dropped") else "done"
    conn = get_conn()
    conn.execute("UPDATE world_directives SET status=?, resolved_at=datetime('now') WHERE id=?",
                 (status, directive_id))
    conn.commit(); conn.close()
    return {"ok": True, "status": status}


@router.post("/api/world/agent/{agent_id}/want")
def agent_want(agent_id: int, background: BackgroundTasks, body: dict = Body(default={})):
    """Buy & conjure a new prop (costs coins). {"generate": false} reserves a placeholder."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM world_agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "agent not found")
    r = dict(row)
    # Real-world rule: items are never free and never below the configured floor.
    cost = max(1 if not ws.b("world_allow_free") else 0, ws.i("world_min_item_cost"))
    if (r["coins"] or 0) < cost:
        conn.close()
        raise HTTPException(400, f"{r['name']} needs {cost} 🪙 for that "
                                 f"(has {r['coins'] or 0}). Put them to work first!")
    label = (body.get("label") or "chair").strip()[:40]
    prompt = body.get("prompt") or wd.pixel_prompt(label)
    do_gen = body.get("generate", True)
    prop_id = conn.execute(
        "INSERT INTO world_props (kind,label,location,prompt,status,owner_key) VALUES ('furniture',?,?,?,?,?)",
        (label, f"desk:{r['dept']}", prompt, "queued" if do_gen else "placeholder", r["key"])).lastrowid
    conn.execute("UPDATE world_agents SET coins=coins-? WHERE id=?", (cost, agent_id))
    conn.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
                 (r["key"], "want", f"{r['name']} spent {cost} 🪙 on a {label}."))
    conn.commit(); conn.close()
    if do_gen:
        background.add_task(world_build.generate_world_prop, prop_id)
    return {"ok": True, "prop_id": prop_id, "label": label, "generating": bool(do_gen), "spent": cost}


@router.post("/api/world/prop/{prop_id}/generate")
def prop_generate(prop_id: int, background: BackgroundTasks):
    conn = get_conn()
    if not conn.execute("SELECT id FROM world_props WHERE id=?", (prop_id,)).fetchone():
        conn.close(); raise HTTPException(404, "prop not found")
    conn.execute("UPDATE world_props SET status='queued' WHERE id=?", (prop_id,))
    conn.commit(); conn.close()
    background.add_task(world_build.generate_world_prop, prop_id)
    return {"ok": True, "prop_id": prop_id}


@router.get("/api/world/props/recent")
def props_recent(limit: int = 12):
    """Recent world creations (the agents' pixel props/decor) to 👍/👎 — teaches the
    town's taste, separate from store-bound creations. Newest finished props first."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id,label,kind,image_path,score,verdict,user_verdict "
            "FROM world_props WHERE status='done' AND image_path IS NOT NULL AND image_path!='' "
            "ORDER BY id DESC LIMIT ?", (max(1, min(48, limit)),)).fetchall()
        return {"props": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/api/world/prop/{prop_id}/verdict")
def prop_verdict(prop_id: int, background: BackgroundTasks, body: dict = Body(default={})):
    """Like or reject a world creation → feeds the taste model (+1/-1). A reject also has
    the maker REWORK it with your note (the world-creation reject → tweak loop)."""
    like = bool(body.get("like"))
    reason = (body.get("reason") or "").strip()
    conn = get_conn()
    try:
        row = conn.execute("SELECT label, prompt FROM world_props WHERE id=?", (prop_id,)).fetchone()
        if not row:
            raise HTTPException(404, "prop not found")
        conn.execute("UPDATE world_props SET user_verdict=? WHERE id=?", (1 if like else -1, prop_id))
        conn.commit()
        try:
            import world_taste
            text = row["prompt"] or row["label"] or f"prop {prop_id}"
            world_taste.add_example(conn, f"prop:{prop_id}", "prop", text, 1.0 if like else -1.0, "god_verdict")
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()
    if not like:
        background.add_task(world_build.rework_prop, prop_id, reason)
    return {"ok": True, "prop_id": prop_id, "like": like}


@router.post("/api/world/agent/{agent_id}/buy")
def buy_upgrade(agent_id: int, body: dict = Body(...)):
    up = wd.UPGRADES_BY_ID.get((body.get("upgrade_id") or "").strip())
    if not up:
        raise HTTPException(400, "unknown upgrade")
    conn = get_conn()
    row = conn.execute("SELECT * FROM world_agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "agent not found")
    r = dict(row)
    owned = json.loads(r["upgrades"] or "[]")
    if up["id"] in owned:
        conn.close(); raise HTTPException(400, f"{r['name']} already owns the {up['label']}.")
    if (r["coins"] or 0) < up["cost"]:
        conn.close(); raise HTTPException(400, f"{r['name']} needs {up['cost']} 🪙 (has {r['coins'] or 0}).")
    owned.append(up["id"])
    new_mult = round((r["earn_mult"] or 1.0) + up["mult"], 3)
    conn.execute("UPDATE world_agents SET coins=coins-?, earn_mult=?, upgrades=?, updated_at=datetime('now') WHERE id=?",
                 (up["cost"], new_mult, json.dumps(owned), agent_id))
    conn.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
                 (r["key"], "upgrade", f"🛠️ {r['name']} bought a {up['label']} ({up['desc']})."))
    conn.commit(); conn.close()
    return {"ok": True, "earn_mult": new_mult, "coins_spent": up["cost"]}


@router.get("/api/world/layout")
def get_layout():
    """The user's hand-edited map layout (play-god mode), or null for procedural."""
    conn = get_conn()
    try:
        raw = wd.mget(conn.cursor(), "layout")
    finally:
        conn.close()
    conn = get_conn()
    try:
        wraw = wd.mget(conn.cursor(), "tile_wear")
    finally:
        conn.close()
    try:
        wear = json.loads(wraw) if wraw else {}
    except Exception:
        wear = {}
    if not raw:
        return {"layout": None, "wear": wear}
    try:
        return {"layout": json.loads(raw), "wear": wear}
    except Exception:
        return {"layout": None, "wear": wear}


@router.post("/api/world/wear")
def push_wear(body: dict = Body(...)):
    """Merge foot-traffic increments into the persistent desire-line map.
    {updates: {"c,r": steps, ...}} — counts accumulate server-side, capped."""
    updates = body.get("updates") or {}
    if not isinstance(updates, dict) or not updates:
        return {"ok": True, "tiles": 0}
    conn = get_conn()
    try:
        c = conn.cursor()
        try:
            wear = json.loads(wd.mget(c, "tile_wear") or "{}")
        except Exception:
            wear = {}
        n = 0
        for k, v in list(updates.items())[:4000]:
            try:
                wear[k] = min(600, int(wear.get(k, 0)) + max(0, int(v)))
                n += 1
            except Exception:
                continue
        wd.mset(c, "tile_wear", json.dumps(wear))
        conn.commit()
        return {"ok": True, "tiles": n}
    finally:
        conn.close()


@router.post("/api/world/layout")
def save_layout(body: dict = Body(...)):
    """Persist an edited map layout (buildings, decor, work nodes, landmarks — stored
    as an opaque blob). Send {"layout": null} to reset to the procedural map."""
    layout = body.get("layout")
    conn = get_conn()
    try:
        c = conn.cursor()
        if layout is None:
            c.execute("DELETE FROM world_meta WHERE key='layout'")
        else:
            wd.mset(c, "layout", json.dumps(layout))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "reset": layout is None}


@router.get("/api/world/agent/{agent_id}/log")
def agent_log(agent_id: int):
    conn = get_conn()
    row = conn.execute("SELECT key,name FROM world_agents WHERE id=?", (agent_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "agent not found")
    p = wd.AGENT_LOG_DIR / f"{row['key']}.md"
    txt = p.read_text() if p.exists() else f"# {row['name']} — journal\n\n(No entries yet.)"
    return {"name": row["name"], "markdown": txt[-6000:]}


@router.get("/api/world/snapshot")
def world_snapshot():
    """Compact JSON the LLM world-builder can reason over."""
    conn = get_conn()
    wd.seed(conn)
    c = conn.cursor()
    agents = [{"name": r["name"], "job": r["dept"], "state": r["state"], "mood": r["mood_label"],
               "coins": r["coins"], "level": r["level"]}
              for r in c.execute("SELECT * FROM world_agents ORDER BY id").fetchall()]
    props = [{"label": r["label"], "at": r["location"], "status": r["status"]}
             for r in c.execute("SELECT * FROM world_props ORDER BY id").fetchall()]
    conn.close()
    activity, _ = wd.live_activity()
    return {"agents": agents, "props": props, "activity": activity}
