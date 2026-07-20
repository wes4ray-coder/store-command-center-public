"""JellyCoin (JLY) API — the store's own GPU-mined token + NFTs + agent missions.

Endpoints (chain logic lives in jellycoin.py):
  - /api/jelly/status, /blocks, /wallets, /transfer, /tip — ledger + explorer.
  - /api/jelly/mining/work + /submit — the getwork protocol for GPU rigs. These
    two (plus the miner download) are reachable from OTHER LAN boxes without a
    session (main.py bypass) but self-guard with the X-Jelly-Token header
    against settings.jelly_miner_token — same pattern as /api/money/signals.
    There is NO CPU mining: the server only VERIFIES hashes, and the shipped
    miner refuses to start without an OpenCL GPU. getwork also HOLDS (503 +
    {"pause": true}) while the AI queue owns the GPU — see mining_hold().
  - /api/jelly/miner-policy — the OWNER's mining envelope: per-rig intensity
    (throttle/batch, handed to the rig live inside getwork), allowed hours, and
    a real daily hour budget. Enforced server-side in mining_hold(), so even an
    un-updated miner obeys — it just receives the same 503 hold.
  - /api/jelly/agent-plan — the Company may pick when/how hard to mine, but only
    INSIDE that envelope, and only while its own toggle is on (default OFF).
  - /api/jelly/miner-defense — 51%-defence: measures our share of network
    hashpower from the block table and ramps our own rigs when it erodes.
  - /api/jelly/nft/* — mint real art files as NFTs (content-hash on chain).
  - /api/jelly/missions/* — LLM-drafted "push JLY" pitches from the Company.
    Drafts NEVER act on their own: every mission sits in 'proposed' until the
    god (you) approves or rejects it. Approval posts it to the town feed so
    agents can talk it up in-world; nothing external is auto-posted.
"""
import hmac
import json
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Body, Request
from fastapi.responses import FileResponse, JSONResponse

from deps import *          # get_conn, get_setting, _call_lmstudio, logger
import jellycoin
from prompts import get_prompt
from world_defs import run_llm_job

router = APIRouter()

MINER_TOKEN_KEY = "jelly_miner_token"
_MINER_FILE = Path(__file__).resolve().parent.parent.parent / "miner" / "jellyminer.py"
_INSTALLER_FILE = (Path(__file__).resolve().parent.parent.parent
                   / "deploy" / "miner" / "install-miner.sh")


def _miner_token() -> str:
    tok = get_setting(MINER_TOKEN_KEY)      # get_setting transparently decrypts
    if not tok:
        import crypto as _secrets_at_rest   # app/crypto.py — settings encryption
        tok = secrets.token_hex(16)
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (MINER_TOKEN_KEY, _secrets_at_rest.enc(tok)))
        conn.commit()
        conn.close()
    return tok


def _check_miner(request: Request):
    """LAN rigs authenticate with X-Jelly-Token; same-box calls ride the localhost bypass."""
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1", "testclient"):
        return
    if not hmac.compare_digest(request.headers.get("X-Jelly-Token", ""), _miner_token()):
        raise HTTPException(403, "bad or missing X-Jelly-Token")


# ── yield-to-queue: mining stands down while the AI queue owns the GPU ────────
# The node runs LM Studio + ComfyUI for the store's AI work AND mines JLY on the
# same card. Sharing it produces real failures ("could not load required model X",
# "the GPU may be busy with another model or ComfyUI"), so getwork HOLDS while the
# queue is working: the server is authoritative, the miner just obeys.
#
# Mirrors routers/gpu_guard.py, but in the opposite direction — the guard pauses
# the QUEUE for a game; this pauses MINING for the queue. Same busy signal
# (gpu_guard._store_busy), same settings-toggle conventions.
#
#   jelly_miner_yield_to_queue (1) — master toggle; 0/off ⇒ never hold (old
#                                    always-on throttled coexistence).
#   jelly_miner_settle_sec    (45) — queue must be idle THIS long before mining
#                                    resumes (anti-flap).
#   jelly_miner_retry_sec     (15) — how long a held rig is told to sleep.
YIELD_KEY, SETTLE_KEY, RETRY_KEY = (
    "jelly_miner_yield_to_queue", "jelly_miner_settle_sec", "jelly_miner_retry_sec")
SETTLE_DEFAULT, RETRY_DEFAULT = 45, 15

_yield = {"held": False, "idle_since": 0.0, "since": 0.0}


def _yield_enabled() -> bool:
    return str(get_setting(YIELD_KEY, "1")).strip().lower() not in ("0", "off", "false", "no")


def _yield_num(key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(get_setting(key, default)))))
    except Exception:
        return default


def _settle_sec() -> int:
    return _yield_num(SETTLE_KEY, SETTLE_DEFAULT, 0, 600)


def _retry_sec() -> int:
    return _yield_num(RETRY_KEY, RETRY_DEFAULT, 2, 300)


def _queue_busy() -> bool:
    """The orchestrator's own busy state — the same thing /api/queue reports and
    the same first clause gpu_guard._store_busy tests. Not a second definition.

    Deliberately NOT the DB 'generating' row scan gpu_guard adds on top: every
    media job (image/video/3D/audio) bumps _active_images and releases it in a
    finally, so orch.status() is live and self-clearing, while a crashed row can
    sit at 'generating' forever and would wedge mining shut for good."""
    try:
        from orchestrator import orch
        s = orch.status()
        return (s["llm"] != "idle" or s["image"] != "idle"
                or s["active_images"] > 0 or bool(s["queue"]))
    except Exception:
        return False


def _queue_hold(now: float = 0.0) -> dict:
    """Should mining stand down for the AI QUEUE right now? The hold payload, or {}.

    Hysteresis in both directions:
      • busy → hold IMMEDIATELY. One momentary job is enough; a model load that
        races a mining batch is exactly the failure being fixed here.
      • idle → keep holding until the queue has been quiet for `settle_sec`, so a
        burst of queued jobs can't make the rig start/stop every few seconds.
    Idempotent and time-based, so any caller (getwork, the UI poll) may drive it.
    """
    now = now or time.time()
    if not _yield_enabled():
        _yield.update(held=False, idle_since=0.0, since=0.0)
        return {}
    busy, settle = _queue_busy(), _settle_sec()
    if busy:
        if not _yield["held"]:
            _yield["since"] = now
            logger.info("[jelly] AI queue busy — holding GPU mining")
        _yield.update(held=True, idle_since=0.0)
    elif _yield["held"]:
        if not _yield["idle_since"]:
            _yield["idle_since"] = now
        if now - _yield["idle_since"] >= settle:
            logger.info(f"[jelly] queue idle {settle}s — releasing GPU mining hold")
            _yield.update(held=False, idle_since=0.0, since=0.0)
    if not _yield["held"]:
        return {}
    retry, left = _retry_sec(), 0
    if not busy:
        left = max(0, int(settle - (now - _yield["idle_since"])))
        retry = max(1, min(retry, left or retry))
    return {"pause": True, "retry_after": retry, "busy": busy,
            "reason": ("the AI queue is using the GPU" if busy
                       else f"queue just went idle — settling for {left}s"),
            "settle_sec": settle, "resume_in": left,
            "held_for": int(now - _yield["since"]) if _yield["since"] else 0}


def _touch_rig(miner: str, gpu: str, hashrate: float):
    """Keep a HELD rig's heartbeat fresh so the UI shows it online-but-paused
    rather than pretending it died. Hashrate is left at its last measured value."""
    miner = (miner or "").strip()[:40]
    if not miner:
        return
    try:
        conn = get_conn()
        try:
            jellycoin.ensure_schema(conn)
            conn.execute(
                "INSERT INTO jelly_miners (name,gpu,last_seen,hashrate) VALUES (?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET gpu=excluded.gpu, last_seen=excluded.last_seen",
                (miner, (gpu or "")[:120], int(time.time()), float(hashrate or 0)))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"[jelly] held-rig heartbeat failed: {e}")


