"""Network Security routes — live connection intelligence + Pi-hole scan/findings."""
import hashlib
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from deps import *
import netwatch
import secaudit
import netguard
import aishield
import defense

router = APIRouter()


@router.get("/api/security/posture")
def security_posture():
    """Cheap composite for the Command view — latest audit snapshot, score trend,
    recent alerts. No live probes; instant."""
    return defense.posture()


@router.get("/api/security/defenses")
def security_defenses():
    """Every background defense (app jobs + host systems) with live status and
    last-run. Probes docker/journal/ssh/http, so cached ~45s."""
    from cache import cached
    return cached("sec:defenses", 45, defense.defenses)


@router.post("/api/security/defenses/toggle")
def security_defenses_toggle(data: dict):
    """Flip an app defense on/off (and optionally set its interval in minutes)."""
    data = data or {}
    r = defense.toggle(data.get("id", ""), bool(data.get("on")), data.get("interval_min"))
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "toggle failed"))
    from cache import invalidate_prefix
    invalidate_prefix("sec:defenses")
    return r


@router.get("/api/security/ai/surface")
def ai_surface():
    """Audit the AI attack surface — exposed model/tool endpoints + agent gates."""
    return {"checks": aishield.ai_surface()}


@router.get("/api/security/ai/bots")
def ai_bots():
    """Bot governance — good AI crawlers (allow), bad scrapers (block), raw clients."""
    return aishield.bots()


@router.post("/api/security/ai/scan")
def ai_scan(data: dict):
    """Scan arbitrary text/file content for prompt-injection / jailbreak / exfil."""
    return aishield.scan_injection((data or {}).get("text", ""))


@router.get("/api/security/ai/anomalies")
def ai_anomalies():
    """Agent-action anomaly watch — rogue-agent detection from the prayer queue."""
    return aishield.agent_anomalies()


@router.get("/api/security/guardian")
def security_guardian():
    """Fingerprint + auto-name devices, categorize their traffic, flag bad actors
    (trackers/ads/retry-loops) and recommend surgical blocks."""
    return netguard.analyze()


@router.post("/api/security/guardian/block")
def security_guardian_block(data: dict):
    """Block bad domains (Pi-hole deny). Never blocks functional/local — surgical + reversible."""
    return netguard.remediate(data.get("domains") or [], auto=False, device=data.get("device", ""))


@router.post("/api/security/guardian/unblock")
def security_guardian_unblock(data: dict):
    d = (data or {}).get("domain", "")
    if not d:
        raise HTTPException(400, "domain required")
    return netguard.unblock(d)


@router.post("/api/security/guardian/name")
def security_guardian_name(data: dict):
    mac = (data or {}).get("mac", "")
    name = (data or {}).get("name", "")
    if not mac or not name:
        raise HTTPException(400, "mac and name required")
    return netguard.set_name(mac, name)


@router.get("/api/security/guardian/actions")
def security_guardian_actions(limit: int = 50):
    return netguard.actions(limit)


@router.get("/api/security/connections")
def security_connections(enrich: bool = True):
    """Live who/what/where: external connections in & out, SSH attempts, exposed
    services + attack surface. This is the 'is it even doing anything' view.

    Cached ~10s: it shells out to `ss`, the sshd journal and geo lookups, so rapid
    tab re-opens don't re-run the whole scan."""
    from cache import cached
    return cached(f"sec:connections:{enrich}", 10, lambda: netwatch.connections(enrich=enrich))


@router.get("/api/security/audit")
def security_audit():
    """Hardening audit — patches, SSH, accounts, exposure, Docker, firewall —
    with a weighted score + letter grade (Lynis/CIS-style, native)."""
    return secaudit.audit()


@router.get("/api/security/web-traffic")
def security_web_traffic():
    """Who's hitting the public services (nginx-proxy-manager access logs):
    visitors, vhosts, status codes, and scanner/probe attempts."""
    return secaudit.web_traffic()


