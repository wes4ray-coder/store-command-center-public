"""THE COMPANY — the orchestrator (system C).

The single conductor above the per-agent sim, ticked by world_ticker. Owns the
world's macro-clock that everything else reads:

- SEASONS: spring→summer→autumn→winter, cycling on a tunable real-time period.
  Each season biases which gathering skills are productive (a yield multiplier
  world_skills reads from meta) and tints the world.
- TOWN PHASE: peace → watch → raid → recovery — the baton the raid (system D)
  drives from real security/bug signals. Here we own the state + auto-timeouts so
  a triggered raid always resolves back to peace.

Decoupled by design: writes compact state to world_meta (season / season_bonus /
town_phase) so world_skills & the sim never import this module.
"""
import json
import time

from world_defs import mget, mset

SEASONS = ["spring", "summer", "autumn", "winter"]
SEASON_META = {
    "spring": {"emoji": "🌸", "tint": [90, 165, 105], "festival": "planting season — crops thrive",
               "bonus": {"farming": 1.5, "woodcutting": 1.1}},
    "summer": {"emoji": "☀️", "tint": [235, 195, 95],  "festival": "long warm days — the fish are biting",
               "bonus": {"farming": 1.3, "fishing": 1.4}},
    "autumn": {"emoji": "🍂", "tint": [205, 130, 60],  "festival": "harvest & the great timber cut",
               "bonus": {"woodcutting": 1.5, "farming": 0.9}},
    "winter": {"emoji": "❄️", "tint": [130, 170, 225], "festival": "the mines run hot while fields sleep",
               "bonus": {"mining": 1.4, "farming": 0.5, "fishing": 0.8}},
}

SEASON_LEN_SEC = 3600          # each season = 1h real → a full year in 4h (override via meta 'season_len_sec')
PHASES = ["peace", "watch", "raid", "recovery"]
RAID_LEN_SEC = 300             # a raid runs ~5 min then falls back to recovery (D may end it sooner)
RECOVERY_LEN_SEC = 180         # recovery cooldown before peace returns
WATCH_LEN_SEC = 900            # a watch that never escalates stands down (was a dead-end phase)


# ── seasons ──
def _epoch(c):
    e = mget(c, "world_epoch", None)
    if e is None:
        e = time.time()
        mset(c, "world_epoch", e)
    return float(e)


def _season_len(c):
    try:
        return max(60.0, float(mget(c, "season_len_sec", SEASON_LEN_SEC) or SEASON_LEN_SEC))
    except Exception:
        return float(SEASON_LEN_SEC)


def current_season(c):
    elapsed = time.time() - _epoch(c)
    return SEASONS[int(elapsed / _season_len(c)) % 4]


def year_day(c):
    """A flavour 'day of the year' 1..(4*len) for display."""
    elapsed = time.time() - _epoch(c)
    per_day = _season_len(c) / 30.0            # 30 days per season
    return int(elapsed / per_day) + 1


# ── town phase ──
def phase(c):
    return mget(c, "town_phase", "peace") or "peace"


def set_phase(c, ph, reason=""):
    if ph not in PHASES:
        return phase(c)
    if phase(c) != ph:
        mset(c, "town_phase", ph)
        mset(c, "phase_since", time.time())
        _event(c, "phase", f"⚙️ Town phase → {ph}{(' — ' + reason) if reason else ''}.")
    return ph


def _advance_phase(c):
    """Auto-timeouts so a raid always resolves: raid→recovery→peace."""
    ph = phase(c)
    since = float(mget(c, "phase_since", 0) or 0)
    age = time.time() - since
    if ph == "raid" and age >= RAID_LEN_SEC:
        # don't cut a battle short while the field is contested — world_raid ends
        # it properly (victory → grade → recovery). The timeout is a 15-min
        # backstop against a stuck fight, not the normal ending.
        contested = False
        try:
            contested = bool(c.execute(
                "SELECT 1 FROM world_threats WHERE status='active' LIMIT 1").fetchone())
        except Exception:
            pass
        if not contested or age >= RAID_LEN_SEC * 3:
            set_phase(c, "recovery", "threats handled — standing down")
    elif ph == "recovery" and age >= RECOVERY_LEN_SEC:
        set_phase(c, "peace", "all clear")
    elif ph == "watch" and age >= WATCH_LEN_SEC:
        # watch was a dead-end: maybe_trigger only scanned during peace, so a town
        # that entered watch stayed there forever and security stopped working.
        set_phase(c, "peace", "watch stood down — no escalation")


def _event(c, kind, text):
    try:
        c.execute("INSERT INTO world_events (agent_key, kind, text) VALUES (?,?,?)", ("", kind, text))
    except Exception:
        pass


# ── the tick (called by world_ticker every cadence) ──
def tick(c):
    season = current_season(c)
    meta = SEASON_META[season]
    prev = mget(c, "season", None)
    mset(c, "season", season)
    mset(c, "season_bonus", json.dumps(meta["bonus"]))   # world_skills.gather reads this
    if prev and prev != season:
        _event(c, "season", f"{meta['emoji']} {season.capitalize()} has arrived — {meta['festival']}.")
    _advance_phase(c)


# ── snapshot for the API/frontend ──
def snapshot(c):
    season = current_season(c)
    m = SEASON_META[season]
    return {
        "season": season, "emoji": m["emoji"], "tint": m["tint"],
        "festival": m["festival"], "bonus": m["bonus"],
        "day": year_day(c), "phase": phase(c),
    }
