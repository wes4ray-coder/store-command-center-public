"""
Live network connection intelligence — who/what/where is connecting, in & out.

The Pi-hole tab shows what LAN devices *query* (DNS). This answers the other
question: who from OUTSIDE connected to this server, what service they hit, and
where they are — plus who *tried* and got blocked. Reads live from `ss`,
`journalctl -k` (firewall blocks), and `last` (logins); enriches external IPs
with reverse-DNS + a cached geo lookup.

Runs on the box itself (server @ 127.0.0.1). Degrades gracefully when a
source needs perms it doesn't have.
"""
import ipaddress, logging, re, socket, subprocess, time
import httpx
from deps import get_conn

logger = logging.getLogger("store")

PORT_SVC = {
    22: "SSH", 2022: "SSH-alt", 25: "SMTP", 465: "SMTPS", 587: "SMTP-submit",
    110: "POP3", 995: "POP3S", 143: "IMAP", 993: "IMAPS", 4190: "Sieve",
    53: "DNS", 80: "HTTP", 81: "HTTP-alt", 443: "HTTPS", 88: "Auth",
    631: "CUPS-print", 3389: "RDP", 3478: "STUN/TURN", 3306: "MySQL",
    5432: "Postgres", 6379: "Redis", 8787: "Store", 8188: "ComfyUI",
    1234: "LM-Studio", 2121: "FTP", 3033: "web-app", 8090: "WP-MCP",
}


# ports that are notable to expose to the internet (remote access / data / mail)
_RISKY = {22, 2022, 3389, 3306, 5432, 6379, 13306, 25, 143, 110, 21, 2121, 23}


def _svc(port):
    return PORT_SVC.get(port, f"port {port}")


def _is_private(ip):
    try:
        a = ipaddress.ip_address(ip.strip("[]"))
        return a.is_private or a.is_loopback or a.is_link_local or a.is_multicast
    except Exception:
        return True   # unparseable → treat as non-external (don't leak)


def _run(cmd, timeout=8):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception as e:
        logger.info("netwatch cmd %s failed: %s", cmd[0], e)
        return ""


_EP = re.compile(r"(\[[0-9a-fA-F:]+\]|[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|\*):(\d+|\*)")


def _endpoints(line):
    """Extract (ip, port) endpoints from an ss line, in order."""
    out = []
    for m in _EP.finditer(line):
        ip = m.group(1).strip("[]")
        port = m.group(2)
        out.append((ip, int(port) if port.isdigit() else 0))
    return out


def _listening():
    """Set of local ports this host accepts inbound on."""
    ports = {}
    for ln in _run(["ss", "-tulnH"]).splitlines():
        eps = _endpoints(ln)
        if not eps:
            continue
        # the local listen endpoint is the first with a numeric port
        for ip, port in eps:
            if port and port != 0:
                ports[port] = _svc(port)
                break
    return ports


# ── geo cache (external lookups via ip-api.com; cached in the settings table) ─
def _geo_cache_get(conn, ip):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (f"_geo_{ip}",)).fetchone()
    if r and r["value"]:
        import json
        try:
            return json.loads(r["value"])
        except Exception:
            return None
    return None


def _geo_cache_put(conn, ip, data):
    import json
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (f"_geo_{ip}", json.dumps(data)))
    conn.commit()


def _geo(conn, ip):
    cached = _geo_cache_get(conn, ip)
    if cached is not None:
        return cached
    data = {"country": "", "city": "", "org": "", "isp": ""}
    try:
        r = httpx.get(f"http://ip-api.com/json/{ip}",
                      params={"fields": "status,country,city,org,isp,as"}, timeout=6)
        j = r.json()
        if j.get("status") == "success":
            data = {"country": j.get("country", ""), "city": j.get("city", ""),
                    "org": j.get("org") or j.get("as", ""), "isp": j.get("isp", "")}
    except Exception:
        pass
    _geo_cache_put(conn, ip, data)
    return data


def _rdns(ip):
    try:
        socket.setdefaulttimeout(1.5)
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


# ── firewall blocks + SSH auth (who tried / who got in, from where) ───────────
def _firewall_blocks():
    out = []
    kern = _run(["journalctl", "-k", "--since", "24 hours ago", "--no-pager"], timeout=10)
    for ln in kern.splitlines():
        if "UFW BLOCK" not in ln or "SRC=" not in ln:
            continue
        src = re.search(r"SRC=(\S+)", ln)
        dpt = re.search(r"DPT=(\d+)", ln)
        proto = re.search(r"PROTO=(\S+)", ln)
        ts = re.match(r"(\w+\s+\d+\s+[\d:]+)", ln)
        if src and not _is_private(src.group(1)):
            out.append({"src": src.group(1), "port": int(dpt.group(1)) if dpt else 0,
                        "service": _svc(int(dpt.group(1))) if dpt else "",
                        "proto": proto.group(1) if proto else "", "when": ts.group(1) if ts else ""})
    return out


