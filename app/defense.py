"""
Unified defense status — every background system keeping the box safe, in one place.

The security tab grew organically: scheduled audit, backups, Network Guardian,
AI Shield, the Pi-hole monitor, fail2ban, UFW, the GPU node's ComfyUI firewall,
LM Studio auth, secrets-at-rest, agent action gates… each visible only in its own
corner (or not at all). This module answers, in ONE call: what is protecting us,
is it actually on, when did it last run, and what needs attention.

Two families:
  • App defenses  — the store's own scheduled jobs (settings-gated, scheduler.py).
    Togglable here; last-run comes from the persisted `defense_last_<job>` keys.
  • Host defenses — probed live (docker, journalctl, ssh to the GPU node, HTTP).
    Not togglable from the app; each carries a `fix` when it needs the user.

Every probe degrades gracefully and is bounded by a short timeout; the router
caches the whole result so opening the tab twice doesn't re-probe everything.
"""
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import httpx

import netwatch
import secaudit
from config import BOX_SSH, GPU_HOST, DB_PATH
from deps import get_conn, get_setting

log = logging.getLogger("store")


def _d(id, name, icon, status, detail, *, kind="host", enabled=None, toggle=False,
       last_run=None, interval_min=None, fix=""):
    """status: on | off | warn | unknown."""
    return {"id": id, "name": name, "icon": icon, "status": status, "detail": detail,
            "kind": kind, "enabled": enabled, "toggle": toggle, "last_run": last_run,
            "interval_min": interval_min, "fix": fix}


# ── app defenses: the scheduler's jobs (settings-gated) ──────────────────────
# id → (settings key, default, interval key, default minutes, last-run job name)
APP_DEFENSES = {
    "sec_audit":   ("security_audit_enabled",       "0", "security_audit_interval",    1440, "audit"),
    "backups":     ("backup_enabled",               "1", "backup_interval_min",        1440, "backup"),
    "guardian":    ("netguard_auto_enabled",        "0", "netguard_interval",           360, "guardian"),
    "ai_watch":    ("ai_watch_enabled",             "0", "ai_watch_interval",            60, "aiwatch"),
    "dns_monitor": ("security_monitor_enabled",     "0", "security_monitor_interval",    15, "tick"),
    "autoscan":    ("security_autoscan_enabled",    "0", "security_scan_interval",      360, "scan"),
    "ai_hunt":     ("security_autoanalyze_enabled", "0", "security_analyze_interval",   120, "analyze"),
}

_APP_META = {
    "sec_audit":   ("Scheduled hardening audit", "🗓️", "Snapshots the full audit, diffs vs last, alerts regressions to the God Console."),
    "backups":     ("Automated DB backups", "💾", "Consistent online snapshot of store.db, local + off-box, with retention."),
    "guardian":    ("Network Guardian auto-block", "🛡️", "Auto-blocks clear ad/tracker/ACR domains network-wide — never functional/local, always reversible."),
    "ai_watch":    ("AI Shield agent watch", "🤖", "Watches agents for rogue behaviour (payout/code bursts, unknown actors) → God Console."),
    "dns_monitor": ("Pi-hole device monitor", "📡", "Snapshots recent DNS activity into per-device profiles."),
    "autoscan":    ("Pi-hole config scan", "🔍", "Periodically re-runs the Pi-hole hardening scan."),
    "ai_hunt":     ("AI DNS threat hunt", "🧠", "Local model hunts suspicious domains in DNS logs (uses the GPU)."),
}


def last_run(job):
    """Persisted epoch (string) → iso + seconds-ago, or None if it never ran."""
    v = get_setting(f"defense_last_{job}", "")
    if not v:
        return None
    try:
        t = float(v)
    except (TypeError, ValueError):
        return None
    return {"at": datetime.fromtimestamp(t).isoformat(timespec="seconds"),
            "ago_s": max(0, int(time.time() - t)),
            "note": get_setting(f"defense_note_{job}", "") or ""}


def record_run(job, note=""):
    """Called by the scheduler after each job so 'last ran' survives restarts."""
    try:
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (f"defense_last_{job}", str(time.time())))
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                     (f"defense_note_{job}", str(note)[:200]))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("record_run(%s) failed: %s", job, e)


