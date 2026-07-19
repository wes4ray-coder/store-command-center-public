"""
The Company — simulation engine (the physics of the world).

Advances the world by real elapsed time each tick: pays agents for REAL completed
store work (event-driven, never for merely sitting), decays/refills Sims-style
needs, charges rent + bills, chooses need-driven behaviour (which is why they walk
around), and derives each agent's mood.

Governance (opinions/meetings) lives in world_gov.py; asset generation in
world_build.py; shared constants/helpers in world_defs.py.
"""
import time, json, sqlite3

from deps import get_conn
from world_defs import (NEEDS, OPENCLAW_DB, mget, mset, clamp, level_for,
                        log_agent, log_town)
import world_skills
import world_settings
import jellycoin
import world_orchestra
import world_learn
import world_tech
import world_construct
import world_work
import world_mood
import world_raid
import world_research
import world_schedule
import world_items

SKILL_FULFILL_GAIN = 9.0        # skilling gives purpose (net-positive vs idle drain)
DWELL_SEC = 80                  # min seconds an agent commits to an idle activity (kills the jitter)
_DWELL_STATES = ("skilling", "studying", "leisure", "idle", "sitting", "picnicking", "admiring")
_SUBSTATES = ("busy", "glance", "pause", "potter")


def _idle_substate(a, now, state):
    """A slowly-cycling micro-behaviour so idle agents look natural, not frozen or jittery."""
    if state in ("working", "defending"):
        return "busy"
    if state in ("sleep",):
        return "rest"
    return _SUBSTATES[(a["id"] + int(now / 13)) % len(_SUBSTATES)]
from world_balance import (WAGE_PER_JOB, XP_PER_JOB, RENT, BILLS, BILL_CYCLE_SEC,
                           DT_CAP, COMPANY_TAX, NEED_DECAY, PLACE_RESTORE,
                           WORK_ENERGY_DRAIN, WORK_FULFILL_GAIN, WORK_FUN_DRAIN,
                           IDLE_ENERGY_DRAIN, IDLE_FULFILL_DRAIN,
                           MONOTONY_GRACE_SEC, MONOTONY_SLOPE, MONOTONY_FLOOR,
                           THRIVE_GREEN, THRIVE_MULT, BLESS_MULT)

# Real, completed store-work signals → which department did the work. Each is a
# monotonic COUNT of finished units; agents are paid on the *increase*.
WORK_METRICS = {
    "gen_done":    ("SELECT COUNT(*) FROM generations  WHERE status='done'",                     "image"),
    "video_done":  ("SELECT COUNT(*) FROM videos       WHERE status='done'",                     "video"),
    "audio_done":  ("SELECT COUNT(*) FROM audio_clips  WHERE status='done'",                     "audio"),
    "m3d_pub":     ("SELECT COUNT(*) FROM models3d     WHERE status='published'",                "models3d"),
    "designs_pub": ("SELECT COUNT(*) FROM designs      WHERE status='published'",                "etsy"),
    "portal_push": ("SELECT COUNT(*) FROM portal_pushes",                                        "portal"),
    "resell_post": ("SELECT COUNT(*) FROM automation_log WHERE action='post' AND status='done'", "resell"),
    "trend_prop":  ("SELECT COUNT(*) FROM proposals",                                            "trends"),
    # the store's newer arms pay their own crews now
    "social_post": ("SELECT COUNT(*) FROM social_posts",                                         "social"),
    "fin_mission": ("SELECT COUNT(*) FROM money_missions",                                       "finance"),
    "fin_backtest": ("SELECT COUNT(*) FROM crypto_backtests",                                    "finance"),
    "fin_send":    ("SELECT COUNT(*) FROM wallet_sends",                                         "finance"),
    "sec_fixed":   ("SELECT COUNT(*) FROM security_findings WHERE status='remediated'",          "netsec"),
    "swarm_step":  ("SELECT COUNT(*) FROM swarm_events WHERE kind IN ('plan','code','test','result')", "swarm"),
    "research_done": ("SELECT COUNT(*) FROM research_projects WHERE status='done'",              "research"),
}

