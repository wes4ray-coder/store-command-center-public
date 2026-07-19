"""Health pulse — one aggregated up/down view of every moving part the Store
depends on, so the owner isn't the monitoring system.

`pulse()` returns a list of components, each:
    {key, label, group, status, detail, checked_at}
    status ∈ {'up', 'down', 'degraded', 'unknown'}

Design rules (every probe obeys them):
  • SHORT timeouts (~2.5s) — a health check that hangs is worse than none.
  • Fully defended — any exception maps to 'unknown', never propagates.
  • The whole result is cached ~20s (cache.cached) so polling is cheap and a
    burst of pollers never fans out into a burst of SSH/HTTP/docker calls.

It REUSES the existing probes rather than reinventing them: the same
GPU_HOST/COMFYUI_URL endpoints node.py checks, homelab's docker discovery, and
pihole's configured() gate.
"""
from datetime import datetime, timezone
import socket

import httpx

from config import GPU_HOST, COMFYUI_URL, PIHOLE_API_HOST, PIHOLE_API_PORT
import pihole
from cache import cached

_TIMEOUT = 2.5          # per-probe network timeout (seconds)
_CACHE_TTL = 20         # seconds the aggregated pulse is reused
_LMSTUDIO_PORT = 1234   # LM Studio OpenAI server on the GPU box


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tcp_up(host: str, port: int, timeout: float = _TIMEOUT) -> bool:
    """True if a TCP connection to host:port completes within `timeout`."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def _comp(key, label, group, status, detail):
    return {"key": key, "label": label, "group": group,
            "status": status, "detail": detail, "checked_at": _now()}


# ── individual probes (each returns one component dict, never raises) ──────────
def _probe_store():
    # If this code is executing, the API responded.
    return _comp("store_api", "Store API", "Store", "up",
                 "Serving this request")


def _probe_gpu_node():
    try:
        up = _tcp_up(GPU_HOST, 22)
    except Exception as e:
        return _comp("gpu_node", "GPU box", "GPU Box", "unknown", str(e)[:120])
    return _comp("gpu_node", "GPU box", "GPU Box",
                 "up" if up else "down",
                 f"SSH {GPU_HOST}:22 " + ("reachable" if up else "no response (box off / network down?)"))


def _probe_lmstudio():
    url = f"http://{GPU_HOST}:{_LMSTUDIO_PORT}/v1/models"
    try:
        r = httpx.get(url, timeout=_TIMEOUT)
        if r.is_success:
            n = len((r.json() or {}).get("data", []))
            return _comp("lmstudio", "LM Studio (LLM)", "GPU Box", "up",
                         f"{n} model(s) loaded" if n else "server up, no model loaded")
        # Any HTTP response means the server is listening (LM Studio answers 401
        # when no model is auth-exposed) — reachable, but flag the non-OK code.
        return _comp("lmstudio", "LM Studio (LLM)", "GPU Box", "degraded",
                     f"server up, HTTP {r.status_code} on :{_LMSTUDIO_PORT}")
    except Exception as e:
        return _comp("lmstudio", "LM Studio (LLM)", "GPU Box", "down",
                     f"no response on :{_LMSTUDIO_PORT} ({type(e).__name__})")


def _probe_comfyui():
    url = f"{COMFYUI_URL.rstrip('/')}/system_stats"
    try:
        r = httpx.get(url, timeout=_TIMEOUT)
        if r.is_success:
            dev = ""
            try:
                d = (r.json() or {}).get("devices") or []
                if d:
                    dev = " · " + str(d[0].get("name", ""))[:40]
            except Exception:
                pass
            return _comp("comfyui", "ComfyUI (images)", "GPU Box", "up",
                         f"system_stats OK{dev}")
        return _comp("comfyui", "ComfyUI (images)", "GPU Box", "degraded",
                     f"server up, HTTP {r.status_code}")
    except Exception as e:
        return _comp("comfyui", "ComfyUI (images)", "GPU Box", "down",
                     f"no response ({type(e).__name__})")


# key containers to surface individually when Docker is up (first few that exist)
_KEY_CONTAINERS = ("pihole", "jellyfin", "sonarr", "radarr", "qbittorrent",
                   "nginx-proxy-manager", "wordpress", "searxng")


def _probe_docker():
    """Docker engine + a couple of key containers, reusing homelab's discovery
    (itself cached ~8s). Returns a LIST of components."""
    try:
        from routers.homelab import _discover
        containers = _discover()
    except Exception as e:
        return [_comp("docker", "Docker engine", "Homelab", "down",
                      f"unreachable ({str(e)[:80]})")]
    running = [c for c in containers if c.get("running")]
    stopped = [c for c in containers if not c.get("running")]
    engine = _comp("docker", "Docker engine", "Homelab", "up",
                   f"{len(running)} running · {len(stopped)} stopped")
    out = [engine]
    seen = set()
    for kw in _KEY_CONTAINERS:
        if len(seen) >= 3:
            break
        for c in containers:
            name = (c.get("name") or "")
            if kw in name.lower() and name not in seen:
                seen.add(name)
                out.append(_comp(f"container:{name}", name, "Homelab",
                                 "up" if c.get("running") else "down",
                                 c.get("status") or ("running" if c.get("running") else "stopped")))
                break
    return out


def _probe_dns():
    """Pi-hole / DNS. Only meaningful if configured; otherwise 'unknown'."""
    try:
        if not pihole.configured():
            return _comp("dns_pihole", "DNS / Pi-hole", "Network", "unknown",
                         "not configured (set STORE_PIHOLE_API_PASS)")
        up = _tcp_up(PIHOLE_API_HOST, PIHOLE_API_PORT)
        return _comp("dns_pihole", "DNS / Pi-hole", "Network",
                     "up" if up else "down",
                     f"API {PIHOLE_API_HOST}:{PIHOLE_API_PORT} " +
                     ("reachable" if up else "no response"))
    except Exception as e:
        return _comp("dns_pihole", "DNS / Pi-hole", "Network", "unknown", str(e)[:120])


# ── aggregation ───────────────────────────────────────────────────────────────
_RANK = {"down": 0, "degraded": 1, "unknown": 2, "up": 3}


def _build() -> dict:
    components = []
    components.append(_probe_store())
    components.append(_probe_gpu_node())
    components.append(_probe_lmstudio())
    components.append(_probe_comfyui())
    components.extend(_probe_docker())
    components.append(_probe_dns())

    summary = {"up": 0, "down": 0, "degraded": 0, "unknown": 0}
    for c in components:
        summary[c["status"]] = summary.get(c["status"], 0) + 1

    # worst = the lowest-ranked status actually present (down < degraded < unknown < up)
    worst = "up"
    for c in components:
        if _RANK.get(c["status"], 3) < _RANK.get(worst, 3):
            worst = c["status"]

    return {"components": components, "summary": summary, "worst": worst,
            "checked_at": _now()}


def pulse() -> dict:
    """Aggregated health of all Store dependencies. Cached ~20s so polling is cheap.
    Never raises — every probe self-defends into an 'unknown'/'down' component."""
    return cached("health:pulse", _CACHE_TTL, _build)