# ═══ owner controls: intensity, schedule windows, daily hour budget ══════════
# Three layers decide how hard (and whether) a rig mines, narrowest last:
#
#   1. OWNER envelope   — per-rig throttle/batch, allowed hours, daily budget.
#                         Nothing below may ever widen this.
#   2. AGENT plan       — the Company picks when/how hard INSIDE the envelope.
#                         Gated by its own toggle, default OFF.
#   3. DEFENCE ramp     — if our share of network hashpower erodes, our own rigs
#                         ramp UP. Owner-enabled, bounded, and loudly logged.
#
# Intensity reaches the rig LIVE, inside the getwork response ("policy"), so a
# change takes effect on the next batch with no reinstall and no restart. An old
# miner that never looks at the field simply keeps its install-time CLI values —
# which is why enforcement of the *schedule* lives here in mining_hold() instead:
# an un-updated rig cannot ignore an HTTP 503.
#
# Timezone: the box's LOCAL time (time.localtime) throughout — windows, "today"
# for the budget, and the UI all agree because they all come from here.
POLICY_KEY = "jelly_rig_policy"                 # JSON {rig|__default__: {throttle,batch,cost}}
SCHED_ON_KEY = "jelly_sched_enabled"            # master toggle, default OFF
SCHED_WIN_KEY = "jelly_sched_windows"           # "22:00-06:00,12:00-13:30"; "" = any hour
SCHED_HOURS_KEY = "jelly_sched_daily_hours"     # per rig, per local day; 0 = unlimited

THROTTLE_MAX = 90                               # miner's own clamp — keep in step
BATCH_MIN, BATCH_MAX = 1 << 16, 1 << 26
DEFAULT_THROTTLE, DEFAULT_BATCH = 50, 1 << 22
CREDIT_CAP_SEC = 120        # most seconds one getwork may add to the budget clock

_BUDGET_DDL = """
CREATE TABLE IF NOT EXISTS jelly_rig_minutes (
    rig TEXT NOT NULL, day TEXT NOT NULL,
    seconds REAL NOT NULL DEFAULT 0, last_seen REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (rig, day))"""


def _sflag(key: str, dflt: str) -> bool:
    return str(get_setting(key, dflt)).strip().lower() not in ("0", "off", "false", "no", "")


def _snum(key: str, dflt: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(get_setting(key, dflt))))
    except (TypeError, ValueError):
        return dflt


def _sjson(key: str, dflt):
    try:
        v = json.loads(str(get_setting(key, "") or ""))
        return v if isinstance(v, type(dflt)) else dflt
    except (TypeError, ValueError):
        return dflt


def _put(conn, key, val):
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(val)))


def _save(key, val):
    conn = get_conn()
    try:
        _put(conn, key, val)
        conn.commit()
    finally:
        conn.close()


def tz_name() -> str:
    """Which clock the schedule speaks. Stated in the API + UI so 22:00 is never
    ambiguous between the box, the browser and a rig in another timezone."""
    try:
        import datetime
        return datetime.datetime.now().astimezone().tzname() or time.tzname[0]
    except Exception:
        return time.tzname[0] if time.tzname else "local"


def _local(now: float):
    return time.localtime(now)


def _today(now: float) -> str:
    return time.strftime("%Y-%m-%d", _local(now))