def _ssh_attempts():
    """Aggregate SSH auth events by source IP — the classic 'who's knocking'."""
    agg = {}
    log = _run(["journalctl", "_COMM=sshd", "--since", "7 days ago", "--no-pager", "-o", "short-iso"], timeout=14)
    for ln in log.splitlines():
        m = re.search(r"from (\d+\.\d+\.\d+\.\d+)", ln)
        if not m:
            continue
        ip = m.group(1)
        if _is_private(ip):
            continue
        result = ("accepted" if "Accepted" in ln else
                  "failed" if ("Failed" in ln or "authentication failure" in ln) else
                  "invalid" if "Invalid user" in ln or "invalid user" in ln else
                  "probe")
        um = re.search(r"(?:Accepted \w+ for|Failed \w+ for|Invalid user)\s+(?:invalid user\s+)?(\S+?)\s+from", ln)
        user = um.group(1) if um else ""
        ts = re.match(r"(\S+)", ln)
        rec = agg.get(ip)
        if not rec:
            rec = {"ip": ip, "attempts": 0, "accepted": 0, "failed": 0, "users": set(), "last": ""}
            agg[ip] = rec
        rec["attempts"] += 1
        if result == "accepted":
            rec["accepted"] += 1
        elif result in ("failed", "invalid"):
            rec["failed"] += 1
        if user and user not in ("from",):
            rec["users"].add(user[:24])
        if ts:
            rec["last"] = ts.group(1)
    out = list(agg.values())
    for r in out:
        r["users"] = sorted(r["users"])[:8]
        r["result"] = "breached" if r["accepted"] else "blocked"   # failed-only = never got in
    out.sort(key=lambda r: (-r["accepted"], -r["attempts"]))
    return out


# ── the main report ──────────────────────────────────────────────────────────
def connections(enrich=True):
    conn = get_conn()
    try:
        listening = _listening()
        est = _run(["ss", "-tunH", "state", "established"])
        agg = {}   # peer_ip -> record
        lan_count = 0
        for ln in est.splitlines():
            eps = _endpoints(ln)
            if len(eps) < 2:
                continue
            (lip, lport), (pip, pport) = eps[-2], eps[-1]
            if _is_private(pip):
                lan_count += 1
                continue
            inbound = lport in listening
            rec = agg.get(pip)
            if not rec:
                rec = {"ip": pip, "count": 0, "in": 0, "out": 0, "ports": {}, "rdns": None, "geo": None}
                agg[pip] = rec
            rec["count"] += 1
            if inbound:
                rec["in"] += 1
                rec["ports"][lport] = _svc(lport)          # the service they reached
            else:
                rec["out"] += 1
                rec["ports"][pport] = _svc(pport)          # the remote service we reached
        ext = list(agg.values())
        # enrich the external peers (cheap: rDNS local, geo cached)
        if enrich:
            for rec in sorted(ext, key=lambda r: -r["count"])[:40]:
                rec["rdns"] = _rdns(rec["ip"])
                rec["geo"] = _geo(conn, rec["ip"])
        for rec in ext:
            rec["direction"] = ("in" if rec["in"] and not rec["out"]
                                else "out" if rec["out"] and not rec["in"] else "both")
            rec["services"] = sorted(set(rec["ports"].values()))
            rec.pop("ports", None)
        ext.sort(key=lambda r: (-(r["in"]), -r["count"]))   # inbound first (more noteworthy)

        blocked = _firewall_blocks()
        ssh = _ssh_attempts()
        if enrich:
            for r in blocked[:20]:
                r["geo"] = _geo(conn, r["src"])
            for r in ssh[:30]:
                r["geo"] = _geo(conn, r["ip"])
        breached = [r for r in ssh if r["accepted"]]
        return {
            "external": ext,
            "lan_established": lan_count,
            "listening": [{"port": p, "service": s, "risky": p in _RISKY} for p, s in sorted(listening.items())],
            "blocked": blocked,
            "ssh": ssh,
            "firewall_logging": bool(blocked),
            "summary": {
                "external_total": len(ext),
                "inbound": sum(1 for r in ext if r["in"]),
                "outbound": sum(1 for r in ext if r["out"] and not r["in"]),
                "blocked_24h": len(blocked),
                "ssh_sources": len(ssh),
                "ssh_breached": len(breached),
                "exposed_services": len(listening),
            },
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    finally:
        conn.close()
