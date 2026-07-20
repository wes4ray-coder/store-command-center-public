"""Drop-in plugin system — discovery, routing, static serving, and boot resilience.

The tracked plugins/hello-world/ example doubles as the fixture: it must be
discovered at boot, its backend route must answer, and its frontend must be served
under /plugins/hello-world/. Hardening (app/plugin_host.py): a plugin that raises at
import, collides on a route, misses declared deps, or is disabled must be contained —
listed with a per-plugin status, core routes untouched, boot never broken (verified
in a subprocess so the bad plugins are present at main-import time without disturbing
this suite's app).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STORE_DIR = Path(__file__).resolve().parent.parent
PLUGINS_DIR = STORE_DIR / "plugins"


def test_api_plugins_lists_hello_world(client):
    r = client.get("/api/plugins")
    assert r.status_code == 200
    plugins = r.json()["plugins"]
    hw = next((p for p in plugins if p.get("id") == "hello-world"), None)
    assert hw, f"hello-world not discovered; got ids {[p.get('id') for p in plugins]}"
    assert hw["view"] == "hello-world"
    assert hw["frontend_url"] == "/plugins/hello-world/frontend.js"


def test_plugin_backend_route_responds(client):
    r = client.get("/api/hello-world/ping")
    assert r.status_code == 200, f"plugin route -> {r.status_code} {r.text[:160]}"
    body = r.json()
    assert body.get("ok") is True and body.get("plugin") == "hello-world"


def test_plugin_static_frontend_served(client):
    r = client.get("/plugins/hello-world/frontend.js")
    assert r.status_code == 200, f"plugin static -> {r.status_code}"
    assert "registerView('hello-world'" in r.text


def test_plugin_manifest_and_backend_never_served(client):
    """Security contract: only static/ is web-exposed — the manifest and backend
    module at the plugin root must not be reachable over HTTP."""
    for path in ("/plugins/hello-world/plugin.json", "/plugins/hello-world/backend.py"):
        r = client.get(path)
        assert r.status_code == 404, f"{path} must not be web-served (got {r.status_code})"


def test_status_fields_and_backward_compat(client):
    """/api/plugins keeps the v1 shape (manifest keys + id + frontend_url) and adds
    the hardening fields with sane values for the healthy hello-world plugin."""
    hw = next(p for p in client.get("/api/plugins").json()["plugins"]
              if p.get("id") == "hello-world")
    # v1 fields intact
    assert hw["view"] == "hello-world"
    assert hw["name"] == "Hello World"
    assert hw["frontend_url"] == "/plugins/hello-world/frontend.js"
    # hardening fields
    assert hw["status"] == "loaded"
    assert hw["error"] is None
    assert hw["routes"] >= 1
    assert hw["frontend_ok"] is True
    assert hw["enabled"] is True
    assert hw["pending_restart"] is False


def test_toggle_persists_and_flags_restart(client):
    """Toggling a loaded plugin off persists plugin_disabled_<id> and flags
    pending_restart (uvicorn can't hot-unmount); toggling back clears it."""
    try:
        r = client.post("/api/plugins/hello-world/toggle", json={"enabled": False})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert r.json()["pending_restart"] is True
        hw = next(p for p in client.get("/api/plugins").json()["plugins"]
                  if p["id"] == "hello-world")
        assert hw["enabled"] is False
        assert hw["status"] == "loaded"          # boot-time state until restart
        assert hw["pending_restart"] is True
        # unknown plugin → clean 404, not a 500
        assert client.post("/api/plugins/zz-nope/toggle", json={"enabled": True}).status_code == 404
    finally:
        r = client.post("/api/plugins/hello-world/toggle", json={"enabled": True})
        assert r.status_code == 200 and r.json()["pending_restart"] is False


def test_plugin_readme_served(client):
    """The author contract is reachable read-only for the Settings → Plugins pane."""
    r = client.get("/api/plugins/readme")
    assert r.status_code == 200
    assert "plugin.json" in r.text and "requires" in r.text


def test_bad_plugins_cannot_break_the_store(tmp_path):
    """One throwaway boot (subprocess: discovery is module-level) with FOUR bad
    plugins present proves every plugin_host guard at once:
      - import crash   → status failed, error kept, boot completes
      - route collision→ router NOT included (its unique route absent), core wins
      - disabled       → listed as disabled, backend never imported
      - missing requires→ failed with 'missing deps [...]', backend never imported
    plus hello-world still loads and core routes still answer 200."""
    fixtures = {
        "zz-broken-test": {
            "plugin.json": json.dumps({"name": "Broken", "view": "zz-broken-test"}),
            "backend.py": "raise RuntimeError('boom at import')\n",
        },
        "zz-collide-test": {
            "plugin.json": json.dumps({"name": "Collide", "view": "zz-collide-test"}),
            "backend.py": (
                "from fastapi import APIRouter\n"
                "router = APIRouter()\n"
                "@router.get('/api/settings')\n"          # collides with a core route
                "def clash(): return {'hijacked': True}\n"
                "@router.get('/api/zz-collide-test/other')\n"
                "def other(): return {}\n"
            ),
        },
        "zz-disabled-test": {
            "plugin.json": json.dumps({"name": "Disabled", "view": "zz-disabled-test"}),
            "backend.py": (
                "import pathlib\n"
                f"pathlib.Path({str(tmp_path)!r}, 'disabled-imported.flag').touch()\n"
                "from fastapi import APIRouter\nrouter = APIRouter()\n"
            ),
        },
        "zz-missing-deps-test": {
            "plugin.json": json.dumps({"name": "NeedsDeps", "view": "zz-missing-deps-test",
                                       "requires": ["zz_definitely_absent_module"]}),
            "backend.py": (
                "import pathlib\n"
                f"pathlib.Path({str(tmp_path)!r}, 'deps-imported.flag').touch()\n"
                "from fastapi import APIRouter\nrouter = APIRouter()\n"
            ),
        },
    }
    try:
        for pid, files in fixtures.items():
            d = PLUGINS_DIR / pid
            d.mkdir(parents=True, exist_ok=True)
            for fname, content in files.items():
                (d / fname).write_text(content)
        code = (
            f"import sys; sys.path.insert(0, {str(STORE_DIR / 'app')!r})\n"
            "import db; db.init_db()\n"
            "conn = db.get_conn()\n"
            "conn.execute(\"INSERT OR REPLACE INTO settings (key,value) VALUES\"\n"
            "             \" ('plugin_disabled_zz-disabled-test','1')\")\n"
            "conn.commit(); conn.close()\n"
            "import main\n"
            "by_id = {p['id']: p for p in main.PLUGIN_MANIFESTS}\n"
            "assert by_id['hello-world']['status'] == 'loaded', by_id['hello-world']\n"
            "b = by_id['zz-broken-test']\n"
            "assert b['status'] == 'failed' and 'boom at import' in b['error'], b\n"
            "c = by_id['zz-collide-test']\n"
            "assert c['status'] == 'failed', c\n"
            "assert c['error'] == 'route collision /api/settings', c\n"
            "paths = {getattr(r, 'path', None) for r in main.app.routes}\n"
            "assert '/api/zz-collide-test/other' not in paths, 'collided router was included'\n"
            "d = by_id['zz-disabled-test']\n"
            "assert d['status'] == 'disabled' and d['enabled'] is False, d\n"
            "m = by_id['zz-missing-deps-test']\n"
            "assert m['status'] == 'failed', m\n"
            "assert m['error'] == 'missing deps [zz_definitely_absent_module]', m\n"
            "from fastapi.testclient import TestClient\n"
            "cl = TestClient(main.app, base_url='https://testserver')\n"
            "r = cl.post('/login', data={'password': 'store'}, follow_redirects=False)\n"
            "assert r.status_code in (200, 302, 303), r.status_code\n"
            "r = cl.get('/api/settings')\n"     # core route still core-owned + 200
            "assert r.status_code == 200 and 'hijacked' not in r.json(), r.text[:200]\n"
            "r = cl.get('/api/plugins')\n"
            "assert r.status_code == 200 and len(r.json()['plugins']) >= 5\n"
            "r = cl.get('/api/hello-world/ping')\n"
            "assert r.status_code == 200 and r.json()['ok'] is True\n"
        )
        env = dict(os.environ, STORE_DATA_DIR=str(tmp_path), STORE_BASE_PATH="")
        r = subprocess.run([sys.executable, "-c", code], env=env, timeout=180,
                           cwd=str(STORE_DIR / "app"), capture_output=True, text=True)
        assert r.returncode == 0, (
            f"hardening boot failed:\n{r.stderr[-3000:]}")
        # never-imported proofs: the sentinel files the bad backends would write
        assert not (tmp_path / "disabled-imported.flag").exists(), "disabled plugin was imported"
        assert not (tmp_path / "deps-imported.flag").exists(), "missing-deps plugin was imported"
    finally:
        for pid in fixtures:
            shutil.rmtree(PLUGINS_DIR / pid, ignore_errors=True)