def parse_windows(raw: str):
    """"22:00-06:00, 12:00-13:30" → [(1320, 360), (720, 810)] in minutes-of-day.

    end < start means the window WRAPS past midnight — the common case for an
    overnight rig, so it is supported rather than rejected."""
    out = []
    for chunk in str(raw or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            a, b = chunk.split("-", 1)

            def mins(s):
                s = s.strip()
                h, m = (s.split(":", 1) + ["0"])[:2] if ":" in s else (s, "0")
                h, m = int(h), int(m)
                if not (0 <= h <= 24 and 0 <= m < 60):
                    raise ValueError(f"bad time {s!r}")
                return (h * 60 + m) % 1440
            out.append((mins(a), mins(b)))
        except (ValueError, IndexError):
            raise ValueError(f"bad window {chunk!r} — use HH:MM-HH:MM (e.g. 22:00-06:00)")
    return out


def _in_windows(wins, now: float) -> bool:
    """No windows configured ⇒ every hour is allowed (the schedule then only
    constrains via the daily budget). Otherwise: inside any one of them."""
    if not wins:
        return True
    lt = _local(now)
    cur = lt.tm_hour * 60 + lt.tm_min
    for a, b in wins:
        if a == b:                                  # zero-width ⇒ treat as all day
            return True
        if a < b:
            if a <= cur < b:
                return True
        elif cur >= a or cur < b:                   # wraps midnight
            return True
    return False


def _secs_to_open(wins, now: float) -> int:
    """Seconds until the next window opens (capped at an hour so a held rig still
    checks back in occasionally rather than sleeping until 22:00 and missing a
    settings change)."""
    if not wins:
        return 0
    lt = _local(now)
    cur = lt.tm_hour * 60 + lt.tm_min
    best = min(((a - cur) % 1440) for a, _ in wins)
    return int(min(3600, max(60, best * 60)))


def _ensure_budget(conn):
    conn.execute(_BUDGET_DDL)


def credit_mining(rig: str, now: float):
    """Bank the time a rig has actually been mining, so the daily budget is REAL
    and not a theoretical wall-clock window.

    Credited on WORK ISSUE only — a held rig keeps polling, and counting those
    polls would burn the budget while the card sat idle. The per-call cap means a
    rig that was off for six hours credits one poll interval when it returns, not
    six hours."""
    rig = (rig or "").strip()[:40]
    if not rig:
        return
    conn = get_conn()
    try:
        _ensure_budget(conn)
        day = _today(now)
        row = conn.execute("SELECT seconds,last_seen FROM jelly_rig_minutes WHERE rig=? AND day=?",
                           (rig, day)).fetchone()
        if row is None:
            conn.execute("INSERT INTO jelly_rig_minutes (rig,day,seconds,last_seen) VALUES (?,?,0,?)",
                         (rig, day, now))
        else:
            delta = 0.0 if not row["last_seen"] else max(0.0, min(CREDIT_CAP_SEC, now - row["last_seen"]))
            conn.execute("UPDATE jelly_rig_minutes SET seconds=seconds+?, last_seen=? WHERE rig=? AND day=?",
                         (delta, now, rig, day))
        conn.commit()
    except Exception as e:
        logger.debug(f"[jelly] budget accounting failed for {rig}: {e}")
    finally:
        conn.close()


def hours_today(rig: str, now: float = 0.0) -> float:
    now = now or time.time()
    conn = get_conn()
    try:
        _ensure_budget(conn)
        row = conn.execute("SELECT seconds FROM jelly_rig_minutes WHERE rig=? AND day=?",
                           (rig, _today(now))).fetchone()
        return round((row["seconds"] if row else 0.0) / 3600.0, 3)
    except Exception:
        return 0.0
    finally:
        conn.close()


def _secs_to_midnight(now: float) -> int:
    lt = _local(now)
    return int(min(3600, max(60, ((23 - lt.tm_hour) * 60 + (60 - lt.tm_min)) * 60)))


def schedule_hold(miner: str = "", now: float = 0.0) -> dict:
    """The OWNER's hours. Same 503 hold shape as the queue-yield, so an old miner
    obeys the schedule without knowing a schedule exists."""
    now = now or time.time()
    if not _sflag(SCHED_ON_KEY, "0"):
        return {}
    try:
        wins = parse_windows(get_setting(SCHED_WIN_KEY, "") or "")
    except ValueError:
        wins = []                                   # a malformed setting must never wedge mining
    if not _in_windows(wins, now):
        retry = _secs_to_open(wins, now)
        return {"pause": True, "retry_after": retry, "busy": False, "sched": True,
                "reason": f"outside the mining hours you set ({get_setting(SCHED_WIN_KEY, '')}, {tz_name()})",
                "resume_in": retry, "settle_sec": 0, "held_for": 0}
    budget = _snum(SCHED_HOURS_KEY, 0, 0, 24)
    if budget > 0 and miner:
        used = hours_today(miner, now)
        if used >= budget:
            retry = _secs_to_midnight(now)
            return {"pause": True, "retry_after": retry, "busy": False, "sched": True,
                    "reason": (f"{miner} has used its {budget:g}h for today "
                               f"({used:.2f}h mined, {tz_name()}) — resumes at midnight"),
                    "resume_in": retry, "settle_sec": 0, "held_for": 0,
                    "hours_today": used, "daily_hours": budget}
    return {}


def mining_hold(now: float = 0.0, miner: str = "") -> dict:
    """Should this rig stand down right now? The hold payload, or {}.

    ORDER IS THE POLICY. In normal running the AI queue is checked first and wins
    outright: store work always outranks mining, whatever the schedule says. Only
    if the queue is happy do the owner's hours, the daily budget and the Company's
    plan get a say.

    The one documented exception is CHAIN DEFENCE. While defence is engaged the
    chain itself is at risk, so mining stops standing down — for the queue, for
    the owner's hours, and for any agent plan alike. That preemption is graceful
    (defense_yield_override lets an in-flight generation finish first) and never
    cancels anything; it ships ON and has its own toggle.

    `miner` is optional so older callers (the UI's /miner-yield poll) still work;
    without it the per-rig budget simply isn't evaluated."""
    now = now or time.time()
    defending = defense_yield_override(now)
    q = _queue_hold(now)                            # always evaluated: keeps the
    if q and not defending:                         # hysteresis state machine live
        return q
    if defending:
        return {}                                   # defending the chain: mine, full stop
    s = schedule_hold(miner, now)
    if s:
        return s
    return agent_hold(miner, now)


# ── per-rig intensity, delivered live inside getwork ─────────────────────────
def rig_policy(rig: str, now: float = 0.0) -> dict:
    """What intensity should THIS rig run at? Owner base → agent (clamped) →
    defence ramp (bounded). Every layer may only be applied, never bypassed."""
    now = now or time.time()
    pol = _sjson(POLICY_KEY, {})
    base = {"throttle": DEFAULT_THROTTLE, "batch": DEFAULT_BATCH, "cost": "ai"}
    for k in ("__default__", rig):
        v = pol.get(k)
        if isinstance(v, dict):
            base.update({kk: vv for kk, vv in v.items() if kk in base})
    try:
        throttle = max(0, min(THROTTLE_MAX, int(float(base["throttle"]))))
    except (TypeError, ValueError):
        throttle = DEFAULT_THROTTLE
    try:
        batch = max(BATCH_MIN, min(BATCH_MAX, int(float(base["batch"]))))
    except (TypeError, ValueError):
        batch = DEFAULT_BATCH
    cost = "free" if str(base.get("cost", "ai")).lower() == "free" else "ai"
    source = "owner"

    plan = active_agent_plan(now)                   # {} unless the toggle is ON
    if plan and plan.get("rig") in (rig, "*") and plan.get("throttle") is not None:
        throttle = max(agent_min_throttle(), min(THROTTLE_MAX, int(plan["throttle"])))
        source = "agent"

    ramp = defense_ramp(rig, cost, now)
    if ramp is not None and ramp < throttle:
        throttle, source = ramp, "defense"
    return {"throttle": throttle, "batch": batch, "cost": cost, "source": source}


# ═══ agent-decided mining — bounded by the owner, gated by its own toggle ════
# Same shape as world_leader.py: the Company may act, but only inside a hard
# envelope the owner set, everything it does is recorded and visible, and the
# whole feature is behind a toggle that ships OFF.
#
# What a plan may do:      pick a throttle, or stand a rig down for a while.
# What a plan may NEVER do: mine outside the owner's hours, exceed the daily
#                           budget, out-run agent_min_throttle, or touch the
#                           queue-yield. Those are all enforced *elsewhere*
#                           (mining_hold / rig_policy clamps), so a bad plan is
#                           structurally incapable of widening the envelope.
AGENT_ON_KEY = "jelly_agent_control"            # default OFF
AGENT_MIN_THROTTLE_KEY = "jelly_agent_min_throttle"     # the hardest agents may push
AGENT_MAX_PAUSE_KEY = "jelly_agent_max_pause_min"       # longest stand-down they may call
AGENT_MAX_MINUTES_KEY = "jelly_agent_max_minutes"       # longest a plan may last
AGENT_PLAN_KEY = "jelly_agent_plan"             # JSON — the one plan in force

AGENT_MIN_THROTTLE_DEFAULT, AGENT_MAX_PAUSE_DEFAULT, AGENT_MAX_MINUTES_DEFAULT = 25, 120, 240

_PLANS_DDL = """
CREATE TABLE IF NOT EXISTS jelly_agent_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, agent TEXT, rig TEXT,
    throttle INTEGER, pause_min INTEGER, minutes INTEGER,
    reason TEXT, clamped TEXT, accepted INTEGER DEFAULT 1)"""


def agent_enabled() -> bool:
    return _sflag(AGENT_ON_KEY, "0")


def agent_min_throttle() -> int:
    return int(_snum(AGENT_MIN_THROTTLE_KEY, AGENT_MIN_THROTTLE_DEFAULT, 0, THROTTLE_MAX))


def active_agent_plan(now: float = 0.0) -> dict:
    """The plan in force, or {} — including whenever the toggle is off, so
    flipping the switch instantly de-fangs any plan already on the books."""
    if not agent_enabled():
        return {}
    now = now or time.time()
    plan = _sjson(AGENT_PLAN_KEY, {})
    if not plan or float(plan.get("expires") or 0) <= now:
        return {}
    return plan


def agent_hold(miner: str = "", now: float = 0.0) -> dict:
    """An agent-called stand-down. Narrowing only: it can pause mining, never
    start it, so it cannot reach outside the owner's hours."""
    now = now or time.time()
    plan = active_agent_plan(now)
    if not plan or plan.get("rig") not in (miner, "*"):
        return {}
    until = float(plan.get("pause_until") or 0)
    if until <= now:
        return {}
    left = int(until - now)
    retry = int(min(300, max(5, left)))
    return {"pause": True, "retry_after": retry, "busy": False, "agent": True,
            "reason": (f"{plan.get('agent') or 'the Company'} stood this rig down: "
                       f"{plan.get('reason') or 'no reason given'}"),
            "resume_in": left, "settle_sec": 0, "held_for": 0}


def _log_plan(row: dict):
    conn = get_conn()
    try:
        conn.execute(_PLANS_DDL)
        conn.execute("INSERT INTO jelly_agent_plans (at,agent,rig,throttle,pause_min,minutes,"
                     "reason,clamped,accepted) VALUES (?,?,?,?,?,?,?,?,?)",
                     (row["at"], row["agent"], row["rig"], row["throttle"], row["pause_min"],
                      row["minutes"], row["reason"], json.dumps(row.get("clamped") or {}),
                      1 if row.get("accepted", True) else 0))
        conn.commit()
    finally:
        conn.close()


def propose_agent_plan(agent: str, rig: str, throttle=None, pause_min: int = 0,
                       minutes: int = 60, reason: str = "", now: float = 0.0) -> dict:
    """The Company's one lever. Refused outright while the toggle is off; every
    number silently CLAMPED into the owner's envelope otherwise, with the clamps
    reported back so nothing is hidden."""
    now = now or time.time()
    if not agent_enabled():
        raise HTTPException(403, "agent-decided mining is off — turn it on in "
                                 "Crypto → JellyCoin → ⛏️ GPU rigs first")
    rig = (str(rig or "*").strip() or "*")[:40]
    clamped = {}
    max_min = int(_snum(AGENT_MAX_MINUTES_KEY, AGENT_MAX_MINUTES_DEFAULT, 1, 1440))
    max_pause = int(_snum(AGENT_MAX_PAUSE_KEY, AGENT_MAX_PAUSE_DEFAULT, 0, 1440))
    floor = agent_min_throttle()

    try:
        minutes = int(float(minutes))
    except (TypeError, ValueError):
        minutes = 60
    if not 1 <= minutes <= max_min:
        clamped["minutes"] = minutes
        minutes = max(1, min(max_min, minutes))
    try:
        pause_min = int(float(pause_min or 0))
    except (TypeError, ValueError):
        pause_min = 0
    if not 0 <= pause_min <= max_pause:
        clamped["pause_min"] = pause_min
        pause_min = max(0, min(max_pause, pause_min))
    if throttle is not None:
        try:
            t = int(float(throttle))
        except (TypeError, ValueError):
            t = floor
        if not floor <= t <= THROTTLE_MAX:
            clamped["throttle"] = t
            t = max(floor, min(THROTTLE_MAX, t))
        throttle = t

    plan = {"agent": (str(agent or "the Company").strip() or "the Company")[:60],
            "rig": rig, "throttle": throttle, "reason": str(reason or "")[:300],
            "at": now, "expires": now + minutes * 60,
            "pause_until": now + pause_min * 60 if pause_min else 0}
    _save(AGENT_PLAN_KEY, json.dumps(plan))
    _log_plan({**plan, "pause_min": pause_min, "minutes": minutes, "clamped": clamped})
    try:                                            # visible, like every leader action
        from world_defs import log_town
        log_town(f"⛏️ {plan['agent']} set mining on {rig}: "
                 + (f"throttle {throttle}%" if throttle is not None else "no intensity change")
                 + (f", stand down {pause_min}m" if pause_min else "")
                 + f" for {minutes}m — {plan['reason'] or 'routine'}")
    except Exception:
        pass
    return {"ok": True, "plan": plan, "minutes": minutes, "pause_min": pause_min,
            "clamped": clamped, "envelope": agent_envelope()}


def agent_envelope() -> dict:
    """What the owner allows the Company to do — echoed everywhere a plan is, so
    the bounds are never a mystery."""
    return {"enabled": agent_enabled(), "min_throttle": agent_min_throttle(),
            "max_pause_min": int(_snum(AGENT_MAX_PAUSE_KEY, AGENT_MAX_PAUSE_DEFAULT, 0, 1440)),
            "max_minutes": int(_snum(AGENT_MAX_MINUTES_KEY, AGENT_MAX_MINUTES_DEFAULT, 1, 1440))}


# ═══ 51%-attack defence: measure our share, then scale our own hashpower ═════
# Today every block is ours. If outsiders ever join and take the majority they
# could reorg the chain, so we watch for it and answer with hashpower.
#
# HOW SHARE IS MEASURED — and what that is worth:
#   Signal: the fraction of the last N blocks whose `miner` is one of OUR rigs,
#   which is the only share signal the chain can VERIFY (each of those blocks is
#   a real solved proof-of-work). Network hashrate is estimated the standard way,
#   from the work the chain actually absorbed: Σ(2²⁵⁶/target) over the window,
#   divided by the wall-clock the window spanned.
#   We deliberately do NOT trust the `hashrate` a miner self-reports in getwork —
#   an attacker sets that field to whatever they like. It is display only.
#   Limitation: block attribution is a BINOMIAL sample. At 60 blocks a true 50%
#   attacker reads anywhere from ~37% to ~63% at 95% confidence, so the ladder
#   needs a margin (hence warn 70 / act 60) and `blocks` is reported as the
#   confidence figure. An attacker mining privately (a withheld-chain reorg)
#   contributes NO blocks to our view and is invisible to this signal until they
#   publish — that is the shape this cannot see coming.
DEF_ON_KEY = "jelly_defense_enabled"            # ships ON — the chain protects itself
DEF_PREEMPT_KEY = "jelly_defense_preempt_ai"    # ships ON — defence outranks AI work
DEF_WARN_KEY = "jelly_defense_warn_pct"         # tell me (70)
DEF_ACT_KEY = "jelly_defense_act_pct"           # engage (60)
DEF_CLEAR_KEY = "jelly_defense_clear_pct"       # disengage above this (70)
DEF_SETTLE_KEY = "jelly_defense_settle_min"     # …once recovered THIS long (30 min)
DEF_WINDOW_KEY = "jelly_defense_window_blocks"  # sample size (60)
DEF_MY_RIGS_KEY = "jelly_defense_my_rigs"       # "" = auto-detect non-peer rigs
DEF_SAMPLE_MIN_KEY = "jelly_defense_sample_min"
DEF_MODE_KEY = "jelly_defense_mode"             # JSON — engaged state, survives restarts
DEF_WARN_DEFAULT, DEF_ACT_DEFAULT, DEF_CLEAR_DEFAULT = 70, 60, 70
DEF_WINDOW_DEFAULT, DEF_SETTLE_DEFAULT, DEF_SAMPLE_MIN_DEFAULT = 60, 30, 15
MIN_BLOCKS_FOR_CONFIDENCE = 10

_DEF_LOG_DDL = """
CREATE TABLE IF NOT EXISTS jelly_defense_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, share_pct REAL,
    net_hashrate REAL, my_hashrate REAL, blocks INTEGER, level TEXT, note TEXT)"""

_def_cache = {"at": 0.0, "state": None}
DEF_CACHE_SEC = 30              # getwork must not rescan the block table every poll

# Graceful-preemption gate. While defence is engaged mining stops yielding to the
# AI queue — but NOT mid-job: we keep yielding until the queue next goes idle, so
# a render in flight finishes cleanly. Nothing is ever cancelled or killed.
_def_gate = {"armed": False, "engaged_at": 0.0, "ai_seconds": 0.0, "since": 0.0}


def defense_enabled() -> bool:
    return _sflag(DEF_ON_KEY, "1")


def _my_rigs(conn) -> tuple:
    """Which rigs are OURS. Explicit list wins; otherwise fall back to every rig
    not mapped to a peer wallet, and SAY it was a guess — an unknown rig mining
    on our node would be counted as ours by that fallback, which is exactly the
    case the owner should pin down by hand."""
    raw = str(get_setting(DEF_MY_RIGS_KEY, "") or "").strip()
    if raw:
        return tuple(sorted({r.strip()[:40] for r in raw.replace(";", ",").split(",") if r.strip()})), False
    try:
        rows = conn.execute("SELECT name,owner FROM jelly_miners").fetchall()
        return tuple(sorted(r["name"] for r in rows
                            if not (r["owner"] or "").startswith("peer:"))), True
    except Exception:
        return (), True


def _def_mode() -> dict:
    m = _sjson(DEF_MODE_KEY, {})
    return m if isinstance(m, dict) else {}


def defense_state(now: float = 0.0, fresh: bool = False) -> dict:
    """Our measured share of network hashpower, the alert level, and whether
    defence is currently ENGAGED (with hysteresis, so noise can't flap the box)."""
    now = now or time.time()
    if not fresh and _def_cache["state"] and now - _def_cache["at"] < DEF_CACHE_SEC:
        return _def_cache["state"]
    warn = _snum(DEF_WARN_KEY, DEF_WARN_DEFAULT, 0, 100)
    act = min(warn, _snum(DEF_ACT_KEY, DEF_ACT_DEFAULT, 0, 100))
    clear = max(act, _snum(DEF_CLEAR_KEY, DEF_CLEAR_DEFAULT, 0, 100))
    window = int(_snum(DEF_WINDOW_KEY, DEF_WINDOW_DEFAULT, 5, 500))
    mode = _def_mode()
    st = {"enabled": defense_enabled(), "preempt_ai": _sflag(DEF_PREEMPT_KEY, "1"),
          "warn_pct": warn, "act_pct": act, "clear_pct": clear,
          "settle_min": _snum(DEF_SETTLE_KEY, DEF_SETTLE_DEFAULT, 0, 1440),
          "window_blocks": window, "level": "unknown", "share_pct": None,
          "net_hashrate": 0.0, "my_hashrate": 0.0, "blocks": 0, "confident": False,
          "my_rigs": [], "auto_rigs": True, "per_rig": [],
          "engaged": bool(mode.get("engaged")), "engaged_since": mode.get("since") or 0,
          "recovering_since": mode.get("recovering") or 0, "ramped": [],
          "suppressed_until": mode.get("suppress_until") or 0,
          "ai_seconds": round(_def_gate["ai_seconds"], 1), "reason": ""}
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT height,time,target,miner FROM jelly_blocks WHERE height>0 "
                            "ORDER BY height DESC LIMIT ?", (window,)).fetchall()
        mine, auto = _my_rigs(conn)
    except Exception as e:
        st["reason"] = f"could not read the chain: {e}"
        _def_cache.update(at=now, state=st)
        return st
    finally:
        conn.close()
    st["my_rigs"], st["auto_rigs"] = list(mine), auto
    if len(rows) < 2:
        st["reason"] = "not enough blocks mined yet to measure a share"
        _def_cache.update(at=now, state=st)
        return st
    span = max(1, int(rows[0]["time"]) - int(rows[-1]["time"]))
    work, counts = 0, {}
    for r in rows:
        try:
            tgt = int(r["target"], 16)
        except (TypeError, ValueError):
            continue
        work += (1 << 256) // max(1, tgt + 1)
        counts[r["miner"] or "?"] = counts.get(r["miner"] or "?", 0) + 1
    total = sum(counts.values()) or 1
    mine_n = sum(n for m, n in counts.items() if m in mine)
    st["blocks"] = total
    st["net_hashrate"] = work / span
    st["share_pct"] = round(100.0 * mine_n / total, 1)
    st["my_hashrate"] = st["net_hashrate"] * mine_n / total
    st["confident"] = total >= MIN_BLOCKS_FOR_CONFIDENCE
    st["per_rig"] = sorted(
        ({"rig": m, "blocks": n, "pct": round(100.0 * n / total, 1), "mine": m in mine}
         for m, n in counts.items()), key=lambda d: -d["blocks"])
    if not st["confident"]:
        st["level"] = "unknown"
        st["reason"] = (f"only {total} block(s) in the window — too small a sample to act on "
                        f"(need {MIN_BLOCKS_FOR_CONFIDENCE})")
    elif st["share_pct"] < act:
        st["level"] = "act"
        st["reason"] = f"our share is {st['share_pct']}% — below the {act:g}% action line"
    elif st["share_pct"] < warn:
        st["level"] = "warn"
        st["reason"] = f"our share is {st['share_pct']}% — below the {warn:g}% warning line"
    else:
        st["level"] = "ok"
        st["reason"] = f"our share is {st['share_pct']}%"
    _defense_transition(st, now)
    _def_cache.update(at=now, state=st)
    _defense_sample(st, now)
    return st


