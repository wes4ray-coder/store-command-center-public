"""
Network Guardian — fingerprint + name every device, understand its traffic,
flag bad actors, and surgically kill the bad domains without breaking the
network or anything needed.

Principles the user set:
  • Auto-identify unnamed devices (MAC vendor + behaviour) and give them a name.
  • Trusted things are never flagged: local infra, your own services, and the
    functional traffic a device legitimately needs (DNS, NTP, OS updates, the
    streaming apps you use).
  • Bad actors = ad/tracking/ACR domains + runaway retry loops. Block THOSE
    (domain-level, via Pi-hole — reversible), never the device or the network.
  • Everything is logged and reversible; auto-remediation is opt-in.
"""
import json, logging, os, re, subprocess, time
from collections import defaultdict
from deps import get_conn, get_setting

logger = logging.getLogger("store")

# Pi-hole's HTTP API needs auth we don't have; docker exec is the reliable path
# (same as the audit/web-traffic tools). DOCKER_HOST forced for the systemd ctx.
_PIHOLE = "pihole"


def _drun(cmd, timeout=25):
    env = dict(os.environ)
    env["DOCKER_HOST"] = get_setting("docker_host", "") or "unix:///var/run/docker.sock"
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except Exception as e:
        logger.info("netguard docker cmd failed: %s", e)
        class _R:  # noqa
            stdout = ""; stderr = str(e); returncode = 1
        return _R()


_QLINE = re.compile(r"query\[[A-Z]+\]\s+(\S+)\s+from\s+(\d+\.\d+\.\d+\.\d+)")


def _read_queries(lines=40000):
    """Fresh per-device DNS activity straight from the Pi-hole query log."""
    r = _drun(["docker", "exec", _PIHOLE, "sh", "-c",
               "tail -n %d /var/log/pihole/pihole.log 2>/dev/null" % lines], timeout=25)
    out = []
    for ln in (r.stdout or "").splitlines():
        m = _QLINE.search(ln)
        if m:
            out.append((m.group(2), m.group(1).lower().rstrip(".")))   # (ip, domain)
    return out


def _pihole_deny(domains, remove=False):
    if not domains:
        return True
    cmd = ["docker", "exec", _PIHOLE, "pihole", "deny"] + (["-d"] if remove else []) + list(domains)
    r = _drun(cmd, timeout=30)
    return r.returncode == 0

# ── MAC OUI → vendor (curated common consumer prefixes; behaviour fills gaps) ─
OUI = {
    "18:58:80": "LG Electronics", "00:e0:91": "LG", "a8:23:fe": "LG", "cc:2d:8c": "LG",
    "3c:cd:93": "LG", "b8:1d:aa": "LG", "10:f1:f2": "LG",
    "f8:1f:32": "Sichuan AI-Link/IoT", "fc:a1:83": "Amazon", "44:65:0d": "Amazon",
    "68:37:e9": "Amazon", "50:dc:e7": "Amazon", "ac:63:be": "Amazon",
    "b0:a7:37": "Roku", "cc:6d:a0": "Roku", "d8:31:34": "Roku", "dc:3a:5e": "Roku",
    "bc:d1:1f": "Samsung", "5c:49:7d": "Samsung", "8c:79:f5": "Samsung", "e8:b1:fc": "Intel/Wi-Fi",
    "f8:e6:1a": "Samsung", "34:14:5f": "Samsung", "78:bd:bc": "Samsung",
    "3c:5a:b4": "Google", "f4:f5:d8": "Google", "1c:53:f9": "Google", "d4:f5:47": "Google",
    "a4:83:e7": "Apple", "f0:18:98": "Apple", "ac:bc:32": "Apple", "dc:2b:2a": "Apple",
    "e4:c3:2a": "Router/Gateway", "b8:8c:29": "Wi-Fi device", "24:32:ae": "Wi-Fi device",
    "38:a5:c9": "Wi-Fi device", "f8:1f:32x": "", "70:85:c2": "ASRock/PC", "b8:27:eb": "Raspberry Pi",
    "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi", "d8:3a:dd": "Raspberry Pi",
    "18:c0:4d": "Espressif/IoT", "24:6f:28": "Espressif/IoT", "a4:cf:12": "Espressif/IoT",
    "50:02:91": "Espressif/IoT", "cc:50:e3": "Espressif/IoT",
}


def oui_vendor(mac):
    if not mac:
        return ""
    return OUI.get(mac.lower()[:8], "")


