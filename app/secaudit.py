"""
Security audit — the hardening checks an auditor runs, done natively (no lynis).

Groups of pass/warn/fail checks across patches, SSH, accounts, network exposure,
Docker, and system. Produces a weighted score + letter grade. Everything works
as the unprivileged `user` user; checks that truly need root are marked SKIP
with the reason, not silently dropped.

Plus web_traffic(): parses the nginx-proxy-manager access logs (via docker) to
show who's hitting the public services (example.com) — the web edition of
"who connected to me".
"""
import json, logging, os, re, subprocess, time
from collections import defaultdict
import netwatch          # reuse _run, _RISKY, _svc, _is_private, _geo
from deps import get_setting, get_conn

logger = logging.getLogger("store")


def _run(cmd, timeout=12):
    return netwatch._run(cmd, timeout)


def _drun(cmd, timeout=20):
    """Run a docker command with the socket forced (the systemd context gotcha)."""
    env = dict(os.environ)
    env["DOCKER_HOST"] = get_setting("docker_host", "") or "unix:///var/run/docker.sock"
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env).stdout
    except Exception as e:
        logger.info("docker cmd %s failed: %s", cmd[:2], e)
        return ""


def _chk(title, status, detail="", fix=""):
    return {"title": title, "status": status, "detail": detail, "fix": fix}


# ── patches ──────────────────────────────────────────────────────────────────
def _patches():
    out = _run(["apt", "list", "--upgradable"], timeout=25)
    lines = [l for l in out.splitlines() if "/" in l and "upgradable" in l]
    sec = [l for l in lines if re.search(r"-security", l, re.I)]
    checks = []
    if not lines:
        checks.append(_chk("System packages up to date", "pass", "No pending upgrades."))
    else:
        checks.append(_chk("Security updates pending",
                           "fail" if sec else "warn",
                           f"{len(sec)} security update(s), {len(lines)} total upgradable.",
                           "sudo apt update && sudo apt upgrade" if sec else "sudo apt upgrade"))
    return checks


# ── SSH hardening ────────────────────────────────────────────────────────────
def _sshd():
    checks = []
    try:
        txt = open("/etc/ssh/sshd_config").read()
    except Exception:
        return [_chk("SSH config", "skip", "/etc/ssh/sshd_config not readable.")]

    def val(key, default=None):
        m = re.search(rf"^\s*{key}\s+(\S+)", txt, re.I | re.M)
        return m.group(1).lower() if m else default

    pr = val("permitrootlogin")
    checks.append(_chk("SSH root login", "pass" if pr in ("no", "prohibit-password") else "warn",
                       f"PermitRootLogin = {pr or 'default (prohibit-password)'}",
                       "Set 'PermitRootLogin no' in /etc/ssh/sshd_config" if pr in ("yes",) else ""))
    pw = val("passwordauthentication", "yes")
    checks.append(_chk("SSH password auth", "warn" if pw != "no" else "pass",
                       f"PasswordAuthentication = {pw} — key-only auth resists brute force.",
                       "Use SSH keys, then set 'PasswordAuthentication no'" if pw != "no" else ""))
    ep = val("permitemptypasswords", "no")
    checks.append(_chk("SSH empty passwords", "fail" if ep == "yes" else "pass",
                       f"PermitEmptyPasswords = {ep}"))
    x11 = val("x11forwarding", "no")
    checks.append(_chk("SSH X11 forwarding", "warn" if x11 == "yes" else "pass",
                       f"X11Forwarding = {x11} — disable if you don't tunnel GUIs.",
                       "Set 'X11Forwarding no'" if x11 == "yes" else ""))
    mat = val("maxauthtries")
    checks.append(_chk("SSH max auth tries", "pass" if (mat and int(mat) <= 4) else "info",
                       f"MaxAuthTries = {mat or 'default (6)'}"))
    return checks