def _defense_transition(st: dict, now: float):
    """The engage/disengage state machine.

    ENGAGE is automatic and immediate — an attack will not wait for anyone to wake
    up and click a button, so nothing here asks permission.
    DISENGAGE is deliberately slow: the share must sit at or above `clear_pct` for
    a whole `settle_min` before we stand down. Block attribution is a binomial
    sample and jitters by tens of percent at these window sizes; without that
    hysteresis one lucky round for an attacker would flap every rig on the box in
    and out of full blast."""
    if not st["enabled"] or not st["confident"]:
        return
    mode = _def_mode()
    engaged = bool(mode.get("engaged"))
    if not engaged:
        # A manual stand-down is the owner overriding an automatic system, so it
        # is honoured — but it EXPIRES rather than disarming the chain for good.
        # Re-engaging the moment he clicks "stand down" would make the button a
        # lie; never re-engaging would turn one click into a permanent hole.
        if now < float(mode.get("suppress_until") or 0):
            st["suppressed_until"] = float(mode["suppress_until"])
            st["reason"] += f" (defence suppressed by hand until " \
                            f"{time.strftime('%H:%M', _local(st['suppressed_until']))})"
            return
        if st["level"] == "act":
            _defense_engage(st, now)
        return
    if st["share_pct"] >= st["clear_pct"]:
        rec = float(mode.get("recovering") or 0)
        if not rec:
            mode["recovering"] = now
            _save(DEF_MODE_KEY, json.dumps(mode))
            st["recovering_since"] = now
        elif (now - rec) >= st["settle_min"] * 60:
            _defense_disengage(st, now)
    elif mode.get("recovering"):
        mode["recovering"] = 0                      # dipped again — restart the clock
        _save(DEF_MODE_KEY, json.dumps(mode))
        st["recovering_since"] = 0


