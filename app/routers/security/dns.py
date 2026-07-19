"""Live Pi-hole/DNS monitor — query logs, device profiles, ban/allow, AI log
analysis, and the LM Studio access monitor."""
from fastapi import HTTPException
from deps import *
import pihole
from collections import defaultdict, Counter
import subprocess as _sp
from ._base import router, _fkey, _score


def _audit(action: str, target: str, detail: str = ""):
    conn = get_conn()
    conn.execute("INSERT INTO pihole_actions (action, target, detail) VALUES (?,?,?)",
                 (action, target, detail))
    conn.commit()
    conn.close()


@router.get("/api/security/monitor/config")
def get_monitor_config():
    """Auto-monitor schedule settings (on/off + intervals)."""
    try:
        import scheduler
        running = scheduler.scheduler._thread.is_alive()
    except Exception:
        running = False
    return {
        "running": running,
        "enabled": get_setting("security_monitor_enabled", "0") == "1",
        "interval": int(get_setting("security_monitor_interval", "15")),
        "autoscan": get_setting("security_autoscan_enabled", "0") == "1",
        "scan_interval": int(get_setting("security_scan_interval", "360")),
        "autoanalyze": get_setting("security_autoanalyze_enabled", "0") == "1",
        "analyze_interval": int(get_setting("security_analyze_interval", "120")),
    }


@router.post("/api/security/monitor/config")
def set_monitor_config(data: dict):
    data = data or {}
    conn = get_conn()
    def put(k, v):
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, str(v)))
    for key, dbkey in [("enabled", "security_monitor_enabled"),
                       ("autoscan", "security_autoscan_enabled"),
                       ("autoanalyze", "security_autoanalyze_enabled")]:
        if key in data:
            put(dbkey, "1" if data[key] else "0")
    for key, dbkey in [("interval", "security_monitor_interval"),
                       ("scan_interval", "security_scan_interval"),
                       ("analyze_interval", "security_analyze_interval")]:
        if key in data:
            try:
                put(dbkey, max(1, int(data[key])))
            except (TypeError, ValueError):
                pass
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/api/security/overview")
def security_overview():
    """Top-level status: verdict/score (from findings) + live Pi-hole stats."""
    conn = get_conn()
    scan = conn.execute("SELECT status, last_scan_at FROM security_scans ORDER BY created_at DESC LIMIT 1").fetchone()
    counts = {r["status"]: r["c"] for r in
              conn.execute("SELECT status, COUNT(*) c FROM security_findings GROUP BY status").fetchall()}
    n_clients = conn.execute("SELECT COUNT(*) c FROM network_clients").fetchone()["c"]
    n_susp = conn.execute("SELECT COUNT(*) c FROM network_clients WHERE suspicious=1").fetchone()["c"]
    conn.close()
    out = {"score": _score(), "verdict": (scan["status"] if scan else "unknown"),
           "last_scan": scan["last_scan_at"] if scan else None,
           "finding_counts": counts, "clients": n_clients, "suspicious_clients": n_susp,
           "pihole_configured": pihole.configured(), "pihole_ok": False}
    if pihole.configured():
        try:
            s = pihole.get_summary().get("queries", {})
            out["pihole_ok"] = True
            out["queries_total"] = s.get("total")
            out["percent_blocked"] = round(s.get("percent_blocked", 0), 1)
            out["blocked_total"] = s.get("blocked")
        except Exception as e:
            out["pihole_error"] = str(e)
    return out


@router.get("/api/security/logs")
def security_logs(length: int = 200, only_blocked: bool = False, client: str = ""):
    """Recent Pi-hole DNS query log (live)."""
    if not pihole.configured():
        raise HTTPException(400, "Pi-hole password not set (STORE_PIHOLE_API_PASS)")
    try:
        qs = pihole.get_queries(min(length, 1000))
    except Exception as e:
        raise HTTPException(502, str(e))
    if only_blocked:
        qs = [q for q in qs if q["blocked"]]
    if client:
        qs = [q for q in qs if client.lower() in (q["client"] or "").lower()]
    return {"queries": qs, "count": len(qs)}


@router.post("/api/security/monitor/tick")
def monitor_tick(length: int = 1000):
    """Aggregate the recent query window into per-device profiles (what's coming/going)."""
    if not pihole.configured():
        raise HTTPException(400, "Pi-hole password not set")
    try:
        qs = pihole.get_queries(length)
    except Exception as e:
        raise HTTPException(502, str(e))
    agg = defaultdict(lambda: {"name": "", "total": 0, "blocked": 0, "domains": Counter()})
    for q in qs:
        ip = q["client_ip"] or q["client"] or "?"
        a = agg[ip]
        a["name"] = q["client"] or ip
        a["total"] += 1
        if q["blocked"]:
            a["blocked"] += 1
        if q["domain"]:
            a["domains"][q["domain"]] += 1
    conn = get_conn()
    for ip, a in agg.items():
        top = json.dumps(a["domains"].most_common(10))
        row = conn.execute("SELECT ip, suspicious FROM network_clients WHERE ip=?", (ip,)).fetchone()
        if row:
            conn.execute("UPDATE network_clients SET name=?, last_seen=datetime('now'), "
                         "total_queries=?, blocked_queries=?, top_domains=? WHERE ip=?",
                         (a["name"], a["total"], a["blocked"], top, ip))
        else:
            conn.execute("INSERT INTO network_clients (ip, name, total_queries, blocked_queries, top_domains) "
                         "VALUES (?,?,?,?,?)", (ip, a["name"], a["total"], a["blocked"], top))
    conn.commit()
    conn.close()
    return {"clients": len(agg), "queries_scanned": len(qs)}