@router.get("/api/security/threats")
def security_threats():
    """Ranked attackers (SSH brute-force, web scanners) with a ready-to-run block
    command + fail2ban status."""
    return secaudit.threats()


@router.get("/api/security/events")
def security_events(limit: int = 40):
    """Scheduled-audit alert history + the security score trend."""
    return secaudit.events(limit)


@router.post("/api/security/audit/run")
def security_audit_run():
    """Take an audit snapshot now + diff vs the last (raises regression alerts)."""
    return secaudit.run_scheduled_audit()

REPORT_DIR  = BASE / "network-security" / "reports"
SCAN_SCRIPT = BASE / "network-security" / "scripts" / "pihole-security-scan.sh"
REPORT_PATH = REPORT_DIR / "SECURITY-REPORT.md"


def _fkey(issue: str) -> str:
    return hashlib.sha256(issue.strip().lower().encode()).hexdigest()[:16]


def _parse_report(content: str) -> dict:
    """Extract verdict + findings from the markdown report."""
    status = "unknown"
    upper = content.upper()
    if "NEEDS ATTENTION" in upper:
        status = "needs_attention"
    elif "HEALTHY" in upper:
        status = "healthy"

    findings = []
    seen = set()
    lines = content.split("\n")

    def add(issue, action="", priority=""):
        issue = (issue or "").strip().strip("*").strip()
        if not issue or issue.lower() in ("issue", "issues found") or issue.startswith("-"):
            return
        k = _fkey(issue)
        if k in seen:
            return
        seen.add(k)
        findings.append({"issue": issue, "action": (action or "").strip(), "priority": (priority or "").strip()})

    # 1) Remediation Plan table:  | Priority | Issue | Action |
    in_table = False
    for ln in lines:
        if "Remediation Plan" in ln:
            in_table = True
            continue
        if in_table:
            if ln.startswith("## ") or ln.startswith("---") or ln.startswith("*Report"):
                in_table = False
                continue
            if "|" in ln:
                cols = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cols) >= 3 and cols[0].lower() not in ("priority", "") and not set(cols[0]) <= {"-", ":"}:
                    add(cols[1], cols[2], cols[0])

    # 2) "Issues found:" bullet list (Section 6)
    in_issues = False
    for ln in lines:
        if "Issues found" in ln:
            in_issues = True
            continue
        if in_issues:
            s = ln.strip()
            if s.startswith("## ") or s.startswith("---"):
                in_issues = False
                continue
            if s.startswith(("-", "*")) and len(s) > 2:
                add(s.lstrip("-* ").strip())

    return {"status": status, "findings": findings}


def _upsert_findings(parsed_findings):
    """Insert new findings as 'pending'; keep existing statuses on re-scan."""
    conn = get_conn()
    for f in parsed_findings:
        k = _fkey(f["issue"])
        row = conn.execute("SELECT id FROM security_findings WHERE fkey=?", (k,)).fetchone()
        if row:
            conn.execute("UPDATE security_findings SET issue=?, action=?, priority=?, updated_at=datetime('now') WHERE fkey=?",
                         (f["issue"], f["action"], f["priority"], k))
        else:
            conn.execute("INSERT INTO security_findings (fkey, issue, action, priority, status) VALUES (?,?,?,?, 'pending')",
                         (k, f["issue"], f["action"], f["priority"]))
    conn.commit()
    conn.close()


def _score():
    """0-100 security score from open (pending/approved) findings, weighted by priority."""
    conn = get_conn()
    rows = conn.execute("SELECT priority FROM security_findings WHERE status IN ('pending','approved')").fetchall()
    conn.close()
    penalty = 0
    for r in rows:
        p = (r["priority"] or "").lower()
        penalty += 20 if "high" in p else 10 if "med" in p else 5
    return max(0, 100 - penalty)