def _defense_engage(st: dict, now: float):
    ramped = [r["rig"] for r in st["per_rig"] if r["mine"]] or list(st["my_rigs"])
    _save(DEF_MODE_KEY, json.dumps({"engaged": True, "since": now, "recovering": 0,
                                    "share": st["share_pct"], "rigs": ramped}))
    _def_gate.update(armed=False, engaged_at=now, ai_seconds=0.0, since=now)
    st.update(engaged=True, engaged_since=now, recovering_since=0, ramped=ramped)
    note = (f"DEFENCE ENGAGED — share {st['share_pct']}% (below {st['act_pct']:g}%). "
            f"Ramping every rig to full: {', '.join(ramped) or 'none online'}."
            + (" AI work is preempted for the duration." if st["preempt_ai"] else ""))
    logger.warning(f"[jelly] {note}")
    _defense_log(now, st, "engage", note)
    _defense_shout(f"🛡️ JellyCoin defence ENGAGED: {note}")


def _defense_disengage(st: dict, now: float):
    mode = _def_mode()
    held = now - float(mode.get("since") or now)
    _save(DEF_MODE_KEY, json.dumps({"engaged": False, "since": 0, "recovering": 0}))
    st.update(engaged=False, engaged_since=0, recovering_since=0)
    note = (f"DEFENCE STOOD DOWN — share back to {st['share_pct']}% for "
            f"{st['settle_min']:g} min. Defended for {held / 3600:.1f}h; "
            f"AI work gave up {_def_gate['ai_seconds'] / 60:.0f} min of GPU.")
    logger.warning(f"[jelly] {note}")
    _defense_log(now, st, "disengage", note)
    _defense_shout(f"🛡️ JellyCoin defence stood down: {note}")
    _def_gate.update(armed=False, engaged_at=0.0, ai_seconds=0.0, since=0.0)


def _defense_shout(text: str):
    """Unmissable: the god's message board AND the town feed."""
    try:
        import world_ops as wo
        wo.note(text, kind="need")
    except Exception:
        pass
    try:
        from world_defs import log_town
        log_town(text)
    except Exception:
        pass


def _defense_log(now: float, st: dict, level: str, note: str):
    conn = get_conn()
    try:
        conn.execute(_DEF_LOG_DDL)
        conn.execute("INSERT INTO jelly_defense_log (at,share_pct,net_hashrate,my_hashrate,"
                     "blocks,level,note) VALUES (?,?,?,?,?,?,?)",
                     (now, st["share_pct"], st["net_hashrate"], st["my_hashrate"],
                      st["blocks"], level, note))
        conn.commit()
    except Exception as e:
        logger.debug(f"[jelly] defence log failed: {e}")
    finally:
        conn.close()


def _defense_sample(st: dict, now: float):
    """Persist a routine datapoint so slow erosion over DAYS is visible instead of
    silent — the failure mode that let a broken tileset sit unnoticed. Also feeds
    the share/hashrate chart. Engage/disengage are logged separately and always."""
    if not st["confident"]:
        return
    every = _snum(DEF_SAMPLE_MIN_KEY, DEF_SAMPLE_MIN_DEFAULT, 1, 1440) * 60
    conn = get_conn()
    try:
        conn.execute(_DEF_LOG_DDL)
        last = conn.execute("SELECT at,level FROM jelly_defense_log ORDER BY id DESC LIMIT 1").fetchone()
        if last and (now - float(last["at"])) < every and last["level"] == st["level"]:
            return
        conn.execute("INSERT INTO jelly_defense_log (at,share_pct,net_hashrate,my_hashrate,"
                     "blocks,level,note) VALUES (?,?,?,?,?,?,?)",
                     (now, st["share_pct"], st["net_hashrate"], st["my_hashrate"],
                      st["blocks"], st["level"], st["reason"]))
        conn.commit()
        if st["level"] == "warn" and (not last or last["level"] != "warn"):
            logger.warning(f"[jelly] hashpower warning: {st['reason']}")
            _defense_shout(f"🛡️ JellyCoin hashpower: {st['reason']}. Spare rigs are ramping; "
                           f"full defence engages below {st['act_pct']:g}%.")
    except Exception as e:
        logger.debug(f"[jelly] defence sample failed: {e}")
    finally:
        conn.close()


def defense_ramp(rig: str, cost: str, now: float = 0.0):
    """Cheapest capacity first. Returns a throttle CEILING for this rig, or None.

      warn     → ramp the FREE rigs only. Idle silicon costs nothing but watts, so
                 spare capacity answers first and the AI box is left alone.
      ENGAGED  → ramp EVERY rig to full, automatically. At this point the chain is
                 the thing at risk, and it does not wait for approval.

    Rigs are whatever the DB knows — a third card or a fourth needs an install,
    not a code change."""
    if not defense_enabled():
        return None
    st = defense_state(now)
    if st["engaged"]:
        return 0
    if st["level"] == "warn" and cost == "free":
        return 0
    return None


def defense_preempting(now: float = 0.0) -> bool:
    """Is chain defence currently allowed to outrank the AI queue?

    Requires defence on, the preempt toggle on (both ship ON), and defence
    actually ENGAGED. This is the one and only case where mining beats AI work."""
    if not (defense_enabled() and _sflag(DEF_PREEMPT_KEY, "1")):
        return False
    return bool(defense_state(now)["engaged"])


def defense_yield_override(now: float) -> bool:
    """Graceful preemption: should mining ignore a busy AI queue right now?

    Not the instant defence engages — a generation already on the GPU is allowed
    to FINISH. We keep yielding until the queue next reports idle, and only then
    arm the override. Nothing is ever cancelled, killed or rolled back; the worst
    an in-flight job sees is the GPU getting busier after it completes.

    Once armed, the time mining spends holding the card while the queue wants it
    is accumulated as the honest cost of defending (reported as `ai_seconds`)."""
    if not defense_preempting(now):
        if _def_gate["armed"]:
            _def_gate.update(armed=False)
        return False
    if not _def_gate["armed"]:
        if _queue_busy():
            return False                            # let the in-flight job finish
        _def_gate.update(armed=True, since=now)
        logger.warning("[jelly] defence armed — AI queue no longer preempts mining "
                       "(in-flight work was allowed to finish)")
    if _queue_busy():                               # measure what defending costs
        last = _def_gate.get("since") or now
        _def_gate["ai_seconds"] += max(0.0, min(CREDIT_CAP_SEC, now - last))
    _def_gate["since"] = now
    return True

