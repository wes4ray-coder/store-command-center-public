"""Plugin host — discovery + hardening for the drop-in plugin system.

main.py calls `mount_plugins(app)` once (inside a try/except) and nothing else;
every guard that keeps a plugin from breaking the store lives here:

  * per-plugin enable/disable — settings key `plugin_disabled_<id>` ("1" = off).
    A disabled plugin is discovered (listed at /api/plugins with status
    "disabled") but its backend is never imported and its static never mounted.
    Toggling via POST /api/plugins/<id>/toggle takes effect on the next restart
    (uvicorn can't hot-unmount routes); the frontend loader skips it immediately.
  * manifest `requires` — optional list of python module names checked with
    importlib.util.find_spec BEFORE importing backend.py, so a plugin with
    missing deps fails with a clean "missing deps [x,y]" instead of a traceback.
    Deps are never auto-installed.
  * route-collision guard — a plugin router whose (path, method) already exists
    (core route or an earlier plugin) is NOT included; the plugin lists as
    failed with error "route collision <path>". Re-registration of a plugin's
    OWN paths (same process, repeated mount_plugins) is not a collision.
  * import isolation — a backend.py that raises at import marks that plugin
    failed (error truncated) and the loop moves on; boot always completes.

Each /api/plugins entry keeps the v1 fields (manifest keys + id + frontend_url)
and adds: status ("loaded"|"failed"|"disabled"), error (truncated or None),
routes (count actually registered), frontend_ok, enabled, pending_restart.
Author contract: plugins/README.md (served read-only at /api/plugins/readme).
"""
import importlib.util
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from config import BASE
from db import get_conn

log = logging.getLogger("store")

PLUGINS_DIR = BASE / "plugins"
PLUGIN_MANIFESTS: list = []      # served by GET /api/plugins (discovery order)
_ROUTE_OWNERS: dict = {}         # (path, method) -> plugin id (self-reload tolerance)
_MOUNTED_STATIC: set = set()     # plugin ids whose static/ is already mounted
_ERR_MAX = 300                   # error strings are truncated to this many chars

router = APIRouter()