def persisted_last(job):
    """Epoch float for the scheduler to seed its timers from (0.0 if never ran)."""
    try:
        return float(get_setting(f"defense_last_{job}", "") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _app_defenses():
    out = []
    for id, (key, default, ikey, idef, job) in APP_DEFENSES.items():
        name, icon, desc = _APP_META[id]
        on = get_setting(key, default) == "1"
        try:
            iv = max(1, int(get_setting(ikey, str(idef)) or idef))
        except (TypeError, ValueError):
            iv = idef
        lr = last_run(job)
        detail = desc
        status = "on" if on else "off"
        if on and lr and lr["ago_s"] > iv * 60 * 3:
            status = "warn"
            detail = f"Enabled but hasn't run in {lr['ago_s'] // 3600}h (interval {iv}m) — check the store logs."
        out.append(_d(id, name, icon, status, detail, kind="app", enabled=on,
                      toggle=True, last_run=lr, interval_min=iv))
    return out


# ── host defenses: probed live ────────────────────────────────────────────────
def _pihole_defense():
    st = secaudit._drun(["docker", "ps", "--filter", "name=pihole",
                         "--format", "{{.Status}}"], timeout=8).strip().splitlines()
    up = bool(st and st[0].startswith("Up"))
    return _d("pihole", "Pi-hole DNS filtering", "🕳️",
              "on" if up else "warn",
              f"Container {st[0]}" if up else "Pi-hole container not running — DNS-level ad/tracker blocking is down.",
              fix="" if up else "docker start pihole")


def _fail2ban_defense():
    f2b = secaudit.fail2ban_status()
    if f2b.get("installed"):
        return _d("fail2ban", "fail2ban (SSH brute-force bans)", "⛓️", "on",
                  f"{f2b.get('total_banned', 0)} IP(s) banned across {len(f2b.get('jails', []))} jail(s).")
    return _d("fail2ban", "fail2ban (SSH brute-force bans)", "⛓️", "off",
              "Not installed — SSH brute-force isn't auto-banned. (Low urgency while SSH stays WAN-firewalled.)",
              fix="sudo apt install fail2ban")


def _ufw_defense():
    # `ufw status` needs root; infer from kernel log lines instead.
    out = netwatch._run(["journalctl", "-k", "--since", "-48 hours", "--no-pager",
                         "-g", "UFW"], timeout=10)
    lines = [l for l in out.splitlines() if "UFW" in l]
    if lines:
        return _d("ufw_log", "Firewall (UFW) logging", "🧱", "on",
                  f"{len(lines)} UFW log line(s) in 48h — blocked/attempted inbound is being recorded.")
    return _d("ufw_log", "Firewall (UFW) logging", "🧱", "warn",
              "No UFW kernel-log lines in 48h — logging is likely OFF, so inbound attempts aren't recorded.",
              fix="sudo ufw logging on")


def _comfy_firewall_defense():
    try:
        r = subprocess.run(BOX_SSH + ["systemctl is-active comfy-firewall.service; "
                                      "systemctl is-enabled comfy-firewall.service"],
                           capture_output=True, text=True, timeout=12)
        lines = (r.stdout or "").strip().splitlines() + ["", ""]
        active, enabled = lines[0].strip(), lines[1].strip()
    except Exception as e:
        return _d("comfy_fw", "ComfyUI firewall (GPU node)", "🔥", "unknown",
                  f"GPU node {GPU_HOST} unreachable: {e}")
    if active == "active":
        return _d("comfy_fw", "ComfyUI firewall (GPU node)", "🔥", "on",
                  f"comfy-firewall.service active on {GPU_HOST} — :8188 restricted to LAN + VPN.")
    if enabled == "enabled":
        return _d("comfy_fw", "ComfyUI firewall (GPU node)", "🔥", "warn",
                  f"Unit enabled for next boot on {GPU_HOST} but not started this boot — "
                  "the LAN-only iptables rules may not be applied right now.",
                  fix=f"on {GPU_HOST}: sudo systemctl start comfy-firewall.service")
    return _d("comfy_fw", "ComfyUI firewall (GPU node)", "🔥", "warn",
              f"comfy-firewall.service is '{active or 'missing'}' on {GPU_HOST} — "
              "ComfyUI :8188 may be open beyond the LAN.",
              fix=f"on {GPU_HOST}: sudo systemctl enable --now comfy-firewall.service")


def _lmstudio_defense():
    try:
        code = httpx.get(f"http://{GPU_HOST}:1234/v1/models", timeout=4).status_code
    except Exception:
        return _d("lm_auth", "LM Studio API key", "🔑", "unknown",
                  f"LM Studio ({GPU_HOST}:1234) unreachable right now.")
    if code in (401, 403):
        return _d("lm_auth", "LM Studio API key", "🔑", "on",
                  "Unauthorized callers get 401 — the LLM endpoint requires a key.")
    return _d("lm_auth", "LM Studio API key", "🔑", "warn",
              f"Anonymous request got HTTP {code} — any LAN device can use the LLM.",
              fix="LM Studio → Developer → enable 'Require API Key'")


def _secrets_defense():
    key_file = Path(DB_PATH).parent / ".secret_key"
    has = bool(os.environ.get("STORE_SECRET_KEY")) or key_file.exists()
    if has:
        return _d("secrets", "Secrets encrypted at rest", "🔐", "on",
                  "API keys/tokens in the DB are Fernet-encrypted; key kept outside the DB.")
    return _d("secrets", "Secrets encrypted at rest", "🔐", "warn",
              "No encryption key found — secrets may be stored in plaintext.",
              fix="Restart the store once (the key auto-generates on startup)")


def _gates_defense():
    try:
        import world_ops
        gated = world_ops.gated_kinds()          # LIVE effective set (honors the God Console toggles)
        critical = {"paypal_payout", "add_software"}   # money + code = the dangerous auto-execute paths
        off = sorted(critical - gated)
        if off:
            return _d("gates", "Agent action gates", "⛔", "warn",
                      f"Critical gate(s) turned OFF: {', '.join(off)} — agents could auto-spend or run code without your approval.",
                      fix="Re-enable in The Company → God Console → 🔒 Gates")
        if gated:
            return _d("gates", "Agent action gates", "⛔", "on",
                      f"Always-approval-gated agent actions: {', '.join(sorted(gated))}.")
        return _d("gates", "Agent action gates", "⛔", "warn",
                  "No agent actions are gated — agents could pay out or publish without approval.",
                  fix="Enable gates in The Company → God Console → 🔒 Gates")
    except Exception as e:
        return _d("gates", "Agent action gates", "⛔", "unknown", f"world_ops unavailable: {e}")


def defenses():
    """Every defense with live status. Host probes run concurrently (each shells
    out or does network I/O) so a cold load is one slow probe, not the sum of all."""
    from concurrent.futures import ThreadPoolExecutor

    out = _app_defenses()
    probes = (_pihole_defense, _fail2ban_defense, _ufw_defense,
              _comfy_firewall_defense, _lmstudio_defense, _secrets_defense,
              _gates_defense)

    def _safe(probe):
        try:
            return probe()
        except Exception as e:
            log.warning("defense probe %s failed: %s", probe.__name__, e)
            return None

    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        out += [d for d in pool.map(_safe, probes) if d]
    counts = {"on": 0, "off": 0, "warn": 0, "unknown": 0}
    for d in out:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    return {"defenses": out, "counts": counts, "generated_at": datetime.now().isoformat(timespec="seconds")}


def toggle(id, on, interval_min=None):
    """Flip an app defense's setting (and optionally its interval). Host defenses
    aren't togglable from here — they carry a `fix` instead."""
    if id not in APP_DEFENSES:
        return {"ok": False, "error": f"'{id}' isn't a togglable app defense."}
    key, _default, ikey, idef, _job = APP_DEFENSES[id]
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                 (key, "1" if on else "0"))
    if interval_min is not None:
        try:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                         (ikey, str(max(1, int(interval_min)))))
        except (TypeError, ValueError):
            pass
    conn.commit()
    conn.close()
    return {"ok": True, "id": id, "enabled": bool(on)}


# ── posture: the cheap composite for the Command view ─────────────────────────
def posture():
    """Latest audit snapshot + trend + recent alerts. No live probes — instant."""
    conn = get_conn()
    try:
        secaudit._ensure(conn)
        snap = conn.execute("SELECT created_at,score,grade FROM security_snapshots "
                            "ORDER BY id DESC LIMIT 1").fetchone()
        hist = conn.execute("SELECT created_at,score,grade FROM security_snapshots "
                            "ORDER BY id DESC LIMIT 12").fetchall()
        events = conn.execute("SELECT created_at,severity,text FROM security_events "
                              "ORDER BY id DESC LIMIT 8").fetchall()
    finally:
        conn.close()
    return {
        "score": snap["score"] if snap else None,
        "grade": snap["grade"] if snap else None,
        "snapshot_at": snap["created_at"] if snap else None,
        "history": [dict(h) for h in hist],
        "events": [dict(e) for e in events],
    }