# In-progress signals — makes the right worker *look* busy at their desk (no pay).
BUSY_METRICS = {
    "image":    "SELECT COUNT(*) FROM generations WHERE status IN ('queued','generating')",
    "video":    "SELECT COUNT(*) FROM videos      WHERE status IN ('queued','generating','pending')",
    "audio":    "SELECT COUNT(*) FROM audio_clips WHERE status IN ('queued','generating','pending')",
    "models3d": "SELECT COUNT(*) FROM models3d    WHERE status IN ('queued','generating','pending')",
    # time-bound: a stuck 'running' row (crashed automation) must NOT signal forever
    "resell":   "SELECT COUNT(*) FROM automation_log WHERE status='running' AND created_at > datetime('now','-10 minutes')",
    "research": "SELECT COUNT(*) FROM research_projects WHERE status='running'",
}


def _pay(c, a, delta, reason, event=True):
    """Apply a coin delta to agent dict `a`; write ledger + (optional) event."""
    if delta > 0:                   # research: Marketing/Analytics lift EARNINGS (not bills) (#7)
        delta = int(round(delta * float(mget(c, "research_pay_mult", 1.0) or 1.0)))
    bal = (a["coins"] or 0) + delta
    debt = a["debt"] or 0
    if bal < 0:                     # can't cover it → to debt, wallet floored at 0
        debt += -bal
        bal = 0
    a["coins"], a["debt"] = bal, debt
    if delta > 0:
        a["coins_earned"] = (a["coins_earned"] or 0) + delta
    c.execute("INSERT INTO world_ledger (agent_key,delta,reason,balance_after) VALUES (?,?,?,?)",
              (a["key"], delta, reason, bal))
    if event:
        icon = "🪙" if delta >= 0 else "💸"
        c.execute("INSERT INTO world_events (agent_key,kind,text) VALUES (?,?,?)",
                  (a["key"], "job_done" if delta >= 0 else "bill",
                   f"{icon} {a['name']} {'earned' if delta>=0 else 'paid'} {abs(delta)} — {reason}."))