# ── chain / ledger ───────────────────────────────────────────────────────────
@router.get("/api/jelly/status")
def jelly_status():
    return jellycoin.status()


@router.get("/api/jelly/supply")
def jelly_supply():
    """Emission audit: circulating vs the hard cap, headroom, the halving schedule,
    the projected date the cap is reached — and a reconciliation of the block-derived
    supply against the sum of every wallet balance."""
    return jellycoin.supply_report()


@router.get("/api/jelly/blocks")
def jelly_blocks(limit: int = 25):
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT height,hash,time,miner,reward,boost,nonce FROM jelly_blocks "
                            "ORDER BY height DESC LIMIT ?", (max(1, min(200, limit)),)).fetchall()
        return {"blocks": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/api/jelly/wallets")
def jelly_wallets():
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT name,address,balance,kind,created_at FROM jelly_wallets "
                            "ORDER BY balance DESC, name").fetchall()
        txs = conn.execute("SELECT * FROM jelly_txs ORDER BY id DESC LIMIT 40").fetchall()
        return {"unit": jellycoin.UNIT,
                "wallets": [dict(r) for r in rows],
                "recent_txs": [dict(r) for r in txs]}
    finally:
        conn.close()


@router.post("/api/jelly/transfer")
def jelly_transfer(payload: dict = Body(...)):
    try:
        return jellycoin.transfer(
            str(payload.get("from", "")).strip(), str(payload.get("to", "")).strip(),
            int(float(payload.get("amount_jly", 0)) * jellycoin.UNIT),
            memo=str(payload.get("memo", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/jelly/tip")
def jelly_tip(payload: dict = Body(...)):
    """The AI friend's tip jar → send JLY from the 'assistant' wallet (MCP-callable)."""
    try:
        return jellycoin.transfer(
            jellycoin.ASSISTANT, str(payload.get("to", "")).strip(),
            int(float(payload.get("amount_jly", 0)) * jellycoin.UNIT),
            memo=str(payload.get("memo", "tip from your AI friend")), kind="tip")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/jelly/stats")
def jelly_stats(points: int = 160):
    """Chart series derived from the block table: difficulty, block interval,
    cumulative supply (each downsampled to ≤`points`), plus blocks per rig."""
    points = max(10, min(500, points))
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT height,time,target,reward,boost,miner FROM jelly_blocks "
                            "ORDER BY height").fetchall()
        per_rig = [dict(r) for r in conn.execute(
            "SELECT miner, COUNT(*) blocks FROM jelly_blocks WHERE height>0 "
            "GROUP BY miner ORDER BY blocks DESC LIMIT 8")]
    finally:
        conn.close()
    series = []
    supply = 0
    for i, r in enumerate(rows):
        supply += int(r["reward"]) + int(r["boost"])
        series.append({
            "h": int(r["height"]), "t": int(r["time"]),
            "difficulty": round(jellycoin.difficulty(int(r["target"], 16)), 2),
            "interval": (int(r["time"]) - int(rows[i - 1]["time"])) if i else None,
            "supply": round(supply / jellycoin.UNIT, 2),
        })
    if len(series) > points:                      # keep first/last, stride the middle
        step = len(series) / points
        series = [series[int(i * step)] for i in range(points - 1)] + [series[-1]]
    return {"series": series, "per_rig": per_rig,
            "target_block_sec": jellycoin.TARGET_BLOCK_SEC}


_DOCS = {"whitepaper": "WHITEPAPER.md", "security": "SECURITY.md"}
_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "jellycoin"


@router.get("/api/jelly/doc/{name}")
def jelly_doc(name: str):
    """Serve the JellyCoin white paper / security-protocol docs (markdown, read-only)."""
    fn = _DOCS.get(name)
    if not fn or not (_DOCS_DIR / fn).is_file():
        raise HTTPException(404, f"doc must be one of {sorted(_DOCS)}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse((_DOCS_DIR / fn).read_text(encoding="utf-8"),
                             media_type="text/markdown")


# ── mining (LAN-reachable, token-guarded; GPU rigs only — server never mines) ─
@router.get("/api/jelly/mining/work")
def jelly_work(request: Request, miner: str, gpu: str = "", hashrate: float = 0.0):
    """Issue a PoW job — unless the AI queue owns the GPU, in which case hold.

    The hold is an HTTP 503 (+ Retry-After) whose body is {"pause": true,
    "retry_after": n, ...} and carries NO work_id/header76/target. That shape is
    deliberate: an un-updated miner's `raise_for_status()` turns it into its
    normal "getwork failed; retrying in 10s" path, so an OLD binary idles safely
    instead of parsing a half-response or spinning. An updated miner reads the
    body and sleeps for retry_after with a modest backoff.

    A 200 additionally carries a "policy" object ({throttle, batch, ...}) telling
    the rig how HARD to mine right now. It rides alongside the work rather than
    in a second call, so intensity changes land on the next batch with no restart
    and no reinstall. Purely additive: a miner built before it existed ignores the
    unknown key and keeps its install-time --throttle/--batch, exactly as today.

    Submission is NEVER gated — see /api/jelly/mining/submit."""
    _check_miner(request)
    now = time.time()
    hold = mining_hold(now, miner)
    if hold:
        _touch_rig(miner, gpu, hashrate)
        return JSONResponse(status_code=503, content=hold,
                            headers={"Retry-After": str(hold["retry_after"])})
    try:
        work = jellycoin.get_work(miner, gpu=gpu, hashrate=hashrate)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # Credit AFTER the work is safely issued, so a failed getwork never burns
    # budget, and report the remaining allowance so the rig can show it.
    credit_mining(miner, now)
    pol = rig_policy(miner, now)
    budget = _snum(SCHED_HOURS_KEY, 0, 0, 24)
    if budget > 0:
        pol["hours_today"] = hours_today(miner, now)
        pol["daily_hours"] = budget
    work["policy"] = pol
    return work


@router.post("/api/jelly/mining/submit")
def jelly_submit(request: Request, payload: dict = Body(...)):
    """Always open, even while mining is held. A rig that found a nonce just
    before the hold must still be able to bank it — and because a hold returns
    BEFORE jellycoin.get_work(), the WORK_TTL sweep never runs during a pause, so
    in-flight work cannot be expired out from under a valid submit."""
    _check_miner(request)
    res = jellycoin.submit_work(str(payload.get("work_id", "")),
                                int(payload.get("nonce", 0)),
                                str(payload.get("miner", "")))
    if res.get("ok") and res.get("wallet"):                 # winner-take-all block
        logger.info(f"[jelly] block {res['height']} mined by {res['wallet']} (+{res['reward']} JLY)")
    elif res.get("block"):                                  # pool block (reward split)
        logger.info(f"[jelly] pool block {res['height']} split (+{res.get('reward', 0)} JLY)")
    return res


@router.get("/api/jelly/mining/miner.py")
def jelly_miner_download(request: Request):
    _check_miner(request)
    if not _MINER_FILE.is_file():
        raise HTTPException(404, "miner script missing from install")
    return FileResponse(str(_MINER_FILE), media_type="text/x-python", filename="jellyminer.py")


@router.get("/api/jelly/mining/install-miner.sh")
def jelly_miner_installer(request: Request):
    """The standalone installer, served so a fresh GPU box can one-line itself in:

        curl -sSL http://<store>:8787/api/jelly/mining/install-miner.sh \\
          | bash -s -- --url http://<store>:8787 --token <TOKEN> --name rig1

    Same rig-token gate as the miner download — it is fetched by machines that are
    about to mine, not by browsers."""
    _check_miner(request)
    if not _INSTALLER_FILE.is_file():
        raise HTTPException(404, "installer missing from install")
    return FileResponse(str(_INSTALLER_FILE), media_type="text/x-shellscript",
                        filename="install-miner.sh")


def _my_miner_url() -> str:
    """The URL a rig should point at — derived at runtime, never hardcoded.

    Prefers this box's LAN address because that is where rigs almost always live.
    (It also fixes the public release: the old copy-paste command carried a literal
    LAN IP, which the retail scrub rewrote to 127.0.0.1 — leaving every public user
    a command that only ever worked on the store box itself. Detecting the address
    means each install prints its own.) A buddy mining from outside the LAN should
    substitute the node's public URL."""
    import socket
    from config import PORT
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          # no packet sent; just picks the route
        ip = s.getsockname()[0]
        s.close()
        return f"http://{ip}:{PORT}"
    except Exception:
        return (PUBLIC_BASE_URL or f"http://127.0.0.1:{PORT}").rstrip("/")


@router.get("/api/jelly/miner-token")
def jelly_miner_token():
    """Session-only: the token, a copy-paste run command, and the one-line installer."""
    tok = _miner_token()
    url = _my_miner_url()
    return {"token": tok, "url": url,
            "run": f"python3 jellyminer.py --url {url} --token {tok} --name $(hostname -s)",
            "install": (f"curl -sSL {url}/api/jelly/mining/install-miner.sh -H 'X-Jelly-Token: {tok}' "
                        f"| bash -s -- --url {url} --token {tok} --name $(hostname -s)")}


@router.get("/api/jelly/miner-yield")
def jelly_miner_yield():
    """Is mining standing down for the AI queue right now, and on what settings?
    Session-guarded (outside the /api/jelly/mining/ LAN exemption) — this is the
    god's view + controls, not part of the rig protocol."""
    hold = mining_hold()
    return {"enabled": _yield_enabled(), "settle_sec": _settle_sec(),
            "retry_sec": _retry_sec(), "held": bool(hold),
            "queue_busy": _queue_busy(), **hold}


@router.post("/api/jelly/miner-yield")
def jelly_miner_yield_set(payload: dict = Body(...)):
    """House rule: every gate ships with a toggle. Default ON (it fixes a real
    failure), but flip `enabled` off and rigs mine straight through AI work."""
    conn = get_conn()
    try:
        def put(key, val):
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(val)))
        if "enabled" in payload:
            put(YIELD_KEY, "1" if payload["enabled"] else "0")
        if "settle_sec" in payload:
            put(SETTLE_KEY, max(0, min(600, int(float(payload["settle_sec"])))))
        if "retry_sec" in payload:
            put(RETRY_KEY, max(2, min(300, int(float(payload["retry_sec"])))))
        conn.commit()
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"bad value: {e}")
    finally:
        conn.close()
    return jelly_miner_yield()