# ── domain intelligence ──────────────────────────────────────────────────────
def _rx(*pats):
    return re.compile("|".join(pats), re.I)


LOCAL_RX = _rx(r"\.lan$", r"\.local$", r"\.internal$", r"in-addr\.arpa$", r"\.arpa$")
FUNCTIONAL_RX = _rx(
    r"netflix\.com", r"nflx", r"youtube", r"googlevideo", r"ytimg", r"ggpht",
    r"amazonvideo\.com", r"aiv-", r"primevideo", r"(^|\.)hulu", r"(^|\.)disney", r"spotify",
    r"connectivitycheck", r"captiveportal", r"connectivity-check", r"gstatic\.com$",
    r"(^|\.)ntp", r"time\.(android|apple|windows|google|nist)", r"pool\.ntp",
    r"windowsupdate", r"update\.microsoft", r"swcdn\.apple", r"gdmf\.apple", r"mesu\.apple",
    r"archive\.ubuntu", r"security\.ubuntu", r"ngfts\.lge\.com", r"aic-ngfts\.lge\.com", r"lgtvsdp\.com",
    r"3gppnetwork\.org", r"epdg", r"account\.t-mobile", r"msg\.t-mobile",
    r"meethue\.com", r"akamai", r"cloudflare", r"fastly", r"cloudfront",
)
ADS_RX = _rx(
    r"googlesyndication", r"doubleclick", r"googleadservices", r"adservice",
    r"adsystem", r"amazon-adsystem", r"lgsmartad", r"smartclip", r"adnxs",
    r"pagead", r"googleads", r"(^|\.)ads?\.", r"advertising", r"ueiwsp\.com",
)
TRACKING_RX = _rx(
    r"lgtvcommon\.com", r"cdpbeacon", r"acr\.", r"samsungacr", r"(^|\.)analytics",
    r"telemetry", r"crashlytics", r"app-measurement", r"mixpanel", r"segment\.io",
    r"datadoghq", r"sentry", r"appsflyer", r"branch\.io", r"scorecardresearch",
    r"doubleverify", r"nielsen", r"cdplauncher", r"cdpsvc", r"lgad", r"rlog",
)


def categorize(domain):
    d = (domain or "").lower().rstrip(".")
    if not d:
        return "unknown"
    if LOCAL_RX.search(d):
        return "local"
    if FUNCTIONAL_RX.search(d):
        return "functional"
    if ADS_RX.search(d):
        return "ads"
    if TRACKING_RX.search(d):
        return "tracking"
    return "unknown"


# domains/patterns that must NEVER be blocked no matter what
def _never_block(domain):
    c = categorize(domain)
    return c in ("local", "functional")


def _parent(domain):
    parts = (domain or "").rstrip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


# domains that are PURE ad/tracking networks — safe to block at the parent level
# (nothing legitimate lives there). Everything else is blocked as the EXACT
# subdomain seen, so we never nuke a mixed/legit parent (e.g. mozilla.org).
TRACKER_PARENTS = {
    "doubleclick.net", "googlesyndication.com", "googleadservices.com", "google-analytics.com",
    "adnxs.com", "scorecardresearch.com", "lgsmartad.com", "lgtvcommon.com", "ueiwsp.com",
    "amazon-adsystem.com", "app-measurement.com", "crashlytics.com", "appsflyer.com",
    "branch.io", "doubleverify.com", "nielsen.com", "segment.io", "mixpanel.com",
    "smartclip.net", "adsafeprotected.com", "moatads.com", "2mdn.net", "serving-sys.com",
    "flurry.com", "chartboost.com", "unity3d.com", "applovin.com", "smaato.net",
}


def _blockable(domain):
    """Pure-tracker domain → block the parent; anything else → block only the
    exact subdomain (so a legit parent like mozilla.org is never blocked)."""
    p = _parent(domain)
    return p if p in TRACKER_PARENTS else domain


def _is_loopback(ip):
    return ip in ("127.0.0.1", "::1", "0.0.0.0") or ip.startswith("127.")