def simulate(conn):
    """Advance the world by the real time elapsed since the last tick."""
    c = conn.cursor()
    now = time.time()
    last = float(mget(c, "last_tick", 0) or 0)
    dt = now - last
    if last and dt < 2:
        return                       # debounce very frequent polls
    dt = min(dt if last else 20, DT_CAP)
    mset(c, "last_tick", now)

    agents = [dict(r) for r in c.execute("SELECT * FROM world_agents ORDER BY id").fetchall()]
    by_class = {}
    for a in agents:
        by_class.setdefault(a["job_class"], []).append(a)

    # 1) REAL WORK → PAY. Compare monotonic completion counts to last-seen.
    fund_gain = 0
    for metric, (sql, klass) in WORK_METRICS.items():
        try:
            cur = c.execute(sql).fetchone()[0]
        except Exception:
            continue
        prev = int(float(mget(c, f"m_{metric}", cur)))      # first run: no back-pay
        mset(c, f"m_{metric}", cur)
        delta = max(0, cur - prev)
        if not delta:
            continue
        workers = [w for w in (by_class.get(klass) or []) if w["job_class"] == klass] \
                  or by_class.get(klass) or []
        if not workers:
            continue
        for i in range(min(delta, 20)):                     # sane cap per tick
            w = world_learn.pick_worker(c, workers) or workers[i % len(workers)]  # merit routing (system E)
            kmult = world_skills.knowledge_mult(c, w["key"])  # library study → better at the job
            # FLUX bonuses: all needs in the green = thriving (balance pays best);
            # a recent blessing from god = temp buff (god lifts, the company drains)
            thrive = THRIVE_MULT if all((w[n] or 0) >= THRIVE_GREEN for n in NEEDS) else 1.0
            bless = BLESS_MULT if (w.get("blessed_until") or 0) > now else 1.0
            if thrive > 1:
                world_mood.add_thought(c, w["key"], "firing on all cylinders", 5, hours=6, unique=True)
            wage = int(round(WAGE_PER_JOB * (w["earn_mult"] or 1.0) * kmult * thrive * bless))
            _pay(c, w, wage, f"finished {klass} work")
            world_mood.add_thought(c, w["key"], "shipped good work", 6, hours=8, unique=True)  # mood boost
            fund_gain += round(WAGE_PER_JOB * COMPANY_TAX)   # company's cut of the work
            w["xp"] = (w["xp"] or 0) + int(round(XP_PER_JOB * kmult * thrive * bless))
            w["jobs_done"] = (w["jobs_done"] or 0) + 1
            w["fulfillment"] = clamp((w["fulfillment"] or 0) + 14)
            w["energy"] = clamp((w["energy"] or 0) - 4)
            log_agent(w["key"], w["name"], f"Completed {klass} work (+{wage}🪙).")

    # 1b) OpenClaw agents — pay per succeeded task_run (their real work).
    fund_gain += _pay_openclaw(c, by_class.get("agent", []))
    if fund_gain:
        mset(c, "company_fund", int(float(mget(c, "company_fund", 0) or 0)) + fund_gain)

    # 2) Who is actively busy right now (working animation; unpaid).
    busy_now = {}
    for klass, sql in BUSY_METRICS.items():
        try:
            busy_now[klass] = c.execute(sql).fetchone()[0]
        except Exception:
            busy_now[klass] = 0

    # 3) NEEDS decay + place-based restoration, then behaviour + mood.
    hour = int(time.strftime("%H"))
    sched_band = world_schedule.band(c, hour)          # town timetable for this hour (#6)
    raiding = world_orchestra.phase(c) == "raid"      # all hands to defense during a raid
    raid_id = int(float(mget(c, "raid_counter", 0) or 0))
    raid_roles = {}
    if raiding:                                        # compute the fight/build/medic split ONCE for the roster
        _dk = [a["key"] for a in agents if a["kind"] in ("worker", "openclaw")]
        raid_roles = world_raid.combat_roles(c, _dk, raid_id)
    for klass, workers in by_class.items():
        if klass in ("mayor", "boss"):
            continue                    # leaders handled separately (no work, derived mood)
        for idx, a in enumerate(workers):
            has_work = (klass != "agent" and idx < busy_now.get(klass, 0))
            _tick_needs(a, dt, has_work)
            # MENTAL BREAK (RimWorld): a broken agent hijacks its own behaviour + refuses work
            if a.get("break_until") and not world_mood.is_broken(a):
                world_mood.end_break(c, a)                  # timer elapsed → catharsis, back to normal
            if world_mood.is_broken(a):
                emoji, label = world_mood.break_view(a)
                a["state"] = "breakdown"
                a["location"] = "home" if a.get("break_kind") == "sadwander" else "park"
                a["goal"] = label
                a["mood_emoji"], a["mood_label"] = emoji, label
                a["substate"] = "break"
                a["level"] = level_for(a["xp"] or 0)
                continue                                    # broken → no work this tick
            if raiding:
                if a.get("downed"):                        # combat depth (#8): out of the fight, awaiting a medic
                    a["role"] = "downed"
                    state, loc, goal = "downed", "infirmary", "wounded — a medic is on the way"
                else:
                    # canonical role split (fight / build / medic) shared with world_raid.raid_tick
                    role = raid_roles.get(a["key"], "fight")
                    a["role"] = role
                    state, loc = "defending", "defense"
                    goal = {"build": "raising the barricades", "medic": "tending the wounded",
                            "fight": "fighting off the raiders"}.get(role, "fighting off the raiders")
            elif a.get("posted_to") and now < (a.get("posted_until") or 0):
                # PLAY-GOD POST (RCT-style): the player picked this agent up and dropped
                # them on a task/spot — obey it over the scheduler until it expires.
                a["role"] = None
                pk = a.get("posted_kind") or "spot"
                if pk == "skill" and a["posted_to"] in world_skills.NODE_SKILL:
                    state, loc, goal = "skilling", a["posted_to"], f"posted to the {a['posted_to']}"
                else:
                    state, loc, goal = "idle", "posted", "standing where you dropped them"
                a["dwell_until"] = 0
            else:
                a["role"] = None
                if a.get("posted_to"):                     # a post just expired → release cleanly
                    c.execute("UPDATE world_agents SET posted_to=NULL, posted_kind=NULL WHERE id=?", (a["id"],))
                    a["posted_to"] = None
                ch_state, ch_loc, ch_goal = _choose(a, has_work, hour, sched_band)
                if ch_state == "productive":
                    # DWELL: stick with the current activity until dwell expires (no more jitter)
                    if now < (a.get("dwell_until") or 0) and a.get("state") in _DWELL_STATES and a.get("location"):
                        state, loc, goal = a["state"], a["location"], a.get("goal") or "keeping busy"
                    else:
                        # Work-Priority scheduler: first available job in the agent's priority order
                        job = world_work.choose_work(c, a, {"has_work": has_work, "hour": hour, "t": now})
                        state, loc, goal = job["state"], job["location"], job["goal"]
                        try:                                     # grinders dwell long, switchers hop (genome)
                            import world_genome
                            _focus = world_genome.genome(a)["focus"]
                        except Exception:
                            _focus = 1.0
                        a["dwell_until"] = now + DWELL_SEC * _focus + (a["id"] % 6) * 8   # staggered so they don't all re-pick together
                else:
                    state, loc, goal = ch_state, ch_loc, ch_goal
                    a["dwell_until"] = 0                    # forced (work/sleep/need) → free to re-pick after
            a["substate"] = _idle_substate(a, now, state)
            # NOTE: routine idle movement (chopping wood, fishing, wandering) is NOT posted to the
            # town feed — it belongs in each agent's own journal (log_agent). Only town-level events
            # (raids, tech, meetings, incidents, achievements) reach the feed. Keeps it readable.
            if a.get("location") != loc and state not in ("working", "skilling", "studying", "leisure", "productive"):
                log_agent(a["key"], a["name"], goal)
            a["state"], a["location"], a["goal"] = state, loc, goal
            # MONOTONY: grinding one activity nonstop yields less and less (floor 35%).
            # The bandit's reward shrinks with it, so agents LEARN to rotate — the
            # anti-"do one thing forever" pressure that keeps lives varied.
            if a.get("streak_state") != state:
                a["streak_state"], a["streak_since"] = state, now
            streak = now - (a.get("streak_since") or now)
            mono = max(MONOTONY_FLOOR, 1.0 - max(0.0, streak - MONOTONY_GRACE_SEC) * MONOTONY_SLOPE)
            if mono < 0.8 and state in ("skilling", "studying"):
                world_mood.add_thought(c, a["key"], f"worn out on nonstop {state}", -4, hours=2, unique=True)
            if state == "skilling":                     # idle labour → skill XP + stockpile
                skill = world_skills.NODE_SKILL.get(loc) or world_skills.primary_skill(a)
                xp, res, units = world_skills.gather(c, a, skill, dt * mono)
                a["fulfillment"] = clamp((a["fulfillment"] or 0) + SKILL_FULFILL_GAIN * mono * (dt / 60.0))
                world_learn.record_reward(c, a["key"], skill, xp)     # bandit reward = xp earned
                if skill == "construction":                           # build the town's structures (haul/frame/build)
                    world_construct.advance(c, 2 + units * 3, a)
                if units:
                    log_agent(a["key"], a["name"], f"{skill}: gathered {units} {res} (+{xp}xp).")
                    # JellyCoin tie-in (god-toggled): real skilling queues boost tickets
                    # that pay out ONLY inside a real GPU-mined block. Never mines here.
                    try:
                        if world_settings.b("world_crypto_mining_enabled", c):
                            jellycoin.skill_pulse(c, a["key"], a["name"], skill, units)
                    except Exception:
                        pass    # the coin must never be able to break the sim
            elif state == "studying":                   # library → Knowledge (buffs real-job output) + research
                if _rand_book() and (a["id"] + int(now / 8)) % 40 == 0:   # ~occasionally: what they're reading
                    log_agent(a["key"], a["name"], f"📚 Read about “{_rand_book()}” in the library archives.")
                kxp, klvl = world_skills.study(c, a, dt * mono)
                a["fulfillment"] = clamp((a["fulfillment"] or 0) + SKILL_FULFILL_GAIN * 0.6 * mono * (dt / 60.0))
                world_learn.record_reward(c, a["key"], "study", kxp)
                world_tech.add_research(c, kxp * 0.5)     # study drives the material ladder (chunk 4)
                world_research.tick_research(c, kxp * 0.5)  # …and the research TREE (#7)
            elif state == "leisure":                    # bandit learns leisure pays off when needs are low
                avg = sum(a[n] or 0 for n in NEEDS) / len(NEEDS)
                world_learn.record_reward(c, a["key"], "leisure", max(3.0, (100 - avg) * 0.25))
            world_items.tick_agent(c, a, now)           # eat / grocery run / furnish (may set 'shopping')
            a["mood_emoji"], a["mood_label"] = _mood(a, has_work)
            a["level"] = level_for(a["xp"] or 0)
            mood = world_mood.mood_of(c, a)              # thought-ledger mood → maybe a mental break next tick
            world_mood.maybe_break(c, a, mood)

    # 3b) Leaders: never work; wellbeing mirrors those they serve.
    citizens = [a for a in agents if a["job_class"] not in ("mayor", "boss")]
    workers_only = [a for a in agents if a["kind"] == "worker"]
    town_h  = sum(_happiness(a) for a in citizens) / len(citizens) if citizens else 60
    staff_h = sum(_happiness(a) for a in workers_only) / len(workers_only) if workers_only else 60
    for a in agents:
        if a["job_class"] == "mayor":
            _lead(a, town_h, "townhall", "the town")
        elif a["job_class"] == "boss":
            _lead(a, staff_h, "exec", "the crew")

    # 4) BILLS on the cycle (leaders are exempt — they live off the company).
    last_bill = float(mget(c, "last_bill", now) or now)
    if now - last_bill >= BILL_CYCLE_SEC:
        mset(c, "last_bill", now)
        for a in agents:
            if a["job_class"] in ("mayor", "boss"):
                continue
            _pay(c, a, -(RENT + BILLS), "rent + bills")
            world_mood.add_thought(c, a["key"], "paid the bills", -5, hours=5, unique=True)
            log_agent(a["key"], a["name"], f"Paid rent+bills ({RENT+BILLS}🪙).")
        log_town(f"Rent day: everyone charged {RENT+BILLS}🪙.")

    # 5) persist
    for a in agents:
        c.execute("""UPDATE world_agents SET
            coins=?, coins_earned=?, debt=?, xp=?, level=?, jobs_done=?,
            energy=?, fun=?, social=?, fulfillment=?, hunger=?,
            mood_emoji=?, mood_label=?, goal=?, state=?, location=?,
            dwell_until=?, substate=?, role=?, break_until=?, break_kind=?,
            streak_state=?, streak_since=?,
            updated_at=datetime('now') WHERE id=?""",
            (a["coins"], a["coins_earned"], a["debt"], a["xp"], a["level"], a["jobs_done"],
             a["energy"], a["fun"], a["social"], a["fulfillment"], a["hunger"],
             a["mood_emoji"], a["mood_label"], a["goal"], a["state"], a["location"],
             a.get("dwell_until") or 0, a.get("substate"), a.get("role"),
             a.get("break_until") or 0, a.get("break_kind"),
             a.get("streak_state"), a.get("streak_since") or 0, a["id"]))
    conn.commit()