# ── owner + agent + defence controls ─────────────────────────────────────────
# All session-guarded: these live OUTSIDE the /api/jelly/mining/ LAN exemption on
# purpose. A rig may fetch work and submit nonces; it may never read or rewrite
# the owner's schedule. Same reasoning as /api/jelly/miner-yield.
@router.get("/api/jelly/miner-policy")
def jelly_miner_policy():
    """The whole envelope + what each rig is actually doing inside it."""
    now = time.time()
    raw_windows = str(get_setting(SCHED_WIN_KEY, "") or "")
    try:
        wins = parse_windows(raw_windows)
        win_err = ""
    except ValueError as e:
        wins, win_err = [], str(e)
    st = jellycoin.status()
    rigs = []
    for m in st.get("miners", []):
        p = rig_policy(m["name"], now)
        rigs.append({**p, "name": m["name"], "gpu": m.get("gpu", ""),
                     "online": m.get("online"), "hours_today": hours_today(m["name"], now),
                     "held": bool(mining_hold(now, m["name"]))})
    return {"schedule": {"enabled": _sflag(SCHED_ON_KEY, "0"), "windows": raw_windows,
                         "daily_hours": _snum(SCHED_HOURS_KEY, 0, 0, 24),
                         "open_now": _in_windows(wins, now), "tz": tz_name(),
                         "error": win_err},
            "defaults": {"throttle": DEFAULT_THROTTLE, "batch": DEFAULT_BATCH,
                         "throttle_max": THROTTLE_MAX,
                         "batch_min": BATCH_MIN, "batch_max": BATCH_MAX},
            "rigs": rigs, "policy": _sjson(POLICY_KEY, {}),
            "agent": {**agent_envelope(), "plan": active_agent_plan(now)}}


@router.post("/api/jelly/miner-policy")
def jelly_miner_policy_set(payload: dict = Body(...)):
    """Owner-only writes. House rule: the schedule ships with a toggle (default
    OFF) so none of this changes behaviour until it is asked for."""
    pol = _sjson(POLICY_KEY, {})
    conn = get_conn()
    try:
        if "sched_enabled" in payload:
            _put(conn, SCHED_ON_KEY, "1" if payload["sched_enabled"] else "0")
        if "windows" in payload:
            raw = str(payload["windows"] or "").strip()
            try:
                parse_windows(raw)                  # validate before it can wedge anything
            except ValueError as e:
                raise HTTPException(400, str(e))
            _put(conn, SCHED_WIN_KEY, raw)
        if "daily_hours" in payload:
            _put(conn, SCHED_HOURS_KEY, max(0.0, min(24.0, float(payload["daily_hours"] or 0))))
        if "agent_enabled" in payload:
            _put(conn, AGENT_ON_KEY, "1" if payload["agent_enabled"] else "0")
        if "agent_min_throttle" in payload:
            _put(conn, AGENT_MIN_THROTTLE_KEY,
                 max(0, min(THROTTLE_MAX, int(float(payload["agent_min_throttle"])))))
        if "agent_max_pause_min" in payload:
            _put(conn, AGENT_MAX_PAUSE_KEY, max(0, min(1440, int(float(payload["agent_max_pause_min"])))))
        if "agent_max_minutes" in payload:
            _put(conn, AGENT_MAX_MINUTES_KEY, max(1, min(1440, int(float(payload["agent_max_minutes"])))))
        rigs = payload.get("rigs")
        if isinstance(rigs, dict):
            for rig, cfg in rigs.items():
                if not isinstance(cfg, dict):
                    continue
                cur = dict(pol.get(str(rig)[:40]) or {})
                if "throttle" in cfg:
                    cur["throttle"] = max(0, min(THROTTLE_MAX, int(float(cfg["throttle"]))))
                if "batch" in cfg:
                    cur["batch"] = max(BATCH_MIN, min(BATCH_MAX, int(float(cfg["batch"]))))
                if "cost" in cfg:
                    cur["cost"] = "free" if str(cfg["cost"]).lower() == "free" else "ai"
                pol[str(rig)[:40]] = cur
            _put(conn, POLICY_KEY, json.dumps(pol))
        if payload.get("clear_agent_plan"):
            _put(conn, AGENT_PLAN_KEY, "")
        conn.commit()
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"bad value: {e}")
    finally:
        conn.close()
    return jelly_miner_policy()


@router.post("/api/jelly/agent-plan")
def jelly_agent_plan(payload: dict = Body(...)):
    """The Company decides when/how hard to mine — inside the owner's envelope.
    403 while the toggle is off; every number clamped and echoed back."""
    return propose_agent_plan(
        agent=payload.get("agent", "the Company"), rig=payload.get("rig", "*"),
        throttle=payload.get("throttle"), pause_min=payload.get("pause_min", 0),
        minutes=payload.get("minutes", 60), reason=payload.get("reason", ""))


@router.get("/api/jelly/agent-plans")
def jelly_agent_plans(limit: int = 25):
    conn = get_conn()
    try:
        conn.execute(_PLANS_DDL)
        rows = conn.execute("SELECT * FROM jelly_agent_plans ORDER BY id DESC LIMIT ?",
                            (max(1, min(100, limit)),)).fetchall()
        return {"plans": [dict(r) for r in rows], "envelope": agent_envelope(),
                "active": active_agent_plan()}
    finally:
        conn.close()


@router.get("/api/jelly/miner-defense")
def jelly_miner_defense(history: int = 120):
    """Measured share of network hashpower, the alert level, and the history that
    makes slow erosion visible."""
    st = defense_state(fresh=True)
    conn = get_conn()
    try:
        conn.execute(_DEF_LOG_DDL)
        hist = [dict(r) for r in conn.execute(
            "SELECT at,share_pct,net_hashrate,my_hashrate,blocks,level FROM jelly_defense_log "
            "ORDER BY id DESC LIMIT ?", (max(1, min(500, history)),))][::-1]
    finally:
        conn.close()
    return {**st, "history": hist, "sample_min": _snum(DEF_SAMPLE_MIN_KEY, DEF_SAMPLE_MIN_DEFAULT, 1, 1440)}