# ── device classification + auto-name ────────────────────────────────────────
def classify_device(vendor, domains, mac, ip):
    dl = " ".join(domains).lower()
    v = vendor or ""
    def has(*ks):
        return any(k in dl for k in ks)
    if has("lgtvsdp", "lgtvcommon", "ngfts.lge", "lge.com"):
        return "LG webOS TV", "📺"
    if has("samsungcloudsolution", "samsungotn", "samsungacr", "samsungtv"):
        return "Samsung TV", "📺"
    if has("roku"):
        return "Roku", "📺"
    if has("aiv-", "atv-ps", "avods", "ftv"):
        return "Amazon Fire TV", "📺"
    if has("3gppnetwork.org", "epdg", "t-mobile.com", "vzw", "att.com") and has("android", "googleapis"):
        return f"Android Phone ({'T-Mobile' if 't-mobile' in dl else 'cellular'})", "📱"
    if has("android.clients.google", "android.googleapis", "gvt1", "supl.google"):
        return "Android Phone/Tablet", "📱"
    if has("icloud", "apple.com", "push.apple", "gsp-ssl") or v == "Apple":
        return "Apple device", "🍎"
    if has("windowsupdate", "microsoft.com", "msftconnecttest", "steamserver", "discord", "nvidia"):
        return "Windows/Gaming PC", "💻"
    if has("ubuntu.com", "connectivity-check.ubuntu"):
        return "Linux PC", "🐧"
    if has("meethue", "tuya", "smartlife", "espressif", "shelly", "sonoff") or v == "Espressif/IoT":
        return "Smart-home / IoT", "💡"
    if v == "Raspberry Pi":
        return "Raspberry Pi", "🍓"
    if v:
        return f"{v} device", "📶"
    return "Unidentified device", "❓"