def _pay_openclaw(c, oc_agents):
    """Pay OpenClaw agents per newly-succeeded task_run. Returns the company-fund cut."""
    if not oc_agents or not OPENCLAW_DB.exists():
        return 0
    try:
        oc = sqlite3.connect(f"file:{OPENCLAW_DB}?mode=ro&immutable=1", uri=True, timeout=2)
        counts = {r[0]: r[1] for r in oc.execute(
            "SELECT agent_id, COUNT(*) FROM task_runs WHERE status='succeeded' GROUP BY agent_id")}
        oc.close()
    except Exception:
        return 0
    try:
        prev = json.loads(mget(c, "oc_succeeded", "{}") or "{}")
    except Exception:
        prev = {}
    fund = 0
    for a in oc_agents:
        cur = counts.get(a["key"], 0)
        was = int(prev.get(a["key"], cur))     # first run: no back-pay
        for _ in range(min(max(0, cur - was), 20)):
            wage = int(round(WAGE_PER_JOB * (a["earn_mult"] or 1.0)))
            _pay(c, a, wage, "finished an agent task")
            fund += round(WAGE_PER_JOB * COMPANY_TAX)
            a["xp"] = (a["xp"] or 0) + XP_PER_JOB
            a["jobs_done"] = (a["jobs_done"] or 0) + 1
            a["fulfillment"] = clamp((a["fulfillment"] or 0) + 14)
            log_agent(a["key"], a["name"], "Completed a real OpenClaw task (+%d🪙)." % wage)
    mset(c, "oc_succeeded", json.dumps(counts))
    return fund


