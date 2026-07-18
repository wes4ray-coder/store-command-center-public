"""Pi-hole v6 API client — session auth (cached) + queries, stats, and deny/allow
domain management. Host/port/password come from config.py (env-overridable)."""
import time
import httpx

try:
    from config import PIHOLE_API_HOST, PIHOLE_API_PORT, PIHOLE_API_PASS
except Exception:
    PIHOLE_API_HOST, PIHOLE_API_PORT, PIHOLE_API_PASS = "localhost", "8889", ""

_BASE = f"http://{PIHOLE_API_HOST}:{PIHOLE_API_PORT}/api"
_session = {"sid": None, "exp": 0.0}

# Query statuses Pi-hole reports as "blocked".
BLOCKED_STATUSES = {"GRAVITY", "DENYLIST", "REGEX_DENY", "BLACKLIST", "EXTERNAL_BLOCKED",
                    "SPECIAL_DOMAIN", "GRAVITY_CNAME", "REGEX_CNAME", "DENYLIST_CNAME"}


class PiholeError(RuntimeError):
    pass


def configured() -> bool:
    return bool(PIHOLE_API_PASS)


def _auth() -> str:
    if _session["sid"] and _session["exp"] > time.time() + 5:
        return _session["sid"]
    try:
        r = httpx.post(f"{_BASE}/auth", json={"password": PIHOLE_API_PASS}, timeout=10)
        r.raise_for_status()
        sess = r.json().get("session", {})
        sid = sess.get("sid")
        if not sid:
            raise PiholeError("Pi-hole auth failed (check STORE_PIHOLE_API_PASS)")
        _session["sid"] = sid
        _session["exp"] = time.time() + float(sess.get("validity", 300))
        return sid
    except httpx.HTTPError as e:
        raise PiholeError(f"Cannot reach Pi-hole API at {_BASE}: {e}")


def _get(path: str, params: dict = None) -> dict:
    sid = _auth()
    r = httpx.get(f"{_BASE}{path}", params=params or {}, headers={"X-FTL-SID": sid}, timeout=15)
    if r.status_code == 401:
        _session["sid"] = None  # expired — retry once
        sid = _auth()
        r = httpx.get(f"{_BASE}{path}", params=params or {}, headers={"X-FTL-SID": sid}, timeout=15)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    sid = _auth()
    r = httpx.post(f"{_BASE}{path}", json=body, headers={"X-FTL-SID": sid}, timeout=15)
    r.raise_for_status()
    return r.json() if r.text else {}


def _delete(path: str) -> bool:
    sid = _auth()
    r = httpx.delete(f"{_BASE}{path}", headers={"X-FTL-SID": sid}, timeout=15)
    return r.status_code in (200, 204)


# ── Reads ────────────────────────────────────────────────────────────────────
def get_queries(length: int = 200) -> list:
    """Recent DNS queries, normalized + newest first."""
    data = _get("/queries", {"length": length})
    out = []
    for q in data.get("queries", []):
        client = q.get("client") or {}
        status = q.get("status", "")
        out.append({
            "time": q.get("time"),
            "type": q.get("type"),
            "domain": q.get("domain"),
            "status": status,
            "blocked": status in BLOCKED_STATUSES,
            "client_ip": client.get("ip"),
            "client": client.get("name") or client.get("ip"),
            "upstream": q.get("upstream"),
        })
    return out


def get_summary() -> dict:
    return _get("/stats/summary")


def get_top_clients(count: int = 20, blocked: bool = False) -> list:
    d = _get("/stats/top_clients", {"count": count, "blocked": str(blocked).lower()})
    return d.get("clients", [])


# ── Domain management (ban / allow) ──────────────────────────────────────────
def add_domain(domain: str, kind: str = "deny", comment: str = "Added by Store") -> dict:
    """kind = 'deny' (ban) or 'allow' (whitelist). Exact match."""
    listtype = "deny" if kind == "deny" else "allow"
    return _post(f"/domains/{listtype}/exact",
                 {"domain": domain, "comment": comment, "enabled": True})


def remove_domain(domain: str, kind: str = "deny") -> bool:
    listtype = "deny" if kind == "deny" else "allow"
    return _delete(f"/domains/{listtype}/exact/{domain}")


def list_domains(kind: str = "deny") -> list:
    listtype = "deny" if kind == "deny" else "allow"
    d = _get(f"/domains/{listtype}/exact")
    return d.get("domains", [])
