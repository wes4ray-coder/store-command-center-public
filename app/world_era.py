"""
The Company — per-building CIVILIZATION ERA overlay.

A DECOUPLED, purely-cosmetic overlay (modelled on ``world_space.py``): every
DEPARTMENT building visibly climbs a 7-rung ladder of ages when its system is
actually USED, and rots back down when neglected. Non-department buildings
(houses / shops / civic) follow the TOWN AVERAGE era.

  wood → brick → metal → western → modern → futuristic → moon   (level 0..6)

This is NOT the gather-bonus tier (that's ``world_tech``, deliberately untouched).
It keeps its OWN state in a single ``world_meta`` JSON blob (no migration) and is
driven by REAL activity: each tick reads whether a department did recent work
(``world_defs.live_activity()`` — the same backend signal world_sim pays for).
Active accrues ``progress``; idle DECAYS it, scaled by real elapsed ×
``world_run.speed()`` so fast/test mode makes the climb watchable.

Import-safe: no DB / GPU / network work at import time. Every public entry point
degrades gracefully — ``tick`` never raises (a missing signal is just "idle"),
``snapshot`` never raises so it can be inlined into the /api/world/state poll.

Toggle: ``world_era_enabled`` (default on). Tuning: ``world_era_advance_min``
(minutes of activity to climb a rung, default 20) and ``world_era_decay_min``
(minutes of neglect to slip a rung, default 60 — decay is forgiving/slower).
"""
import json
import logging
import time

from deps import get_conn
import world_defs as wd
import world_settings as ws

log = logging.getLogger("world_era")

# ── the ladder ────────────────────────────────────────────────────────────────
ERAS = ["wood", "brick", "metal", "western", "modern", "futuristic", "moon"]
EMOJI = {
    "wood":       "🪵",
    "brick":      "🧱",
    "metal":      "⚙️",
    "western":    "🤠",
    "modern":     "🏙️",
    "futuristic": "🛸",
    "moon":       "🌙",
}
MAX_LEVEL = len(ERAS) - 1            # 6 (moon)

META_KEY = "building_eras"

# On decay, a level drop lands you near the TOP of the lower rung (hysteresis, so
# it doesn't ping-pong across the boundary): you must decay this much more to slip
# again. Advance always resets to the bottom of the new rung.
DECAY_LANDING = 0.75

# Guard against downtime: cap the REAL elapsed folded into one tick (before the
# speed multiplier) so a week offline can't instantly max/nuke every building.
REAL_STEP_CAP = 3600.0              # 1h of real time, max, per tick


# ── persistence (single world_meta blob — no migration) ───────────────────────
def _default_state():
    return {"eras": {}, "last_tick": 0.0}


def _load(c):
    try:
        raw = wd.mget(c, META_KEY)
    except Exception:
        raw = None
    st = _default_state()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                st["eras"] = data.get("eras") if isinstance(data.get("eras"), dict) else {}
                st["last_tick"] = float(data.get("last_tick") or 0.0)
        except Exception:
            pass
    return st


def _save(c, st):
    try:
        wd.mset(c, META_KEY, json.dumps(st))
    except Exception:
        log.exception("world_era: save failed")


# ── event feed ────────────────────────────────────────────────────────────────
def _emit(c, loc, level, up):
    """Announce a rung change to the town event feed. Best-effort; never raises."""
    try:
        label = wd.DEPARTMENTS.get(loc, (loc,))[0]
        era = ERAS[max(0, min(MAX_LEVEL, level))]
        em = EMOJI.get(era, "")
        if up:
            text = f"{em} {label} upgraded to {era.capitalize()}!"
        else:
            text = f"{em} {label} decayed toward {era.capitalize()}…"
        c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (NULL,'era',?)",
                  (text,))
    except Exception:
        pass


# ── the tick (wired into world_ticker) ────────────────────────────────────────
def tick(conn=None):
    """Advance every department building one step. Active this cycle → accrue
    progress toward the next era; idle → decay it (slower). Hysteresis: progress
    crossing 1 promotes a rung; sustained idle dropping it below 0 demotes one.
    Purely time-driven and defended — never raises."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        if not ws.b("world_era_enabled", conn):
            return
        c = conn.cursor()
        now = time.time()
        st = _load(c)
        last = float(st.get("last_tick") or 0.0)
        st["last_tick"] = now

        # first observation → establish the clock, no phantom elapsed
        if not last:
            _save(c, st)
            conn.commit()
            return

        real = now - last
        if real <= 0:
            _save(c, st)
            conn.commit()
            return
        real = min(real, REAL_STEP_CAP)          # downtime protection

        # fast/test run modes accelerate the CHEAP sim — scale so the climb is watchable
        try:
            import world_run
            elapsed = real * max(1, world_run.speed())
        except Exception:
            elapsed = real

        adv_sec = max(60.0, ws.i("world_era_advance_min", conn) * 60.0)
        dec_sec = max(60.0, ws.i("world_era_decay_min", conn) * 60.0)

        # which departments did REAL work recently (missing signal → treated as idle)
        try:
            activity, _ = wd.live_activity()
        except Exception:
            activity = {}
        if not isinstance(activity, dict):
            activity = {}

        eras = st.get("eras")
        if not isinstance(eras, dict):
            eras = {}
        for loc in wd.DEPARTMENTS:
            cell = eras.get(loc) or {}
            level = int(cell.get("level") or 0)
            prog = float(cell.get("progress") or 0.0)
            level = max(0, min(MAX_LEVEL, level))
            active = (activity.get(loc) or 0) > 0

            if active:
                prog += elapsed / adv_sec
                if prog >= 1.0:
                    if level < MAX_LEVEL:
                        level += 1
                        prog = 0.0
                        _emit(c, loc, level, up=True)
                    else:
                        prog = 1.0                # capped at moon
            else:
                prog -= elapsed / dec_sec
                if prog < 0.0:
                    if level > 0:
                        level -= 1
                        prog = DECAY_LANDING       # land near the top of the lower rung
                        _emit(c, loc, level, up=False)
                    else:
                        prog = 0.0                 # floor: wood can rot no further

            eras[loc] = {"level": level, "progress": round(prog, 4)}

        st["eras"] = eras
        _save(c, st)
        conn.commit()
    except Exception:
        log.exception("world_era.tick failed")
    finally:
        if own:
            conn.close()


# ── read-only snapshot (injected into /api/world/state under "eras") ──────────
def snapshot(conn=None):
    """Return the EXACT contract the frontend depends on::

        { ladder: ERAS, emoji: {...}, byLoc: { <loc>: <level 0..6> }, town: <avg> }

    ``byLoc`` carries every department building's current level; ``town`` is the
    rounded average of those levels (houses / shops / civic follow it). NEVER
    raises — returns a safe empty-ish shape on any error."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        c = conn.cursor()
        st = _load(c)
        eras = st.get("eras") if isinstance(st.get("eras"), dict) else {}
        by_loc = {}
        for loc in wd.DEPARTMENTS:
            lvl = int((eras.get(loc) or {}).get("level") or 0)
            by_loc[loc] = max(0, min(MAX_LEVEL, lvl))
        levels = list(by_loc.values())
        town = int(round(sum(levels) / len(levels))) if levels else 0
        town = max(0, min(MAX_LEVEL, town))
        return {"ladder": list(ERAS), "emoji": dict(EMOJI), "byLoc": by_loc, "town": town}
    except Exception:
        log.exception("world_era.snapshot failed")
        return {"ladder": list(ERAS), "emoji": dict(EMOJI), "byLoc": {}, "town": 0}
    finally:
        if own:
            conn.close()