def _run_scan() -> dict:
    if not SCAN_SCRIPT.exists():
        raise HTTPException(404, f"Scan script not found at {SCAN_SCRIPT}")
    env = dict(os.environ)
    if PIHOLE_API_PASS:
        env["PIHOLE_API_PASS"] = PIHOLE_API_PASS
    env["PIHOLE_API_PORT"] = PIHOLE_API_PORT
    env["PIHOLE_CONTAINER"] = PIHOLE_CONTAINER
    result = subprocess.run(["bash", str(SCAN_SCRIPT)], capture_output=True, text=True, env=env, timeout=180)
    if not REPORT_PATH.exists():
        raise HTTPException(500, f"Scan finished (rc={result.returncode}) but no report was produced. {result.stderr[-300:]}")
    content = REPORT_PATH.read_text()
    parsed = _parse_report(content)
    _upsert_findings(parsed["findings"])
    conn = get_conn()
    conn.execute(
        "INSERT INTO security_scans (status, last_scan_at, report_path, summary_json) VALUES (?,?,?,?)",
        (parsed["status"], datetime.now().isoformat(), str(REPORT_PATH),
         json.dumps({"status": parsed["status"], "findings_parsed": len(parsed["findings"])})),
    )
    conn.commit()
    conn.close()
    return {"status": parsed["status"], "findings_parsed": len(parsed["findings"]), "score": _score()}


@router.get("/api/security/status")
def get_security_status():
    conn = get_conn()
    scan = conn.execute("SELECT * FROM security_scans ORDER BY created_at DESC LIMIT 1").fetchone()
    counts = {}
    for r in conn.execute("SELECT status, COUNT(*) c FROM security_findings GROUP BY status").fetchall():
        counts[r["status"]] = r["c"]
    conn.close()
    return {
        "status": scan["status"] if scan else "unknown",
        "last_scan": scan["last_scan_at"] if scan else None,
        "score": _score(),
        "counts": counts,
        "message": None if scan else "No scans performed yet.",
    }


@router.post("/api/security/scan")
def trigger_security_scan():
    try:
        return _run_scan()
    except HTTPException as e:
        return JSONResponse({"error": str(e.detail)}, status_code=e.status_code)
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "Scan timed out"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/security/findings")
def list_findings(status: str = ""):
    conn = get_conn()
    if status:
        rows = conn.execute("SELECT * FROM security_findings WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM security_findings ORDER BY "
                            "CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 "
                            "WHEN 'remediated' THEN 2 ELSE 3 END, updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/security/findings/{fid}/review")
def review_finding(fid: int, data: dict):
    new_status = (data or {}).get("status", "")
    if new_status not in ("pending", "approved", "ignored", "remediated"):
        raise HTTPException(400, "status must be pending|approved|ignored|remediated")
    conn = get_conn()
    cur = conn.execute("UPDATE security_findings SET status=?, updated_at=datetime('now') WHERE id=?", (new_status, fid))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    if not changed:
        raise HTTPException(404, "Finding not found")
    return {"ok": True, "status": new_status, "score": _score()}


@router.get("/api/security/report")
def get_security_report():
    if REPORT_PATH.exists():
        conn = get_conn()
        scan = conn.execute("SELECT last_scan_at FROM security_scans ORDER BY created_at DESC LIMIT 1").fetchone()
        conn.close()
        return {"report": REPORT_PATH.read_text(), "last_scan": scan["last_scan_at"] if scan else None}
    raise HTTPException(404, "No report found — run a scan first")


# ═══════════════════════════════════════════════════════════════════════════
# LIVE MONITOR — Pi-hole query logs, device profiles, ban/allow, AI analysis
# ═══════════════════════════════════════════════════════════════════════════
import pihole
from collections import defaultdict, Counter


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
    tid = orch.submit_llm(_work, desc="AI network log analysis", priority=2)   # background
    return {"task_id": tid}


# ─── LLM access monitor — who is using the node's LM Studio (:1234)? ──────────
import subprocess as _sp

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