def _happiness(a):
    """0..100 wellbeing score for an agent (needs average, docked by debt)."""
    return clamp(sum(a[n] or 0 for n in NEEDS) / len(NEEDS) - min(30, a["debt"] or 0))


def _lead(a, h, loc, who):
    """A leader's stats mirror the happiness of those they serve."""
    a["fulfillment"] = clamp(h)
    a["energy"] = clamp(max(a["energy"] or 0, 65))     # leaders don't tire from labour
    a["state"], a["location"], a["goal"] = "overseeing", loc, f"overseeing {who}"
    if h >= 70:
        a["mood_emoji"], a["mood_label"] = "😌", f"proud of {who}"
    elif h >= 45:
        a["mood_emoji"], a["mood_label"] = "🤔", f"watching {who} closely"
    else:
        a["mood_emoji"], a["mood_label"] = "😠", f"worried about {who}"
    a["level"] = level_for(a["xp"] or 0)


# ── the library's "books" are the town's own knowledge graph (graphify) ──────
_BOOKS = {"t": 0.0, "names": []}

def _rand_book():
    """A random graphify node name — the agents literally study the codebase
    that runs their world. Cached 10 min; empty if no graph is built."""
    import json as _json, random as _r, time as _t
    if _t.time() - _BOOKS["t"] > 600:
        _BOOKS["t"] = _t.time()
        try:
            from pathlib import Path
            from config import BASE
            g = _json.loads((Path(BASE) / "graphify-out" / "graph.json").read_text())
            _BOOKS["names"] = [str(n.get("id") or n.get("name"))[:48]
                               for n in (g.get("nodes") or [])[:4000]
                               if isinstance(n, dict) and (n.get("id") or n.get("name"))]
        except Exception:
            _BOOKS["names"] = []
    return _r.choice(_BOOKS["names"]) if _BOOKS["names"] else None