# ── accounts ─────────────────────────────────────────────────────────────────
def _accounts():
    checks = []
    try:
        rows = [l.split(":") for l in open("/etc/passwd").read().splitlines() if ":" in l]
    except Exception:
        return [_chk("Accounts", "skip", "/etc/passwd not readable.")]
    shells = ("/bin/bash", "/bin/sh", "/bin/zsh", "/usr/bin/bash", "/usr/bin/zsh", "/bin/dash")
    uid0 = [r[0] for r in rows if len(r) > 2 and r[2] == "0"]
    login = [r[0] for r in rows if len(r) > 6 and r[6] in shells]
    checks.append(_chk("Superuser (UID 0) accounts", "fail" if len(uid0) > 1 else "pass",
                       f"UID 0: {', '.join(uid0)}",
                       "Only 'root' should have UID 0 — investigate extras" if len(uid0) > 1 else ""))
    checks.append(_chk("Login-capable accounts", "info",
                       f"{len(login)} accounts with a login shell: {', '.join(login[:12])}"))
    empty = [r[0] for r in rows if len(r) > 1 and r[1] == ""]
    checks.append(_chk("Empty password fields", "fail" if empty else "pass",
                       f"{', '.join(empty)}" if empty else "None (passwords in /etc/shadow)."))
    return checks


# ── network exposure ─────────────────────────────────────────────────────────
def _exposure():
    checks = []
    wan, risky = [], []
    for ln in _run(["ss", "-tulnH"]).splitlines():
        eps = netwatch._endpoints(ln)
        if not eps:
            continue
        ip, port = eps[0]
        if port == 0:
            continue
        if ip in ("0.0.0.0", "*", "::"):
            wan.append(port)
            if port in netwatch._RISKY:
                risky.append(port)
    wan = sorted(set(wan))
    risky = sorted(set(risky))
    checks.append(_chk("Services bound to all interfaces", "warn" if len(wan) > 20 else "info",
                       f"{len(wan)} ports listen on 0.0.0.0 (reachable from any interface / possibly WAN)."))
    checks.append(_chk("Sensitive ports exposed", "fail" if risky else "pass",
                       f"Risky on 0.0.0.0: {', '.join(f'{p}/{netwatch._svc(p)}' for p in risky)}" if risky else "None of the high-risk ports are on all interfaces.",
                       "Bind these to 127.0.0.1/LAN or put them behind a VPN" if risky else ""))
    return checks


# ── docker ───────────────────────────────────────────────────────────────────
def _docker():
    ids = _drun(["docker", "ps", "-q"]).split()
    if not ids:
        return [_chk("Docker", "skip", "No running containers or docker not accessible.")]
    priv, hostnet, root_pub = [], [], 0
    fmt = "{{.Name}}|{{.HostConfig.Privileged}}|{{.HostConfig.NetworkMode}}"
    for cid in ids:
        line = _drun(["docker", "inspect", "--format", fmt, cid]).strip()
        parts = line.split("|")
        if len(parts) == 3:
            name, p, net = parts
            name = name.lstrip("/")
            if p == "true":
                priv.append(name)
            if net == "host":
                hostnet.append(name)
    checks = [_chk("Running containers", "info", f"{len(ids)} containers up.")]
    checks.append(_chk("Privileged containers", "fail" if priv else "pass",
                       ", ".join(priv) if priv else "None run --privileged.",
                       "Drop --privileged; grant only needed capabilities" if priv else ""))
    checks.append(_chk("Host-network containers", "warn" if hostnet else "pass",
                       ", ".join(hostnet) if hostnet else "None share the host network namespace."))
    return checks


# ── firewall (needs root — best effort) ──────────────────────────────────────
def _firewall():
    out = _run(["nft", "list", "ruleset"])
    if "must be root" in out or not out.strip():
        return [_chk("Firewall ruleset", "skip",
                     "Rules need root to read. Confirm one is active.",
                     "Check: sudo ufw status verbose  (or)  sudo nft list ruleset")]
    rules = out.count("\n")
    return [_chk("Firewall active", "pass" if rules > 5 else "warn", f"{rules} nftables lines loaded.")]