@router.get("/api/security/profile")
def security_profile():
    """Per-device profiles built by the monitor (recent activity window)."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM network_clients ORDER BY suspicious DESC, total_queries DESC").fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["top_domains"] = json.loads(d.get("top_domains") or "[]")
        except Exception:
            d["top_domains"] = []
        out.append(d)
    return {"clients": out}


@router.post("/api/security/clients/{ip}/flag")
def flag_client(ip: str, data: dict):
    """Mark a device suspicious / add a note."""
    conn = get_conn()
    cur = conn.execute("UPDATE network_clients SET suspicious=?, notes=? WHERE ip=?",
                       (1 if data.get("suspicious") else 0, data.get("notes", ""), ip))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    if not changed:
        raise HTTPException(404, "Client not found")
    _audit("flag", ip, f"suspicious={bool(data.get('suspicious'))}")
    return {"ok": True}


# ── Ban / allow domains via Pi-hole ──────────────────────────────────────────
@router.post("/api/security/ban")
def ban_domain(data: dict):
    domain = (data or {}).get("domain", "").strip().lower()
    if not domain:
        raise HTTPException(400, "domain required")
    try:
        pihole.add_domain(domain, "deny", data.get("comment", "Banned from Store"))
    except Exception as e:
        raise HTTPException(502, f"Pi-hole error: {e}")
    _audit("ban", domain, data.get("comment", ""))
    # Mark any matching findings as remediated/banned
    conn = get_conn()
    conn.execute("UPDATE security_findings SET status='remediated', updated_at=datetime('now') WHERE domain=?", (domain,))
    conn.commit()
    conn.close()
    return {"ok": True, "domain": domain}


@router.post("/api/security/allow")
def allow_domain(data: dict):
    domain = (data or {}).get("domain", "").strip().lower()
    if not domain:
        raise HTTPException(400, "domain required")
    try:
        pihole.add_domain(domain, "allow", data.get("comment", "Allowed from Store"))
    except Exception as e:
        raise HTTPException(502, f"Pi-hole error: {e}")
    _audit("allow", domain, data.get("comment", ""))
    return {"ok": True, "domain": domain}


@router.post("/api/security/unban")
def unban_domain(data: dict):
    domain = (data or {}).get("domain", "").strip().lower()
    kind = (data or {}).get("kind", "deny")
    if not domain:
        raise HTTPException(400, "domain required")
    try:
        pihole.remove_domain(domain, kind)
    except Exception as e:
        raise HTTPException(502, f"Pi-hole error: {e}")
    _audit("unban", domain, kind)
    return {"ok": True}


@router.get("/api/security/blocklist")
def get_blocklist(kind: str = "deny"):
    if not pihole.configured():
        raise HTTPException(400, "Pi-hole password not set")
    try:
        return {"kind": kind, "domains": pihole.list_domains(kind)}
    except Exception as e:
        raise HTTPException(502, str(e))


@router.get("/api/security/actions")
def get_actions(limit: int = 50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM pihole_actions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return {"actions": [dict(r) for r in rows]}


# ── AI log analysis (local model directs the hunt) ───────────────────────────
_ANALYZE_SYSTEM = (
    "You are a network security analyst AI protecting a home network via Pi-hole DNS. "
    "Given recent DNS activity grouped by device, identify SUSPICIOUS domains: telemetry/tracking, "
    "ad/malware/C2-like, data exfiltration, or abnormal volume. Ignore normal CDN/service traffic.\n\n"
    "Output ONE line per suspicious finding in EXACTLY this pipe format, and NOTHING else "
    "(no reasoning, no markdown):\n"
    "SEVERITY | domain | action | short reason\n"
    "SEVERITY is High, Medium, or Low. action is ban, watch, or allow.\n"
    "Example:\n"
    "High | dpm.demdex.net | ban | Adobe ad/tracking network contacted by Galaxy phone\n"
    "If nothing is suspicious, output exactly: NONE"
)


def _parse_analysis(raw: str) -> list:
    """Robustly extract 'SEVERITY | domain | action | reason' lines from model output
    (tolerates surrounding reasoning/markdown that instruction-following models add)."""
    out = []
    for line in (raw or "").splitlines():
        line = line.strip().strip("`").lstrip("-*• ").strip()
        if line.upper() == "NONE":
            continue
        parts = [p.strip().strip("`*") for p in line.split("|")]
        if len(parts) < 4:
            continue
        sev = parts[0].split()[0] if parts[0] else ""
        if sev.lower() not in ("high", "medium", "low"):
            continue
        domain = parts[1].lower()
        if not domain or " " in domain:
            continue
        out.append({"severity": sev.title(), "domain": domain,
                    "action": parts[2].lower(), "reason": parts[3]})
    return out


@router.post("/api/security/analyze")
def analyze_logs(length: int = 800):
    """Send recent DNS activity to the local model to hunt for suspicious behavior.
    Runs via the orchestrator (loads the model); returns {task_id} to poll."""
    if not pihole.configured():
        raise HTTPException(400, "Pi-hole password not set")
    try:
        qs = pihole.get_queries(length)
    except Exception as e:
        raise HTTPException(502, str(e))

    per_client = defaultdict(lambda: {"total": 0, "blocked": 0, "domains": Counter()})
    for q in qs:
        c = q["client"] or "?"
        per_client[c]["total"] += 1
        if q["blocked"]:
            per_client[c]["blocked"] += 1
        if q["domain"]:
            per_client[c]["domains"][q["domain"]] += 1
    lines = []
    for c, info in sorted(per_client.items(), key=lambda x: -x[1]["total"])[:40]:
        top = ", ".join(f"{d}({n})" for d, n in info["domains"].most_common(12))
        lines.append(f"- {c}: {info['total']} queries, {info['blocked']} blocked | domains: {top}")
    prompt = "Recent Pi-hole DNS activity by device:\n" + "\n".join(lines)

    def _work():
        raw = _call_lmstudio(get_prompt('security_analyze'), prompt, max_tokens=1500)
        findings = _parse_analysis(raw)
        added = 0
        seen_domains = set()
        conn = get_conn()
        for f in findings:
            domain = f["domain"]
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            issue = f"{domain}: {f['reason']}"
            k = _fkey(issue)
            if conn.execute("SELECT id FROM security_findings WHERE fkey=?", (k,)).fetchone():
                continue
            conn.execute("INSERT INTO security_findings (fkey, issue, action, priority, status, domain) "
                         "VALUES (?,?,?,?, 'pending', ?)",
                         (k, issue, f["action"], f["severity"], domain))
            added += 1
        conn.commit()
        conn.close()
        return {"analyzed": len(qs), "findings_added": added, "score": _score()}

    _audit("analyze", "logs", f"{len(qs)} queries")
    tid = orch.submit_llm(_work, desc="AI network log analysis", priority=2, task="security_analyze")   # background
    return {"task_id": tid}


# ─── LLM access monitor — who is using the node's LM Studio (:1234)? ──────────
_LLM_MON_SNIPPET = r'''
echo "BIND:$(ss -tlnp 2>/dev/null | grep ':1234' | awk '{print $4}' | head -1)"
code=$(curl -s -o /dev/null -w "%{http_code}" -m5 http://localhost:1234/v1/models 2>/dev/null)
[ "$code" = "401" ] || [ "$code" = "403" ] && echo "AUTH:on" || echo "AUTH:off"
ss -tn 2>/dev/null | grep ':1234' | awk '{print $5}' | sed 's/^/CONN:/'
f=$(ls -t ~/.lmstudio/server-logs/*/*.log 2>/dev/null | head -1)
grep -aiE "Received request|Endpoint=|Client=" "$f" 2>/dev/null | tail -25 | sed 's/^/LOG:/'
'''


@router.get("/api/security/llm-access")
def security_llm_access():
    """Surface who's using the node's LM Studio: its bind (is it exposed to the LAN?),
    live TCP peers on :1234, and recent request-log lines — so unexpected activity
    (openclaw vs the store vs something/someone else) is visible."""
    host = globals().get("GPU_HOST", "")
    known = {globals().get("GPU_HOST", ""), "127.0.0.1", "::1"}
    out = {"gpu_host": host, "bind": "", "exposed": False, "api_key_required": False,
           "connections": [], "recent": [], "known_hint": "the store host + your OpenClaw node",
           "error": None}
    try:
        r = _sp.run(BOX_SSH + ["bash -s"], input=_LLM_MON_SNIPPET,
                    capture_output=True, text=True, timeout=25)
    except Exception as e:
        out["error"] = f"Couldn't reach the node: {e}"
        return out
    for line in (r.stdout or "").splitlines():
        if line.startswith("BIND:"):
            b = line[5:].strip()
            out["bind"] = b or "(not listening)"
            out["exposed"] = b.startswith(("0.0.0.0", "*", "[::]"))
        elif line.startswith("AUTH:"):
            out["api_key_required"] = line[5:].strip() == "on"
        elif line.startswith("CONN:"):
            peer = line[5:].strip()
            ip = peer.rsplit(":", 1)[0].strip("[]")
            if ip and ip not in ("127.0.0.1", "::1", ""):
                out["connections"].append(ip)
        elif line.startswith("LOG:"):
            out["recent"].append(line[4:].strip()[:180])
    out["connections"] = sorted(set(out["connections"]))
    out["unknown_connections"] = [ip for ip in out["connections"] if ip not in known]
    return out
