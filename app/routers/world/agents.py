"""The Company — agent actions (makeover/rename/assign/want/buy/log), props
(generate/recent/verdict), and governance (think/opinion/meeting/directive)."""
import time, json, logging
from fastapi import HTTPException, Body, BackgroundTasks

from deps import get_conn
import world_defs as wd
import world_gov, world_build, world_systems, world_settings as ws
import world_skills, world_orchestra, world_raid, world_learn, world_security, world_tech, world_construct, world_work, world_mood, world_research, world_schedule, world_items
import world_balance as wb
from ._base import router


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