def _ai_systems():
    try:
        import aishield
        return aishield.ai_surface()
    except Exception as e:
        return [_chk("AI systems", "skip", f"AI Shield unavailable: {e}")]


_GROUPS = [("Patches & Updates", _patches), ("SSH Hardening", _sshd),
           ("Accounts", _accounts), ("Network Exposure", _exposure),
           ("Containers", _docker), ("Firewall", _firewall),
           ("AI Systems", _ai_systems)]
_WEIGHT = {"fail": 0, "warn": 0.5, "pass": 1.0}


def audit():
    groups = []
    scored = 0.0
    total = 0
    counts = defaultdict(int)
    for name, fn in _GROUPS:
        try:
            checks = fn()
        except Exception as e:
            logger.exception("audit group %s failed", name)
            checks = [_chk(name, "skip", f"check error: {e}")]
        for c in checks:
            counts[c["status"]] += 1
            if c["status"] in _WEIGHT:
                scored += _WEIGHT[c["status"]]
                total += 1
        groups.append({"name": name, "checks": checks})
    pct = round(scored / total * 100) if total else 0
    grade = ("A" if pct >= 90 else "B" if pct >= 80 else "C" if pct >= 70
             else "D" if pct >= 55 else "F")
    return {"score": pct, "grade": grade, "counts": dict(counts), "groups": groups}


# ── web traffic (who's hitting the public services) ──────────────────────────
_NPM = "nginx-proxy-manager"
_LOG_RE = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s+-\s+(?P<status>\d+)\s+\d+\s+-\s+(?P<method>\S+)\s+\S+\s+"
    r"(?P<host>\S+)\s+\"(?P<path>[^\"]*)\"\s+\[Client (?P<ip>[^\]]+)\].*?\"(?P<ua>[^\"]*)\"")
# specific probe/exploit signatures — deliberately NOT bare /admin or /config
# (those match the store's own legit paths). Real scanner tells only.
_SCANNER_PATH = re.compile(
    r"(\.env\b|wp-admin|wp-login|xmlrpc\.php|/\.git|phpmyadmin|/actuator|/vendor/|"
    r"/\.aws|/\.ssh|/etc/passwd|eval\(|/cgi-bin|\.php7?$|/boaform|/solr/|/telescope|"
    r"/owa/|/manager/html|/hudson|/jenkins|select.*from|union.*select)", re.I)


def web_traffic(limit=4000):
    raw = _drun(["docker", "exec", _NPM, "sh", "-c",
                "cat /data/logs/*access.log 2>/dev/null | tail -n %d" % limit], timeout=20)
    if not raw.strip():
        return {"available": False, "note": "No nginx-proxy-manager access logs readable.",
                "visitors": [], "vhosts": [], "suspicious": [], "total": 0}
    by_ip = defaultdict(lambda: {"ip": "", "hits": 0, "statuses": defaultdict(int),
                                 "hosts": set(), "ua": "", "suspicious": 0, "last": ""})
    by_host = defaultdict(int)
    suspicious = []
    total = 0
    for ln in raw.splitlines():
        m = _LOG_RE.search(ln)
        if not m:
            continue
        total += 1
        ip = m.group("ip")
        st = m.group("status")
        host = m.group("host")
        path = m.group("path")
        rec = by_ip[ip]
        rec["ip"] = ip
        rec["hits"] += 1
        rec["statuses"][st[0] + "xx"] += 1
        rec["hosts"].add(host)
        rec["ua"] = m.group("ua")[:80]
        rec["last"] = m.group("ts")
        by_host[host] += 1
        is_probe = bool(_SCANNER_PATH.search(path))
        if is_probe or st in ("401", "403"):
            rec["suspicious"] += 1
            if is_probe and len(suspicious) < 80:   # only real probes in the list; 401/403 just counts
                suspicious.append({"ip": ip, "status": st, "host": host, "path": path[:80],
                                   "ua": m.group("ua")[:60], "ts": m.group("ts")})
    visitors = []
    for rec in by_ip.values():
        rec["statuses"] = dict(rec["statuses"])
        rec["hosts"] = sorted(rec["hosts"])[:6]
        visitors.append(rec)
    visitors.sort(key=lambda r: -r["hits"])
    # geo-enrich the top talkers (external only)
    conn = netwatch.get_conn()
    try:
        for rec in visitors[:30]:
            if not netwatch._is_private(rec["ip"]):
                rec["geo"] = netwatch._geo(conn, rec["ip"])
    finally:
        conn.close()
    return {
        "available": True,
        "total": total,
        "unique_visitors": len(visitors),
        "visitors": visitors[:60],
        "vhosts": sorted(([{"host": h, "hits": n} for h, n in by_host.items()]),
                         key=lambda x: -x["hits"])[:20],
        "suspicious": suspicious,
        "cloudflare_note": any(v["ip"].startswith(("162.159.", "172.6", "172.7", "104.")) for v in visitors[:10]),
    }


