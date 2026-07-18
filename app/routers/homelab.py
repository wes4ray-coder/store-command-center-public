"""Services / Homelab hub — one place for all your Docker services + *arr apps.

Auto-discovers Docker containers, HIDES helper/infra containers (databases, redis,
nextcloud-aio sidecars, VPN companions) by default, groups the rest by category with
clickable host:port links and a running/stopped dot, and enriches *arr apps
(sonarr/radarr/lidarr/readarr/prowlarr) with version + queue + health warnings via
their v3 API. Per-container overrides (hide/show, rename, category, URL, API key) and
manual (non-Docker) service entries live in the DB.
"""
import json
import os
import re
import socket
import subprocess
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import *   # get_conn, get_setting, logger

router = APIRouter()


# ── schema (kept here to stay decoupled from the concurrently-edited db.py) ──
def _ensure_schema():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS homelab_overrides (
        container    TEXT PRIMARY KEY,
        hidden       INTEGER DEFAULT 0,
        display_name TEXT,
        category     TEXT,
        url_override TEXT,
        arr_type     TEXT,
        api_key      TEXT,
        sort_order   INTEGER DEFAULT 0,
        updated_at   TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS homelab_manual (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        url        TEXT,
        category   TEXT,
        arr_type   TEXT,
        api_key    TEXT,
        health_url TEXT,
        notes      TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()

_ensure_schema()


# ── helpers ──────────────────────────────────────────────────────────────────
def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def _host() -> str:
    return get_setting("homelab_host", "") or _lan_ip()


_HELPER_RE = re.compile(
    r"(^|[-_/])(db|database|mariadb|mysql|postgres(ql)?|redis|valkey|memcached|mongo(db)?)([-_:]|$)", re.I)

# name/image → (category, arr_type). arr_type set = enrich via *arr v3 API.
_ARR = {"sonarr": "sonarr", "radarr": "radarr", "lidarr": "lidarr",
        "readarr": "readarr", "prowlarr": "prowlarr"}
_CATEGORY_HINTS = [
    (("sonarr", "radarr", "lidarr", "readarr", "prowlarr", "bazarr", "jackett"), "Media Management"),
    (("jellyfin", "plex", "emby", "jellyseerr", "overseerr", "tautulli", "ersatztv", "wizarr", "seerr"), "Media"),
    (("qbittorrent", "transmission", "sabnzbd", "nzbget", "deluge", "yt-dlp", "youtubedownloader", "gluetun"), "Downloads"),
    (("nextcloud", "sftpgo", "filebrowser", "syncthing"), "Files"),
    (("pihole", "nginx-proxy-manager", "searxng", "adguard", "traefik", "wireguard"), "Network"),
    (("portainer", "tdarr", "watchtower", "dozzle", "uptime"), "Tools"),
    (("local-ai", "ollama", "comfyui", "automatic1111"), "AI"),
    (("wordpress", "woocommerce"), "Store"),
]


def _is_helper(name: str, image: str) -> bool:
    n, img = name.lower(), image.lower()
    if name.startswith("nextcloud-aio-") and "mastercontainer" not in name:
        return True
    if "gluetun" in n:
        return True
    if n.endswith("-node"):
        return True
    if _HELPER_RE.search(n) or _HELPER_RE.search(img):
        return True
    return False


def _guess_category(name: str, image: str) -> str:
    hay = (name + " " + image).lower()
    for keys, cat in _CATEGORY_HINTS:
        if any(k in hay for k in keys):
            return cat
    return "Other"


def _guess_arr(name: str, image: str) -> Optional[str]:
    hay = (name + " " + image).lower()
    for k, t in _ARR.items():
        if k in hay:
            return t
    return None


# Container-side ports that are NOT web UIs (torrent, dlna, turn, dns, etc.) — deprioritized.
_NONWEB = {6881, 1900, 7359, 3478, 51820, 53, 3306, 5432, 6379, 137, 138, 139, 445, 1080}


def _parse_ports(ports: str) -> list[int]:
    """TCP host ports published on 0.0.0.0, ordered so the likely web-UI port is first
    (web-ish container ports before non-web ones like torrent/DLNA)."""
    pairs = []
    for m in re.finditer(r"0\.0\.0\.0:(\d+)->(\d+)/tcp", ports or ""):
        hp, cp = int(m.group(1)), int(m.group(2))
        if (hp, cp) not in pairs:
            pairs.append((hp, cp))
    # sort: web-ish container ports first (not in _NONWEB), then by host port
    pairs.sort(key=lambda hc: (hc[1] in _NONWEB, hc[0]))
    out = []
    for hp, _ in pairs:
        if hp not in out:
            out.append(hp)
    return out


def _docker_env() -> dict:
    """Force the SYSTEM docker socket. The user's docker CLI default context is
    'desktop-linux' (Docker Desktop, empty); the real containers live on the system
    daemon at /var/run/docker.sock. Overridable via the `docker_host` setting."""
    env = dict(os.environ)
    env["DOCKER_HOST"] = get_setting("docker_host", "") or "unix:///var/run/docker.sock"
    return env


def _discover() -> list[dict]:
    """Cached ~8s — `docker ps` shells out every call; rapid Services-tab reloads
    shouldn't re-run it. Errors are never cached (they re-raise each time)."""
    from cache import cached
    return cached("homelab:discover", 8, _discover_raw)


def _discover_raw() -> list[dict]:
    try:
        r = subprocess.run(["docker", "ps", "-a", "--format", "{{json .}}"],
                           capture_output=True, text=True, timeout=15, env=_docker_env())
    except Exception as e:
        raise HTTPException(502, f"Could not reach Docker: {e}")
    if r.returncode != 0:
        raise HTTPException(502, f"docker error: {(r.stderr or r.stdout)[:200]}")
    out = []
    for line in r.stdout.splitlines():
        try:
            c = json.loads(line)
        except Exception:
            continue
        name, image = c.get("Names", ""), c.get("Image", "")
        ports = _parse_ports(c.get("Ports", ""))
        out.append({
            "source": "docker", "name": name, "image": image,
            "running": c.get("State", "") == "running",
            "status": c.get("Status", ""), "ports": ports,
            "helper": _is_helper(name, image),
            "category": _guess_category(name, image),
            "arr_type": _guess_arr(name, image),
        })
    return out


def _overrides() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM homelab_overrides").fetchall()
    conn.close()
    return {r["container"]: dict(r) for r in rows}


# ── services list ────────────────────────────────────────────────────────────
@router.get("/api/homelab/services")
def homelab_services(include_hidden: int = 0):
    host = _host()
    ov = _overrides()
    hidden_count = 0
    items = []
    for c in _discover():
        o = ov.get(c["name"], {})
        # default-hide helpers; user override wins either way
        hidden = bool(o.get("hidden")) if "hidden" in o and o.get("hidden") is not None else c["helper"]
        if o.get("hidden") is not None:
            hidden = bool(o["hidden"])
        if hidden:
            hidden_count += 1
            if not include_hidden:
                continue
        cat = o.get("category") or c["category"]
        arr_type = o.get("arr_type") or c["arr_type"]
        url = o.get("url_override") or (f"http://{host}:{c['ports'][0]}" if c["ports"] else None)
        items.append({
            "source": "docker", "name": c["name"],
            "display": o.get("display_name") or _prettify(c["name"]),
            "image": c["image"], "running": c["running"], "status": c["status"],
            "category": cat, "url": url, "ports": c["ports"],
            "arr_type": arr_type, "has_key": bool(o.get("api_key")),
            "hidden": hidden, "helper": c["helper"],
        })
    # manual services
    conn = get_conn()
    for m in conn.execute("SELECT * FROM homelab_manual ORDER BY id").fetchall():
        d = dict(m)
        items.append({
            "source": "manual", "id": d["id"], "name": d["name"], "display": d["name"],
            "image": None, "running": None, "status": None,
            "category": d.get("category") or "Other", "url": d.get("url"),
            "ports": [], "arr_type": d.get("arr_type"), "has_key": bool(d.get("api_key")),
            "hidden": False, "helper": False,
        })
    conn.close()
    # group by category
    cats: dict[str, list] = {}
    for it in items:
        cats.setdefault(it["category"], []).append(it)
    order = ["Media", "Media Management", "Downloads", "Files", "Store", "AI", "Network", "Tools", "Other"]
    grouped = [{"category": c, "services": sorted(cats[c], key=lambda x: x["display"].lower())}
               for c in order if c in cats]
    grouped += [{"category": c, "services": cats[c]} for c in cats if c not in order]
    return {"host": host, "groups": grouped, "hidden_count": hidden_count}


def _prettify(name: str) -> str:
    return re.sub(r"[-_]", " ", name).title().replace("Oc ", "").strip()


# ── per-container overrides ──────────────────────────────────────────────────
class OverrideIn(BaseModel):
    container: str
    hidden: Optional[bool] = None
    display_name: Optional[str] = None
    category: Optional[str] = None
    url_override: Optional[str] = None
    arr_type: Optional[str] = None
    api_key: Optional[str] = None


@router.post("/api/homelab/override")
def homelab_override(body: OverrideIn):
    conn = get_conn()
    cur = conn.execute("SELECT container FROM homelab_overrides WHERE container=?", (body.container,)).fetchone()
    fields = {k: v for k, v in body.dict().items() if k != "container" and v is not None}
    if not fields:
        conn.close(); return {"ok": True}
    if cur:
        sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=datetime('now')"
        conn.execute(f"UPDATE homelab_overrides SET {sets} WHERE container=?", (*fields.values(), body.container))
    else:
        cols = ["container"] + list(fields)
        conn.execute(f"INSERT INTO homelab_overrides ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                     (body.container, *fields.values()))
    conn.commit(); conn.close()
    return {"ok": True}


# ── manual services ──────────────────────────────────────────────────────────
class ManualIn(BaseModel):
    name: str
    url: Optional[str] = ""
    category: Optional[str] = "Other"
    arr_type: Optional[str] = ""
    api_key: Optional[str] = ""
    health_url: Optional[str] = ""
    notes: Optional[str] = ""


@router.post("/api/homelab/manual")
def add_manual(m: ManualIn):
    if not m.name.strip():
        raise HTTPException(400, "Name required.")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO homelab_manual (name,url,category,arr_type,api_key,health_url,notes) VALUES (?,?,?,?,?,?,?)",
        (m.name.strip(), m.url, m.category, m.arr_type, m.api_key, m.health_url, m.notes))
    conn.commit()
    row = conn.execute("SELECT id,name FROM homelab_manual WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@router.delete("/api/homelab/manual/{mid}")
def del_manual(mid: int):
    conn = get_conn()
    conn.execute("DELETE FROM homelab_manual WHERE id=?", (mid,))
    conn.commit(); conn.close()
    return {"ok": True}


# ── *arr enrichment (on demand, per service) ─────────────────────────────────
def _resolve_arr(name: str) -> Optional[dict]:
    """Find a service's url + arr_type + api_key (docker override or manual)."""
    ov = _overrides().get(name)
    if ov and ov.get("arr_type") and ov.get("api_key"):
        url = ov.get("url_override")
        if not url:
            for c in _discover():
                if c["name"] == name and c["ports"]:
                    url = f"http://{_host()}:{c['ports'][0]}"
                    break
        return {"url": url, "type": ov["arr_type"], "key": ov["api_key"]}
    conn = get_conn()
    m = conn.execute("SELECT * FROM homelab_manual WHERE name=? AND arr_type!='' AND api_key!=''", (name,)).fetchone()
    conn.close()
    if m:
        m = dict(m)
        return {"url": m["url"], "type": m["arr_type"], "key": m["api_key"]}
    return None


@router.get("/api/homelab/arr/{name}")
def arr_status(name: str):
    cfg = _resolve_arr(name)
    if not cfg or not cfg.get("url") or not cfg.get("key"):
        raise HTTPException(400, "No *arr URL + API key set for this service.")
    base = cfg["url"].rstrip("/")
    h = {"X-Api-Key": cfg["key"]}
    out = {"ok": False, "version": None, "queue": None, "warnings": []}
    try:
        s = httpx.get(f"{base}/api/v3/system/status", headers=h, timeout=4)
        if s.is_success:
            out["ok"] = True
            out["version"] = s.json().get("version")
        q = httpx.get(f"{base}/api/v3/queue", headers=h, params={"pageSize": 1}, timeout=4)
        if q.is_success:
            out["queue"] = q.json().get("totalRecords")
        hl = httpx.get(f"{base}/api/v3/health", headers=h, timeout=4)
        if hl.is_success:
            out["warnings"] = [w.get("message") for w in hl.json()][:6]
    except Exception as e:
        out["error"] = str(e)[:150]
    return out


# ── config ───────────────────────────────────────────────────────────────────
@router.get("/api/homelab/config")
def homelab_config():
    return {"host": _host(), "detected_ip": _lan_ip()}


class HostIn(BaseModel):
    host: str


@router.post("/api/homelab/config")
def set_homelab_config(body: HostIn):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('homelab_host',?)", (body.host.strip(),))
    conn.commit(); conn.close()
    return {"ok": True, "host": _host()}
