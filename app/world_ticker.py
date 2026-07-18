"""
The Company — background ticker.

Advances the world on a fixed cadence in a daemon thread, INDEPENDENT of whether
anyone is watching. This decouples the simulation from HTTP polling (the previous
design only advanced when /api/world/state was hit), which is the key to scaling:
one authoritative loop owns time; the API only ever reads state.

Mirrors the app's existing scheduler.py pattern (a named daemon thread started at
startup). Every step is wrapped so one failure never kills the loop.
"""
import time, threading, logging

from deps import get_conn
import world_defs as wd
import world_sim, world_gov, world_systems, world_settings as ws
import world_orchestra, world_raid, world_security, world_tech
from world_balance import TICK_INTERVAL_SEC, INCIDENT_EVERY_SEC

log = logging.getLogger("store")
_started = False


def _safe(label, fn):
    try:
        fn()
    except Exception as ex:
        log.error("world_ticker %s error: %s", label, ex)


def _cadence(c, key, every):
    """True at most once per `every` seconds (persisted in world_meta)."""
    now = time.time()
    last = float(wd.mget(c, key, 0) or 0)
    if not last:
        wd.mset(c, key, now)
        return False                 # don't fire on the very first observation
    if now - last >= every:
        wd.mset(c, key, now)
        return True
    return False


def _loop():
    log.info("[world] ticker started (every %ss)", TICK_INTERVAL_SEC)
    while True:
        time.sleep(TICK_INTERVAL_SEC)
        conn = None
        try:
            conn = get_conn()
            wd.seed(conn)
            _safe("beats", lambda: world_security.assign_beats(conn.cursor(),
                  [dict(r) for r in conn.execute("SELECT * FROM world_agents WHERE kind IN ('worker','openclaw')").fetchall()]))
            _safe("orchestra", lambda: world_orchestra.tick(conn.cursor()))   # seasons + phase baton
            _safe("tech", lambda: world_tech.check_unlock(conn.cursor()))     # material/research tiers (chunk 4)
            _safe("raid_scan", lambda: world_raid.maybe_trigger(conn.cursor()))  # auto-raise raids (self-throttled)
            _safe("raid",      lambda: world_raid.raid_tick(conn.cursor(), TICK_INTERVAL_SEC))  # combat while raiding
            _safe("simulate",  lambda: world_sim.simulate(conn))
            _safe("autobuild", lambda: __import__("world_build").maybe_autobuild(conn))
            _safe("achieve",   lambda: world_systems.check_achievements(conn))
            _safe("leader", lambda: __import__("world_leader").maybe_upgrade(conn))  # Mayor/Boss reinvest the fund (self-cadenced, user-gated)

            c = conn.cursor()
            # Scheduled cognition — the ONLY periodic LLM work. Loads a model at most
            # once per `world_llm_interval_min`, and only during active hours.
            cog_secs = max(300, ws.i("world_llm_interval_min", conn) * 60)
            if ws.cognition_allowed(conn) and _cadence(c, "last_cognition", cog_secs):
                conn.commit()
                _safe("cognition", lambda: world_gov.run_cognition(conn))
            _safe("renew", lambda: __import__("world_renew").tick(conn))   # oldest-first refresh + requests (self-cadenced)
            _safe("genomes", lambda: __import__("world_genome").review(conn))  # agents tweak their own strategies (self-cadenced)
            if _cadence(c, "last_crowns", 1800):   # champions savour their crowns (mood)
                _safe("crowns", lambda: __import__("world_rank").crown_champions(conn.cursor()))
            if ws.b("world_incidents_enabled", conn) and _cadence(c, "last_incident", INCIDENT_EVERY_SEC):
                conn.commit()
                _safe("incident", lambda: world_systems.fire_incident(conn))
            if ws.b("world_meetings_enabled", conn) and \
               _cadence(c, "last_meeting_ts", max(300, ws.i("world_meeting_interval_min", conn) * 60)):
                conn.commit()
                _safe("meeting", lambda: world_gov.hold_meeting(conn))
            if _cadence(c, "last_secscan", 300):       # keep system-health + debug tasks fresh (no LLM)
                conn.commit()
                _safe("secscan", lambda: world_security.run_security_scan(conn.cursor(), verbose=False, llm_review=False))
            if _cadence(c, "last_posture", 120):       # real Command-Center posture (probes stay off the poll path)
                conn.commit()
                _safe("posture", lambda: world_security.refresh_real_posture(conn.cursor()))
            if _cadence(c, "last_prune", 300):
                conn.commit()
                _safe("prune", lambda: world_systems.prune_events(conn))
                _safe("prune_thoughts", lambda: __import__("world_mood").prune(conn.cursor()))
            if _cadence(c, "last_reap", 300):     # self-heal: a crashed automation
                conn.commit()                      # left 'running' must not signal forever
                _safe("reap", lambda: (conn.execute(
                    "UPDATE automation_log SET status='failed' "
                    "WHERE status='running' AND created_at < datetime('now','-30 minutes')"), conn.commit()))
                # media queues too: a crashed generation stuck 'queued'/'generating'
                # pins the studio's activity light + raid work-in-flight FOREVER
                # (gotcha: always time-bound busy signals). 2h >> any real render.
                def _reap_media():
                    for tbl in ("generations", "videos", "audio_clips", "models3d", "world_props"):
                        try:
                            n = conn.execute(
                                f"UPDATE {tbl} SET status='failed' "
                                f"WHERE status IN ('queued','generating','pending','processing') "
                                f"AND created_at < datetime('now','-2 hours')").rowcount
                            if n:
                                log.warning("[world] reaped %d stale %s row(s)", n, tbl)
                        except Exception:
                            pass
                    conn.commit()
                _safe("reap_media", _reap_media)
            conn.commit()
        except Exception as ex:
            log.error("[world] ticker loop error: %s", ex)
        finally:
            if conn:
                try: conn.close()
                except Exception: pass


def start():
    """Start the ticker once (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="world-ticker").start()
