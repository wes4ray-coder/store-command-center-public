"""Company-world moonlighting hook for NSFW ("Private Studio") mode.

Extracted verbatim from nsfw.py to keep that module under the size budget.
Called from world_auto's loop (inside its master-enabled/active-hours block).
When world_active(): occasionally one agent "slips off to the private studio" —
a category job (avoid-list aware) attributed to that agent. The town feed only
ever gets the generic lines; prompt text never reaches it.

The core NSFW helpers (world_active/_setting/ensure/list_categories/
submit_category_job/safety_check) live in nsfw.py; this module lazy-imports it
inside functions so there is no import cycle (nsfw.py re-exports these names).
"""
import logging
import random
import threading
import time

from db import get_conn

logger = logging.getLogger("store")

_FALLBACK_IDEAS = [
    "tasteful artistic nude figure study, classical oil painting style, soft window light",
    "elegant boudoir portrait, vintage film photography, warm shadows, implied nude",
    "sensual pin-up illustration, retro 1950s poster art style, confident pose",
    "romantic intimate couple silhouette, adults, chiaroscuro lighting, fine art",
    "artistic nude sculpture study, marble statue aesthetic, dramatic museum lighting",
]
_WORLD_LINES_START = [
    "🚪 {name} slipped away for some studio time on a private commission.",
    "🎨 {name} is putting in quiet hours on a personal art project.",
    "🔒 {name} booked the back room of the studio for private client work.",
]
_WORLD_LINES_DONE = [
    "🖼️ {name} wrapped up a private studio commission. The client seemed pleased.",
    "✅ {name} finished some after-hours personal art. It goes straight to the private archive.",
]

_world_lock = threading.Lock()
_world_running = False


def _world_interval_sec() -> int:
    import nsfw
    try:
        return max(30, int(nsfw._setting("nsfw_world_interval_min", "360") or 360)) * 60
    except Exception:
        return 360 * 60


def maybe_world_cycle():
    """Tick from world_auto's loop: run one world nsfw creation when due. No-op
    unless master+world toggles are on. Serialized; timer persisted in settings."""
    import nsfw
    global _world_running
    if not nsfw.world_active() or _world_running:
        return
    try:
        last = float(nsfw._setting("nsfw_world_last_ts", "0") or 0)
    except Exception:
        last = 0.0
    if time.time() - last < _world_interval_sec():
        return
    with _world_lock:
        if _world_running:
            return
        _world_running = True
    conn = get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('nsfw_world_last_ts',?)",
                     (str(time.time()),))
        conn.commit()
    finally:
        conn.close()
    threading.Thread(target=_world_cycle_thread, daemon=True, name="nsfw-world").start()


def _world_cycle_thread():
    global _world_running
    try:
        world_cycle()
    except Exception:
        logger.exception("nsfw world cycle failed")
    finally:
        _world_running = False


def _log_world_event(agent_key, text):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
                     (agent_key, "thought", text))
        conn.commit()
    finally:
        conn.close()


def world_cycle() -> dict:
    """One agent creation in the private studio. Prefers a category job (the nsfw
    model authors the prompt, steering AWAY from recently-rejected approaches);
    falls back to the built-in tasteful idea list when no categories have prompts
    yet. Only generic PG-13 lines ever reach the town feed."""
    import nsfw
    if not nsfw.world_active():
        return {"ok": False, "skipped": "nsfw world mode off"}
    conn = get_conn()
    try:
        nsfw.ensure(conn)
        agent = conn.execute(
            "SELECT key, name FROM world_agents ORDER BY RANDOM() LIMIT 1").fetchone()
        akey, aname = (agent["key"], agent["name"]) if agent else (None, "Someone")
        cats = [c for c in nsfw.list_categories(conn) if (c.get("gen_prompt") or "").strip()]
    finally:
        conn.close()

    _log_world_event(akey, random.choice(_WORLD_LINES_START).format(name=aname))

    if cats:
        # category job: LLM-authored prompt with the avoid-list baked in; the
        # generation itself runs async through the normal pipeline.
        tid = nsfw.submit_category_job(random.choice(cats), agent_key=akey)
        from orchestrator import orch
        deadline = time.time() + 1800
        gid = None
        while time.time() < deadline:
            t = orch.poll(tid)
            if t["status"] == "done":
                gid = (t.get("result") or {}).get("generation_id")
                break
            if t["status"] in ("error", "cancelled", "not_found"):
                return {"ok": False, "task": tid, "error": t.get("error")}
            time.sleep(5)
        # wait for the image itself so the "done" line is honest
        ok = _wait_generation(gid, timeout=1800) if gid else False
    else:
        prompt = random.choice(_FALLBACK_IDEAS)
        if nsfw.safety_check(prompt):
            return {"ok": False, "skipped": "idea tripped the safety floor"}
        conn = get_conn()
        try:
            from llm_client import _resolve_model
            model = _resolve_model(conn, None)
            cur = conn.execute(
                "INSERT INTO generations (prompt,product_type,width,height,steps,model,"
                "source,nsfw,nsfw_agent) VALUES (?,?,?,?,?,?, 'nsfw',1,?)",
                (prompt, "Art", 1024, 1024, 20, model, akey))
            gid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        import services
        services.run_generation(gid)   # blocks; orchestrator serializes the GPU
        ok = _wait_generation(gid, timeout=60)

    if ok:
        _log_world_event(akey, random.choice(_WORLD_LINES_DONE).format(name=aname))
    return {"ok": ok, "gen_id": gid, "agent": aname}


def _wait_generation(gid, timeout=1800) -> bool:
    if not gid:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        conn = get_conn()
        try:
            row = conn.execute("SELECT status FROM generations WHERE id=?", (gid,)).fetchone()
        finally:
            conn.close()
        st = row["status"] if row else None
        if st == "done":
            return True
        if st in ("failed", "rejected", None):
            return False
        time.sleep(5)
    return False
