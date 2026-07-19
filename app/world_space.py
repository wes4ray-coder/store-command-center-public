"""
The Company — Space Program (JASA).

A DECOUPLED, purely-additive overlay: a NASA-equivalent agency ("crypto's going
to the moon") that launches FINANCE / CRYPTO / RESEARCH agents up to the Moon to
do their work, then flies them home. It does NOT touch the core agent state
machine (world_sim) — the town still lists and animates these agents exactly as
before. This module only maintains its OWN launch schedule + traveler roster in a
single world_meta JSON blob (no migration), so it survives restarts and reconciles
stale flights purely from persisted timestamps.

Everything is derived from ``time.time()`` each tick, so an interrupted launch can
never leave an agent stuck "ascending" forever — the phase is a pure function of
elapsed seconds. Import-safe: no DB / GPU / network work at import time. Every
public entry point degrades gracefully; ``snapshot`` never raises so it can be
inlined into the /api/world/state poll (every 3s).

Toggle: ``world_space_enabled`` (default on). Cadence: ``world_space_interval_min``.
"""
import json
import logging
import random
import time

from deps import get_conn
import world_defs as wd
import world_settings as ws

log = logging.getLogger("world_space")

# ── agency identity ───────────────────────────────────────────────────────────
AGENCY_NAME = "JASA — Acme Aerospace"

# Launch pad tile in the town grid (world-map.js is TILE=20 * COLS=132 x ROWS=104,
# i.e. valid cols 0..131 / rows 0..103). Parked near the bottom-right map edge —
# clear of the city center so a rocket pad reads as its own landmark.
PAD_COL = 118
PAD_ROW = 90

META_KEY = "space_state"

# eligible departments — the "to the moon" crews
ELIGIBLE_DEPTS = ("finance", "crypto", "research")

# ── flight timing (seconds, real time) ────────────────────────────────────────
# Outbound sequence ≈ 40s to reach the Moon; contract phase enum is
# boarding|ascending|transit (out) + landing (the descent home).
OUT_PHASES = [("boarding", 8.0), ("ascending", 12.0), ("transit", 20.0)]
OUT_TOTAL = sum(d for _, d in OUT_PHASES)   # 40.0
MOON_DWELL = 150.0    # how long a crew works on the Moon before returning
BACK_DUR = 15.0       # descent-home ("landing") flight duration
# reconcile guard: a flight older than this (app was down) is resolved immediately
STALE_AFTER = max(OUT_TOTAL, BACK_DUR) + 3600.0


def _empty_payload():
    return {
        "enabled": False,
        "agency": {"name": AGENCY_NAME, "launches_total": 0, "on_moon": 0},
        "pad": {"col": PAD_COL, "row": PAD_ROW},
        "launch": None,
        "on_moon": [],
        "next_launch_eta_sec": 0,
    }


def _default_state():
    return {"launches_total": 0, "flight": None, "on_moon": [], "moon_until": 0.0,
            "last_launch": 0.0}


# ── persistence (single world_meta blob — no migration) ───────────────────────
def _load(conn=None):
    own = conn is None
    if own:
        conn = get_conn()
    try:
        raw = wd.mget(conn.cursor(), META_KEY)
    except Exception:
        raw = None
    finally:
        if own:
            conn.close()
    st = _default_state()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                st.update({k: data.get(k, st[k]) for k in st})
        except Exception:
            pass
    # normalise types / lists
    st["on_moon"] = st.get("on_moon") or []
    if not isinstance(st["on_moon"], list):
        st["on_moon"] = []
    return st


def _save(st, conn=None):
    own = conn is None
    if own:
        conn = get_conn()
    try:
        wd.mset(conn.cursor(), META_KEY, json.dumps(st))
        conn.commit()
    except Exception:
        log.exception("world_space: save failed")
    finally:
        if own:
            conn.close()


# ── config ────────────────────────────────────────────────────────────────────
def enabled(conn=None):
    return ws.b("world_space_enabled", conn)


def _interval_sec(conn=None):
    try:
        return max(30, ws.i("world_space_interval_min", conn) * 60)
    except Exception:
        return 480


# ── crew selection ────────────────────────────────────────────────────────────
def _pick_crew(conn):
    """1-3 eligible agents (finance/crypto/research) still in the game. [] if none."""
    try:
        q = ("SELECT id, name, dept FROM world_agents WHERE dept IN (%s) ORDER BY id"
             % ",".join("?" * len(ELIGIBLE_DEPTS)))
        rows = conn.execute(q, ELIGIBLE_DEPTS).fetchall()
    except Exception:
        return []
    if not rows:
        return []
    n = min(len(rows), random.randint(1, 3))
    picks = random.sample(list(rows), n)
    return [{"id": r["id"], "name": r["name"], "dept": r["dept"]} for r in picks]


def _still_present(crew, conn):
    """Drop crew members that have left the game since they launched."""
    if not crew:
        return []
    try:
        ids = {r[0] for r in conn.execute(
            "SELECT id FROM world_agents").fetchall()}
    except Exception:
        return crew   # can't verify → assume present rather than lose them
    return [m for m in crew if m.get("id") in ids]


# ── phase math (pure function of elapsed time) ────────────────────────────────
def _phase(flight, now):
    """Return (phase_label, overall_progress 0..1) for an active flight."""
    el = max(0.0, now - float(flight.get("started") or now))
    if flight.get("dir") == "back":
        return "landing", min(1.0, el / BACK_DUR)
    acc = 0.0
    for name, dur in OUT_PHASES:
        if el < acc + dur:
            return name, min(1.0, el / OUT_TOTAL)
        acc += dur
    return "transit", 1.0