# ── fail2ban status (reader — lights up once installed) ──────────────────────
def fail2ban_status():
    out = _run(["fail2ban-client", "status"], timeout=8)
    if not out.strip() or "not found" in out.lower():
        return {"installed": False,
                "hint": "Not installed. `sudo apt install fail2ban` then it auto-bans SSH brute-force. "
                        "This panel will show its jails + banned IPs once it's running."}
    jails = []
    m = re.search(r"Jail list:\s*(.+)", out)
    for j in (m.group(1).split(",") if m else []):
        j = j.strip()
        if not j:
            continue
        js = _run(["fail2ban-client", "status", j], timeout=8)
        banned = re.search(r"Banned IP list:\s*(.*)", js)
        total = re.search(r"Total banned:\s*(\d+)", js)
        jails.append({"name": j, "banned": (banned.group(1).split() if banned else []),
                      "total_banned": int(total.group(1)) if total else 0})
    return {"installed": True, "jails": jails,
            "total_banned": sum(x["total_banned"] for x in jails)}


# ── threats: rank attackers + give a ready-to-run block command ──────────────
def threats():
    conn = get_conn()
    try:
        out = []
        # SSH brute-force — real source IPs, directly bannable
        for r in netwatch._ssh_attempts():
            if r["failed"] < 3 and not r["accepted"]:
                continue
            g = netwatch._geo(conn, r["ip"])
            out.append({
                "ip": r["ip"], "type": "ssh-breach" if r["accepted"] else "ssh-bruteforce",
                "severity": "critical" if r["accepted"] else "high" if r["failed"] > 20 else "medium",
                "detail": f"{r['attempts']} SSH tries, {r['failed']} failed"
                          + (f", {r['accepted']} ACCEPTED" if r["accepted"] else "")
                          + (f" (users: {', '.join(r['users'][:5])})" if r["users"] else ""),
                "geo": g, "bannable": True,
                "block": f"sudo ufw deny from {r['ip']}"}
            )
        # Web scanners — behind Cloudflare, so the IP is a CF edge (can't IP-ban)
        wt = web_traffic()
        prober = defaultdict(lambda: {"n": 0, "paths": set()})
        for s in wt.get("suspicious", []):
            prober[s["ip"]]["n"] += 1
            prober[s["ip"]]["paths"].add(s["path"][:40])
        cf = wt.get("cloudflare_note")
        for ip, v in sorted(prober.items(), key=lambda kv: -kv[1]["n"])[:15]:
            if v["n"] < 2:
                continue
            out.append({
                "ip": ip, "type": "web-scanner", "severity": "medium",
                "detail": f"{v['n']} probe requests: {', '.join(list(v['paths'])[:4])}",
                "geo": netwatch._geo(conn, ip) if not netwatch._is_private(ip) else None,
                "bannable": not cf,
                "block": ("Behind Cloudflare — block at the CF WAF / firewall rules, not by IP (this is a CF edge)"
                          if cf else f"sudo ufw deny from {ip}")}
            )
        sev = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        out.sort(key=lambda t: sev.get(t["severity"], 9))
        return {"threats": out, "count": len(out),
                "fail2ban": fail2ban_status()}
    finally:
        conn.close()