@router.post("/api/jelly/miner-defense")
def jelly_miner_defense_set(payload: dict = Body(...)):
    """Thresholds + toggles. Both toggles ship ON — the chain protects itself
    without being asked — but the house rule stands: they can be turned off.
    `stand_down` is the manual override that ends an engagement early."""
    conn = get_conn()
    try:
        if "enabled" in payload:
            _put(conn, DEF_ON_KEY, "1" if payload["enabled"] else "0")
        if "preempt_ai" in payload:
            _put(conn, DEF_PREEMPT_KEY, "1" if payload["preempt_ai"] else "0")
        for key, field, lo, hi in ((DEF_WARN_KEY, "warn_pct", 0, 100),
                                   (DEF_ACT_KEY, "act_pct", 0, 100),
                                   (DEF_CLEAR_KEY, "clear_pct", 0, 100),
                                   (DEF_SETTLE_KEY, "settle_min", 0, 1440),
                                   (DEF_WINDOW_KEY, "window_blocks", 5, 500),
                                   (DEF_SAMPLE_MIN_KEY, "sample_min", 1, 1440)):
            if field in payload:
                _put(conn, key, max(lo, min(hi, float(payload[field]))))
        if "my_rigs" in payload:
            _put(conn, DEF_MY_RIGS_KEY, str(payload["my_rigs"] or "")[:500])
        if payload.get("stand_down"):
            mins = max(1, min(1440, int(float(payload.get("suppress_min", 60)))))
            _put(conn, DEF_MODE_KEY, json.dumps({
                "engaged": False, "since": 0, "recovering": 0,
                "suppress_until": time.time() + mins * 60}))
            _def_gate.update(armed=False, engaged_at=0.0, ai_seconds=0.0, since=0.0)
            logger.warning(f"[jelly] chain defence stood down BY HAND for {mins} min")
        conn.commit()
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"bad value: {e}")
    finally:
        conn.close()
    _def_cache.update(at=0.0, state=None)           # thresholds changed → re-measure now
    return jelly_miner_defense()


# ── buddy-share compute billing (peers federation) ───────────────────────────
@router.get("/api/jelly/peer-billing")
def jelly_peer_billing():
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        peers = [dict(r) for r in conn.execute(
            "SELECT name,balance FROM jelly_wallets WHERE kind='peer' ORDER BY balance DESC")]
        comped = conn.execute("SELECT COUNT(*) c FROM jelly_txs WHERE kind='compute_comped'").fetchone()["c"]
    finally:
        conn.close()
    return {"enabled": jellycoin.peer_billing_enabled(),
            "price_jly": jellycoin.peer_job_price("llm") / jellycoin.UNIT,
            "embedding_price_jly": jellycoin.peer_job_price("embedding") / jellycoin.UNIT,
            "peer_wallets": peers, "comped_jobs": int(comped)}


@router.post("/api/jelly/peer-billing")
def jelly_peer_billing_set(payload: dict = Body(...)):
    conn = get_conn()
    try:
        if "enabled" in payload:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                         (jellycoin.PEER_BILLING_KEY, "1" if payload["enabled"] else "0"))
        if "price_jly" in payload:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                         (jellycoin.PEER_PRICE_KEY, str(max(0.0, float(payload["price_jly"])))))
        conn.commit()
    finally:
        conn.close()
    return jelly_peer_billing()


# ── buddy-share mining pool (proportional reward splitting; toggle default OFF) ─
@router.get("/api/jelly/mode")
def jelly_mode_get():
    """Are we hosting our own chain, or participating on a buddy's network?"""
    return {"mode": jellycoin.jelly_mode(), "home_peer": jellycoin.jelly_home_peer(),
            "chain_is_used": jellycoin.chain_is_used()}


@router.post("/api/jelly/mode")
def jelly_mode_set(payload: dict = Body(...)):
    """Found our own chain, or join a buddy's. Joining is refused once our own
    chain has been used — see set_jelly_mode."""
    try:
        return jellycoin.set_jelly_mode(str(payload.get("mode", "")),
                                        str(payload.get("home_peer", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/jelly/pool")
def jelly_pool():
    return jellycoin.pool_state()


@router.post("/api/jelly/pool")
def jelly_pool_set(payload: dict = Body(...)):
    """God-side controls (session-guarded — NOT in the mining exemption): flip the
    pool toggle and/or map named rigs to payout wallets (e.g. rig → peer:<name>)."""
    if "enabled" in payload:
        jellycoin.set_pool_enabled(bool(payload["enabled"]))
    owners = payload.get("owners") or {}
    if isinstance(owners, dict):
        for rig, owner in owners.items():
            try:
                jellycoin.set_rig_owner(str(rig), str(owner))
            except ValueError:
                pass
    return jellycoin.pool_state()


# ── NFTs ─────────────────────────────────────────────────────────────────────
@router.post("/api/jelly/nft/mint")
def jelly_nft_mint(payload: dict = Body(...)):
    path = str(payload.get("file_path", "")).strip()
    title = str(payload.get("title", "")).strip() or Path(path).stem
    owner = str(payload.get("owner", jellycoin.TREASURY)).strip() or jellycoin.TREASURY
    try:
        return jellycoin.mint_nft(owner, path, title, meta={
            "artist": str(payload.get("artist", "Acme Studio")),
            "note": str(payload.get("note", ""))[:300]})
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/jelly/nft/list")
def jelly_nft_list():
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT * FROM jelly_nfts ORDER BY id DESC LIMIT 100").fetchall()
        return {"nfts": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/api/jelly/nft/transfer")
def jelly_nft_transfer(payload: dict = Body(...)):
    try:
        return jellycoin.transfer_nft(str(payload.get("token_id", "")),
                                      str(payload.get("from", "")), str(payload.get("to", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── missions: agents push/sell JLY — always behind god approval ──────────────
_MISSION_KINDS = {"promo": "a social/blog promo pitch for JellyCoin",
                  "perk": "a 'pay/earn with JLY' perk idea for the example.com store",
                  "sell": "an in-community offer to sell/swap a small JLY bundle"}


@router.post("/api/jelly/missions/draft")
def jelly_mission_draft(payload: dict = Body(default={})):
    kind = str(payload.get("kind", "promo"))
    if kind not in _MISSION_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(_MISSION_KINDS)}")
    st = jellycoin.status()
    user = (f"Mission kind: {kind} — {_MISSION_KINDS[kind]}.\n"
            f"Chain facts: height {st['height']}, supply {st['supply']:.0f} JLY, "
            f"{st['miners_online']} GPU rig(s) online, {st['nft_count']} NFTs minted.\n"
            "Write the pitch now.")
    title, pitch = f"JLY {kind} pitch", ""
    try:
        # through the unified queue — the orch loads the model (with idle-TTL) and
        # the draft shows up as a queue entry instead of a bare JIT call
        raw = run_llm_job(lambda: _call_lmstudio(get_prompt("jelly_mission"), user, max_tokens=700),
                          "jelly:mission-draft", wait=240)
        pitch = (raw or "").strip()
        if pitch:
            title = pitch.splitlines()[0].strip("# ").strip()[:80] or title
    except Exception as e:
        logger.warning(f"[jelly] mission LLM draft failed, using template: {e}")
    if not pitch:
        pitch = (f"JellyCoin ({st['symbol']}) is Acme's own GPU-mined token — "
                 f"{st['supply']:.0f} JLY minted across {st['height']} real proof-of-work blocks. "
                 f"Old graphics cards earn it, the Company's crew boosts it, and our art becomes "
                 f"NFTs on it. Idea ({kind}): spotlight one NFT and offer a small JLY reward "
                 "for community members who share it.")
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        cur = conn.execute("INSERT INTO jelly_missions (kind,title,pitch,agent) VALUES (?,?,?,?)",
                           (kind, title, pitch, str(payload.get("agent", "the Company"))[:60]))
        conn.commit()
        return {"ok": True, "id": cur.lastrowid, "title": title, "pitch": pitch, "status": "proposed"}
    finally:
        conn.close()


@router.get("/api/jelly/missions")
def jelly_missions():
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        rows = conn.execute("SELECT * FROM jelly_missions ORDER BY id DESC LIMIT 50").fetchall()
        return {"missions": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post("/api/jelly/missions/{mission_id}/decide")
def jelly_mission_decide(mission_id: int, payload: dict = Body(...)):
    approve = bool(payload.get("approve"))
    conn = get_conn()
    try:
        jellycoin.ensure_schema(conn)
        row = conn.execute("SELECT * FROM jelly_missions WHERE id=?", (mission_id,)).fetchone()
        if not row:
            raise HTTPException(404, "unknown mission")
        if row["status"] != "proposed":
            raise HTTPException(400, f"already {row['status']}")
        status = "approved" if approve else "rejected"
        conn.execute("UPDATE jelly_missions SET status=?, decided_at=datetime('now') WHERE id=?",
                     (status, mission_id))
        conn.commit()
    finally:
        conn.close()
    if approve:
        try:
            from world_defs import log_town
            log_town(f"📣 The god approved a JellyCoin {row['kind']} mission: {row['title']}")
        except Exception:
            pass
    return {"ok": True, "id": mission_id, "status": status}
