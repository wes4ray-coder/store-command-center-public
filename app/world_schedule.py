"""THE COMPANY — town day/night SCHEDULE (RimWorld #6, temporal gating).

A 24-hour town timetable: each hour is one of Sleep / Work / Free (recreation) /
Anything. The behaviour picker (_choose in world_sim) obeys the current hour's
band — the crew sleeps on the Sleep block, pushes through minor needs and works
on the Work block, blows off steam on the Free block, and falls back to plain
need-driven behaviour on Anything. Critical needs (near-collapse, starving) and
raids always override the schedule.

The spatial half of #6 (restrict an agent to an area) is already covered by the
play-god pick-up/drop-to-a-spot posting. State: world_meta.town_schedule (json
array of 24 band strings). Decoupled; degrades gracefully.
"""
import json
from world_defs import mget, mset

BANDS = ["sleep", "work", "rec", "any"]
BAND_META = {
    "sleep": ("😴", "Sleep", "#6d7a90"),
    "work":  ("💼", "Work",  "#3fae6a"),
    "rec":   ("🎉", "Free",  "#e0b050"),
    "any":   ("•",  "Anything", "#4a90d9"),
}
# sensible default: sleep 0-5, ease-in 6-7, work 8-16, free 17-19, work 20-21, sleep 22-23
_DEFAULT = (["sleep"] * 6 + ["any"] * 2 + ["work"] * 9 + ["rec"] * 3 + ["work"] * 2 + ["sleep"] * 2)


def get(c):
    try:
        s = json.loads(mget(c, "town_schedule", "null") or "null")
        if isinstance(s, list) and len(s) == 24 and all(b in BANDS for b in s):
            return s
    except Exception:
        pass
    return list(_DEFAULT)


def band(c, hour):
    return get(c)[int(hour) % 24]


def set_hour(c, hour, b):
    if b in BANDS and 0 <= int(hour) < 24:
        s = get(c)
        s[int(hour)] = b
        mset(c, "town_schedule", json.dumps(s))
        return True
    return False


def set_all(c, sched):
    if isinstance(sched, list) and len(sched) == 24 and all(b in BANDS for b in sched):
        mset(c, "town_schedule", json.dumps(sched))
        return True
    return False


def snapshot(c, hour):
    return {"schedule": get(c), "hour": int(hour) % 24, "band": band(c, hour),
            "meta": {b: {"icon": m[0], "label": m[1], "color": m[2]} for b, m in BAND_META.items()}}