# ── snapshots + regression alerts (for the scheduled audit) ──────────────────
def _ensure(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS security_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT (datetime('now')),
        score INTEGER, grade TEXT, data TEXT);
    CREATE TABLE IF NOT EXISTS security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT (datetime('now')),
        severity TEXT, text TEXT, seen INTEGER DEFAULT 0);
    """)
    conn.commit()


def _facts():
    """The comparable facts a nightly audit watches for regressions."""
    a = audit()
    c = netwatch.connections(enrich=False)
    exposed = {x["port"] for x in c["listening"]}
    fails = [ck["title"] for g in a["groups"] for ck in g["checks"] if ck["status"] == "fail"]
    breaches = sum(1 for r in c["ssh"] if r["accepted"])
    return {"score": a["score"], "grade": a["grade"], "fails": sorted(fails),
            "exposed": sorted(exposed), "ssh_breaches": breaches,
            "inbound": c["summary"]["inbound"]}


def run_scheduled_audit():
    """Snapshot + diff vs the last snapshot; raise events (and God-Console notes)
    on regressions. Called by the scheduler."""
    conn = get_conn()
    try:
        _ensure(conn)
        cur = _facts()
        prev_row = conn.execute("SELECT data FROM security_snapshots ORDER BY id DESC LIMIT 1").fetchone()
        alerts = []
        if prev_row:
            try:
                prev = json.loads(prev_row["data"])
            except Exception:
                prev = {}
            new_fails = set(cur["fails"]) - set(prev.get("fails", []))
            for f in new_fails:
                alerts.append(("high", f"New audit failure: {f}"))
            new_ports = set(cur["exposed"]) - set(prev.get("exposed", []))
            risky_new = [p for p in new_ports if p in netwatch._RISKY]
            if risky_new:
                alerts.append(("high", f"New risky port(s) exposed: {', '.join(f'{p}/{netwatch._svc(p)}' for p in risky_new)}"))
            if cur["ssh_breaches"] > prev.get("ssh_breaches", 0):
                alerts.append(("critical", "New external SSH login accepted — verify it was you."))
            if cur["score"] < prev.get("score", 100) - 10:
                alerts.append(("medium", f"Security score dropped {prev.get('score')} → {cur['score']}."))
        conn.execute("INSERT INTO security_snapshots (score,grade,data) VALUES (?,?,?)",
                     (cur["score"], cur["grade"], json.dumps(cur)))
        for sev, text in alerts:
            conn.execute("INSERT INTO security_events (severity,text) VALUES (?,?)", (sev, text))
        conn.commit()
        # surface the loud ones in the Company's God Console board
        if alerts:
            try:
                import world_ops as wo
                for sev, text in alerts:
                    if sev in ("high", "critical"):
                        wo.note(f"🛡️ Security: {text}", kind="warning", from_agent="Security")
            except Exception:
                pass
        return {"score": cur["score"], "grade": cur["grade"], "alerts": len(alerts)}
    finally:
        conn.close()


def events(limit=40):
    conn = get_conn()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT * FROM security_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        hist = conn.execute("SELECT created_at,score,grade FROM security_snapshots ORDER BY id DESC LIMIT 30").fetchall()
        return {"events": [dict(r) for r in rows], "history": [dict(r) for r in hist]}
    finally:
        conn.close()