class _PluginStatic(StaticFiles):
    """Plugin asset serving with a short cache (mirrors main.CachedStaticFiles;
    defined here so plugin_host has zero imports from main)."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers.setdefault("Cache-Control", "public, max-age=60")
        return resp


# ── helpers ──────────────────────────────────────────────────────────────────
def _trunc(msg) -> str:
    msg = str(msg)
    return msg if len(msg) <= _ERR_MAX else msg[:_ERR_MAX - 1] + "…"


def _is_disabled(pid: str) -> bool:
    """settings.plugin_disabled_<id> truthy = disabled. Any DB trouble (fresh
    install, table missing at import time) defaults to enabled — never crash."""
    try:
        c = get_conn()
        row = c.execute("SELECT value FROM settings WHERE key=?",
                        (f"plugin_disabled_{pid}",)).fetchone()
        c.close()
        return bool(row and str(row["value"]).strip().lower() in ("1", "true", "on", "yes"))
    except Exception:
        return False


def _missing_requires(man: dict) -> list:
    """Module names from the manifest's `requires` that aren't importable.
    find_spec itself can raise on junk names — junk counts as missing."""
    missing = []
    for mod in (man.get("requires") or []):
        try:
            found = importlib.util.find_spec(str(mod)) is not None
        except Exception:
            found = False
        if not found:
            missing.append(str(mod))
    return missing


def _iter_routes(routes):
    """Flatten a route table. Newer FastAPI keeps include_router()-ed routers as
    lazy _IncludedRouter wrappers (.original_router) instead of flat APIRoutes —
    without flattening, the collision guard would see none of the core routes."""
    for r in routes:
        orig = getattr(r, "original_router", None)
        if orig is not None:
            yield from _iter_routes(orig.routes)
        else:
            yield r


def _route_pairs(routes):
    """(path, METHOD) pairs for every plain route in a router/app route list."""
    pairs = []
    for r in _iter_routes(routes):
        path, methods = getattr(r, "path", None), getattr(r, "methods", None)
        if path and methods:
            pairs.extend((path, m) for m in methods)
    return pairs


def _check_collisions(app, pid: str, plugin_router) -> tuple:
    """Diff the plugin router's routes against everything already on the app.
    Returns (foreign_collision_path_or_None, all_self_owned: bool)."""
    existing = {}
    for path, m in _route_pairs(app.routes):
        existing[(path, m)] = _ROUTE_OWNERS.get((path, m))   # None = core-owned
    pairs = _route_pairs(plugin_router.routes)
    self_owned = 0
    for pair in pairs:
        if pair in existing:
            if existing[pair] != pid:
                return pair[0], False       # someone else (core/other plugin) owns it
            self_owned += 1
    return None, bool(pairs) and self_owned == len(pairs)


# ── discovery (called once from main.py, before the MCP mount) ───────────────
def mount_plugins(app) -> None:
    """Walk plugins/*/plugin.json and wire every plugin onto `app` behind the
    guards documented in the module docstring. Idempotent per process."""
    del PLUGIN_MANIFESTS[:]   # keep list identity (main aliases it) on re-runs

    # Our own routes go on FIRST so the collision guard also protects them
    # (a plugin claiming /api/plugins would otherwise shadow the real one).
    if not any(p == "/api/plugins" for p, _m in _route_pairs(app.routes)):
        app.include_router(router)

    if not PLUGINS_DIR.is_dir():
        return

    for pdir in sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir()):
        mf = pdir / "plugin.json"
        if not mf.is_file():
            continue
        pid = pdir.name

        # Manifest first — a broken plugin.json still yields a (failed) entry.
        try:
            man = json.loads(mf.read_text())
            if not isinstance(man, dict):
                raise ValueError("plugin.json must be a JSON object")
        except Exception as e:
            PLUGIN_MANIFESTS.append({
                "id": pid, "name": pid, "frontend_url": None, "status": "failed",
                "error": _trunc(f"bad plugin.json: {e}"), "routes": 0,
                "frontend_ok": False, "enabled": True, "pending_restart": False,
            })
            log.warning("plugin %s failed to load: bad plugin.json: %s", pid, e)
            continue

        entry = dict(man)
        entry.update(id=pid, frontend_url=None, status="loaded", error=None,
                     routes=0, frontend_ok=False, enabled=True, pending_restart=False)

        # Disabled → listed, but nothing imported and nothing mounted.
        if _is_disabled(pid):
            entry.update(status="disabled", enabled=False)
            PLUGIN_MANIFESTS.append(entry)
            log.info("plugin %s: disabled (settings plugin_disabled_%s)", pid, pid)
            continue

        # `requires` gate → clean failure BEFORE backend.py is ever imported.
        missing = _missing_requires(man)
        if missing:
            entry.update(status="failed", error=f"missing deps [{','.join(missing)}]")
        else:
            bfile = pdir / str(man.get("backend", "backend.py"))
            if bfile.is_file():
                try:
                    # Imported like a core router: app/ is on sys.path, so the
                    # plugin can `from deps import *`. Routes ride the auth guard.
                    spec = importlib.util.spec_from_file_location(f"store_plugin_{pid}", bfile)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    prouter = getattr(mod, "router", None)
                    if prouter is not None:
                        clash, already_own = _check_collisions(app, pid, prouter)
                        if clash:
                            entry.update(status="failed", error=f"route collision {clash}")
                        elif not already_own:      # self-owned = this process already has them
                            app.include_router(prouter)
                            pairs = _route_pairs(prouter.routes)
                            _ROUTE_OWNERS.update({pair: pid for pair in pairs})
                            entry["routes"] = len({p for p, _m in pairs})
                        else:
                            entry["routes"] = len({p for p, _m in _route_pairs(prouter.routes)})
                except Exception as e:
                    entry.update(status="failed", error=_trunc(f"{type(e).__name__}: {e}"))

        # Static mounts even for failed plugins (assets/docs stay reachable);
        # only plugin.json/backend.py at the plugin root are never web-served.
        sdir = pdir / "static"
        if sdir.is_dir() and pid not in _MOUNTED_STATIC:
            try:
                app.mount(f"/plugins/{pid}", _PluginStatic(directory=str(sdir)),
                          name=f"plugin-{pid}")
                _MOUNTED_STATIC.add(pid)
            except Exception as e:
                log.warning("plugin %s: static mount failed: %s", pid, e)
        fjs = str(man.get("frontend", "frontend.js"))
        if pid in _MOUNTED_STATIC and (sdir / fjs).is_file():
            entry["frontend_url"] = f"/plugins/{pid}/{fjs}"
            entry["frontend_ok"] = True

        PLUGIN_MANIFESTS.append(entry)
        if entry["status"] == "loaded":
            log.info("plugin loaded: %s (%d routes)", pid, entry["routes"])
        else:
            log.warning("plugin %s failed to load: %s", pid, entry["error"])


# ── API ──────────────────────────────────────────────────────────────────────
@router.get("/api/plugins")
def list_plugins():
    """Every discovered plugin: v1 manifest fields (id, frontend_url, name, view,
    …) plus status/error/routes/frontend_ok/enabled/pending_restart. The frontend
    plugin-loader builds nav + scripts from this; Settings → Plugins manages it."""
    return {"plugins": PLUGIN_MANIFESTS}


@router.get("/api/plugins/readme")
def plugin_readme():
    """The plugin author contract (plugins/README.md), read-only."""
    p = PLUGINS_DIR / "README.md"
    if not p.is_file():
        raise HTTPException(404, "plugins/README.md not found")
    return PlainTextResponse(p.read_text(), media_type="text/markdown; charset=utf-8")


@router.post("/api/plugins/{pid}/toggle")
def toggle_plugin(pid: str, data: dict):
    """Persist a plugin's enabled/disabled state (settings plugin_disabled_<id>).
    Backend takes effect on the NEXT restart; the frontend loader honors it on
    the next page refresh. Body: {"enabled": true|false}."""
    entry = next((e for e in PLUGIN_MANIFESTS if e.get("id") == pid), None)
    if not entry:
        raise HTTPException(404, f"unknown plugin: {pid}")
    enabled = bool(data.get("enabled"))
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)",
                 (f"plugin_disabled_{pid}", "" if enabled else "1"))
    conn.commit()
    conn.close()
    entry["enabled"] = enabled
    # Restart pending when the desired state disagrees with what THIS process booted with.
    entry["pending_restart"] = enabled != (entry.get("status") != "disabled")
    return {"ok": True, "id": pid, "enabled": enabled,
            "pending_restart": entry["pending_restart"],
            "note": "backend change applies on the next restart"}