# ── persistence (names + action log) ─────────────────────────────────────────
def _ensure(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS net_devices (
        mac TEXT PRIMARY KEY, ip TEXT, name TEXT, vendor TEXT, kind TEXT, icon TEXT,
        user_named INTEGER DEFAULT 0, first_seen TEXT DEFAULT (datetime('now')),
        last_seen TEXT DEFAULT (datetime('now')));
    CREATE TABLE IF NOT EXISTS net_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT (datetime('now')),
        action TEXT, domain TEXT, reason TEXT, device TEXT, auto INTEGER DEFAULT 0);
    """)
    conn.commit()


def _neigh_macs():
    out = {}
    try:
        r = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=6).stdout
        for ln in r.splitlines():
            m = re.match(r"(\d+\.\d+\.\d+\.\d+).*?lladdr ([0-9a-f:]{17})", ln)
            if m:
                out[m.group(1)] = m.group(2)
    except Exception:
        pass
    return out


def set_name(mac, name):
    conn = get_conn()
    try:
        _ensure(conn)
        conn.execute("INSERT INTO net_devices (mac,name,user_named) VALUES (?,?,1) "
                     "ON CONFLICT(mac) DO UPDATE SET name=excluded.name, user_named=1", (mac, name))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ── the analysis ─────────────────────────────────────────────────────────────
def analyze(length=6000):
    conn = get_conn()
    try:
        _ensure(conn)
        queries = _read_queries()
        if not queries:
            return {"available": False, "note": "No Pi-hole query log readable (docker).", "devices": []}
        macs = _neigh_macs()
        blocked_now = {r["domain"] for r in
                       conn.execute("SELECT DISTINCT domain FROM net_actions WHERE action='block'")}

        by_ip = defaultdict(lambda: {"domains": defaultdict(int), "total": 0})
        for ip, dom in queries:
            if not ip or not dom or _is_loopback(ip):     # loopback = the server's own resolver, not a device
                continue
            by_ip[ip]["domains"][dom] += 1
            by_ip[ip]["total"] += 1

        user_named = {r["mac"]: r["name"] for r in conn.execute("SELECT mac,name FROM net_devices WHERE user_named=1")}
        devices = []
        for ip, agg in by_ip.items():
            doms = agg["domains"]
            mac = macs.get(ip, "")
            vendor = oui_vendor(mac)
            cats = defaultdict(int)
            bad = defaultdict(int)          # parent tracker/ad domain -> hits
            loops = []
            for d, n in doms.items():
                c = categorize(d)
                cats[c] += n
                if c in ("ads", "tracking"):
                    bad[_blockable(d)] += n
                if n >= 800 and c not in ("local", "functional"):
                    loops.append({"domain": d, "hits": n})
            auto_name, icon = classify_device(vendor, list(doms.keys()), mac, ip)
            name = user_named.get(mac) or auto_name
            total = agg["total"] or 1
            noise = cats["ads"] + cats["tracking"]
            flags = []
            if noise >= 40 or (noise / total) > 0.15:
                flags.append("heavy tracking/ads")
            if loops:
                flags.append("runaway retry loop")
            if auto_name == "Unidentified device" and not mac:
                flags.append("unknown device")
            recommend = [{"domain": p, "hits": h, "cat": categorize(p) if categorize(p) != "unknown" else "tracking"}
                         for p, h in sorted(bad.items(), key=lambda kv: -kv[1])
                         if p not in blocked_now and not _never_block(p)]
            # if a device tracks heavily but we've already blocked all of it, say so
            if not recommend and "heavy tracking/ads" in flags:
                flags = [f for f in flags if f != "heavy tracking/ads"] + ["✓ trackers blocked"]
            devices.append({
                "ip": ip, "mac": mac, "vendor": vendor, "name": name, "auto_name": auto_name,
                "icon": icon, "user_named": mac in user_named, "total": agg["total"],
                "categories": dict(cats), "flags": flags, "loops": loops[:5],
                "recommend": recommend[:15], "top": sorted(doms.items(), key=lambda kv: -kv[1])[:8],
            })
            # remember the device
            conn.execute("INSERT INTO net_devices (mac,ip,name,vendor,kind,icon,last_seen) "
                         "VALUES (?,?,?,?,?,?,datetime('now')) ON CONFLICT(mac) DO UPDATE SET "
                         "ip=excluded.ip, vendor=excluded.vendor, kind=excluded.kind, "
                         "icon=excluded.icon, last_seen=datetime('now')",
                         (mac or ip, ip, auto_name, vendor, auto_name, icon))
        conn.commit()
        devices.sort(key=lambda d: (-len(d["flags"]), -d["total"]))
        allblocks = [{"parent": p, "hits": h} for d in devices for p, h in
                     [(r["domain"], r["hits"]) for r in d["recommend"]]]
        return {"available": True, "devices": devices, "blocked_count": len(blocked_now),
                "recommend_total": len({b["parent"] for b in allblocks})}
    finally:
        conn.close()


# ── remediation (surgical + reversible + logged) ─────────────────────────────
def remediate(domains, auto=False, device=""):
    conn = get_conn()
    applied, skipped = [], []
    try:
        _ensure(conn)
        clean = [(d or "").strip().lower() for d in domains]
        to_block = [d for d in clean if d and not _never_block(d)]
        skipped = [d for d in clean if d and _never_block(d)]
        if to_block and _pihole_deny(to_block):
            for dom in to_block:
                conn.execute("INSERT INTO net_actions (action,domain,reason,device,auto) "
                             "VALUES ('block',?,?,?,?)", (dom, "ad/tracking", device, 1 if auto else 0))
                applied.append(dom)
        elif to_block:
            skipped += to_block
        conn.commit()
        if applied:
            try:
                import world_ops as wo
                wo.note(f"🛡️ Guardian blocked {len(applied)} tracker/ad domain(s)"
                        + (f" from {device}" if device else "") + " — network + services untouched.",
                        kind="info", from_agent="Guardian")
            except Exception:
                pass
        return {"blocked": applied, "skipped": skipped}
    finally:
        conn.close()


def unblock(domain):
    conn = get_conn()
    try:
        _ensure(conn)
        ok = _pihole_deny([domain], remove=True)
        conn.execute("INSERT INTO net_actions (action,domain,reason) VALUES ('unblock',?,'manual')", (domain,))
        conn.commit()
        return {"ok": bool(ok)}
    finally:
        conn.close()


def actions(limit=50):
    conn = get_conn()
    try:
        _ensure(conn)
        rows = conn.execute("SELECT * FROM net_actions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return {"actions": [dict(r) for r in rows]}
    finally:
        conn.close()


# ── guardian tick (scheduled): auto-block clear trackers, report ─────────────
def guardian_tick():
    """Block only high-confidence ad/tracking parents (never functional/local),
    respecting the allowlist. Opt-in via setting."""
    a = analyze()
    if not a.get("available"):
        return {"skipped": a.get("note")}
    # gather high-confidence bad parents seen enough to matter
    bad = defaultdict(int)
    for d in a["devices"]:
        for r in d["recommend"]:
            bad[r["domain"]] += r["hits"]
    targets = [p for p, h in bad.items() if h >= 20 and not _never_block(p)]
    if not targets:
        return {"blocked": 0}
    res = remediate(targets, auto=True, device="nightly")
    return {"blocked": len(res["blocked"])}