# ── the tick (wired into world_ticker) ────────────────────────────────────────
def tick(conn=None):
    """Advance the space program one step. Idempotent + purely time-driven, so a
    restart mid-flight self-heals (the phase is recomputed from timestamps)."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        now = time.time()
        st = _load(conn)
        changed = False

        if not enabled(conn):
            # feature off → ground everyone cleanly (no stuck travelers)
            if st.get("flight") or st.get("on_moon"):
                st["flight"] = None
                st["on_moon"] = []
                st["moon_until"] = 0.0
                changed = True
            if changed:
                _save(st, conn)
            return

        flight = st.get("flight")
        if flight:
            el = now - float(flight.get("started") or now)
            if flight.get("dir") == "out":
                if el >= OUT_TOTAL or el >= STALE_AFTER:
                    crew = _still_present(flight.get("crew") or [], conn)
                    since = int(now)
                    st["on_moon"] = [{"id": m["id"], "name": m["name"],
                                      "dept": m["dept"], "since": since} for m in crew]
                    st["moon_until"] = now + MOON_DWELL
                    st["flight"] = None
                    changed = True
            else:   # "back" — descent home
                if el >= BACK_DUR or el >= STALE_AFTER:
                    st["flight"] = None   # crew already removed from on_moon at return start
                    changed = True
        else:
            on_moon = st.get("on_moon") or []
            if on_moon and st.get("moon_until") and now >= float(st["moon_until"]):
                # begin the return trip
                crew = _still_present(
                    [{"id": m["id"], "name": m["name"], "dept": m["dept"]} for m in on_moon], conn)
                st["on_moon"] = []
                st["moon_until"] = 0.0
                if crew:
                    st["flight"] = {"dir": "back", "crew": crew, "started": now}
                changed = True
            elif not on_moon:
                # idle → launch on cadence (only one active flight at a time)
                if now - float(st.get("last_launch") or 0) >= _interval_sec(conn):
                    crew = _pick_crew(conn)
                    if crew:
                        st["flight"] = {"dir": "out", "crew": crew, "started": now}
                        st["launches_total"] = int(st.get("launches_total") or 0) + 1
                        st["last_launch"] = now
                        changed = True
                    # no eligible crew → leave last_launch as-is; eta keeps counting
                    # and we retry next tick (cheap, no spam).

        if changed:
            _save(st, conn)
    except Exception:
        log.exception("world_space.tick failed")
    finally:
        if own:
            conn.close()


# ── force a launch now (endpoint) ─────────────────────────────────────────────
def launch_now(conn=None):
    """Force an immediate launch. Returns (ok, note). ok=False → 409-worthy."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        if not enabled(conn):
            return False, "The space program is disabled (world_space_enabled off)."
        st = _load(conn)
        if st.get("flight"):
            return False, "A launch is already in progress."
        if st.get("on_moon"):
            return False, "A crew is already on the Moon — one mission at a time."
        crew = _pick_crew(conn)
        if not crew:
            return False, "No eligible finance/crypto/research agents available to launch."
        now = time.time()
        st["flight"] = {"dir": "out", "crew": crew, "started": now}
        st["launches_total"] = int(st.get("launches_total") or 0) + 1
        st["last_launch"] = now
        _save(st, conn)
        names = ", ".join(m["name"] for m in crew)
        return True, f"🚀 Launch! {names} en route to the Moon."
    except Exception as e:
        log.exception("world_space.launch_now failed")
        return False, f"Launch failed: {e}"
    finally:
        if own:
            conn.close()


# ── read-only payload for /api/world/space + world_state injection ────────────
def snapshot(conn=None):
    """Build the ``space`` payload. NEVER raises — returns an empty payload on any
    error so it's safe to inline into the world_state poll."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        en = enabled(conn)
        st = _load(conn)
        now = time.time()

        launch_obj = None
        flight = st.get("flight")
        if flight:
            phase, prog = _phase(flight, now)
            launch_obj = {
                "phase": phase,
                "progress": round(prog, 3),
                "crew": [{"id": m["id"], "name": m["name"], "dept": m["dept"]}
                         for m in (flight.get("crew") or [])],
            }

        on_moon = [{"id": m["id"], "name": m["name"], "dept": m["dept"],
                    "since": int(m.get("since") or now)}
                   for m in (st.get("on_moon") or [])]

        # next-launch ETA: 0 while outbound; time-to-return while a crew is busy;
        # otherwise time until the cadence fires the next launch.
        if flight and flight.get("dir") == "out":
            eta = 0
        elif on_moon:
            eta = max(0, int(float(st.get("moon_until") or now) - now))
        elif flight and flight.get("dir") == "back":
            eta = max(0, int(BACK_DUR - (now - float(flight.get("started") or now))))
        else:
            eta = max(0, int(float(st.get("last_launch") or 0) + _interval_sec(conn) - now))

        return {
            "enabled": en,
            "agency": {"name": AGENCY_NAME,
                       "launches_total": int(st.get("launches_total") or 0),
                       "on_moon": len(on_moon)},
            "pad": {"col": PAD_COL, "row": PAD_ROW},
            "launch": launch_obj,
            "on_moon": on_moon,
            "next_launch_eta_sec": eta,
        }
    except Exception:
        log.exception("world_space.snapshot failed")
        return _empty_payload()
    finally:
        if own:
            conn.close()