def _tick_needs(a, dt, has_work):
    """Decay/restore needs based on elapsed seconds and where the agent is.
    Rates are data-driven from world_balance so tuning never touches this code."""
    m = dt / 60.0
    for need, rate in NEED_DECAY.items():
        a[need] = clamp((a[need] or 0) - rate * m)
    if has_work:
        a["energy"]      = clamp((a["energy"] or 0)      - WORK_ENERGY_DRAIN * m)
        a["fulfillment"] = clamp((a["fulfillment"] or 0) + WORK_FULFILL_GAIN * m)
        a["social"]      = clamp((a["social"] or 0)      - 0.6 * m)
        a["fun"]         = clamp((a["fun"] or 0)         - WORK_FUN_DRAIN * m)   # the company grinds them down
    else:
        a["energy"]      = clamp((a["energy"] or 0)      - IDLE_ENERGY_DRAIN * m)
        a["fulfillment"] = clamp((a["fulfillment"] or 0) - IDLE_FULFILL_DRAIN * m)  # idleness erodes purpose
    for need, gain in PLACE_RESTORE.get(a.get("location") or "home", {}).items():
        a[need] = clamp((a[need] or 0) + gain * m)


def _choose(a, has_work, hour, sched="any"):
    """Need-driven behaviour → (state, location, goal-phrase), gated by the town
    SCHEDULE band (#6). Critical needs and exhaustion always override the schedule.
    HYSTERESIS: once an agent goes home exhausted it rests until recharged."""
    energy = a["energy"] or 0
    was = a.get("state")
    # CHRONOTYPE: every agent has a personal rhythm (early birds, night owls,
    # light and heavy sleepers) derived from a stable id hash — thresholds vary
    # per person, so the town never crashes/wakes in lockstep and behaviour
    # reads as individual free will instead of one shared state machine.
    ch = (a["id"] * 2654435761) & 0xffff
    wake = 38 + (ch % 17)                   # recharge until 38..54 energy
    crash = 16 + ((ch >> 4) % 11)           # collapse point 16..26
    sleepy = 72 + ((ch >> 8) % 19)          # how full the tank must be to skip scheduled sleep
    # recovering from exhaustion → stay home until genuinely recharged (no flip)
    if was == "sleep" and energy < wake:
        return "sleep", "home", ["sleeping in", "resting up", "recharging — do not disturb"][ch % 3]
    # SCHEDULE 'sleep' block → off the clock (unless wide awake) + hard exhaustion any time
    if (sched == "sleep" and energy < sleepy) or energy < crash:
        return "sleep", "home", "off the clock — resting" if sched == "sleep" else "heading home to rest"
    # starving always interrupts
    if (a["hunger"] or 0) < 24:
        return "leisure", "cafe", "grabbing a bite at the café"
    # 'work' block → push through minor needs; only a real fun-crash takes a quick break
    if sched == "work":
        if (a["fun"] or 0) < 16:
            return "leisure", LEISURE_FUN[a["id"] % len(LEISURE_FUN)], "a quick break, then back to it"
        return "productive", None, None
    # 'rec' (Free) block → go enjoy the town (venues + the public spaces: benches,
    # the picnic green, the plaza). Rotates by hour so the same agent drifts between
    # spots across a free block instead of camping one venue all day.
    if sched == "rec":
        if (a["social"] or 0) < 45:
            return "leisure", "bar", "unwinding with the crew"
        loc = LEISURE_TOWN[(a["id"] + (hour // 4)) % len(LEISURE_TOWN)]
        return LEISURE_SPOTS.get(loc, "leisure"), loc, LEISURE_GOALS.get(loc, "enjoying some free time")
    # 'any' block → the original need-driven wander
    if (a["fun"] or 0) < 28:
        return "leisure", LEISURE_FUN[(a["id"]) % len(LEISURE_FUN)], "blowing off steam"
    if (a["social"] or 0) < 32:
        return "leisure", "bar", "catching up with the crew"
    if (a["coins"] or 0) <= 0 or (a["debt"] or 0) > 0:
        return "idle", "park", "broke — pacing the park, itching for work"
    if (a["fulfillment"] or 0) < 42:
        return "praying", "church", "finding some peace at the church"
    return "productive", None, None      # the bandit (world_learn) picks the activity in simulate

LEISURE_FUN = ["arcade", "tv"]
LEISURE_ALL = ["bar", "arcade", "tv", "park", "cafe"]
# Public-space leisure (Mayor's park & plaza upgrade): these locations come with
# their own visible state instead of generic 'leisure', so sitting/picnicking/
# admiring read on the map. Frontend registers the matching WM.locations keys.
LEISURE_SPOTS = {"bench": "sitting", "picnic": "picnicking", "plaza": "admiring"}
LEISURE_TOWN = LEISURE_ALL + list(LEISURE_SPOTS)
LEISURE_GOALS = {"bench": "resting on a park bench", "picnic": "having a picnic on the green",
                 "plaza": "admiring the plaza fountain"}


def _mood(a, has_work):
    if (a["debt"] or 0) > 0:
        return "😫", "drowning in bills"
    if (a["coins"] or 0) <= 0 and not has_work:
        return "😟", "broke and worried"
    if (a["energy"] or 0) < 22:
        return "😴", "exhausted"
    if (a["hunger"] or 0) < 25:
        return "🍽️", "hungry"
    if (a["fulfillment"] or 0) < 28 and not has_work:
        return "😒", "bored — wants real work"
    if (a["fun"] or 0) < 25:
        return "😑", "restless"
    if (a["social"] or 0) < 25:
        return "🥺", "lonely"
    avg = sum(a[n] or 0 for n in NEEDS) / len(NEEDS)
    if avg > 72 and (a["coins"] or 0) > 60:
        return "😄", "thriving"
    if avg > 55:
        return "🙂", "content"
    return "😕", "getting by"
