# Drop-in plugins

Extend the Store Command Center without editing a single core file. Drop a folder in
here, restart the store, done. Because `plugins/` is gitignored (only this README is
tracked), your plugins **survive every store update with zero re-wiring**.

```
plugins/<name>/
  plugin.json          # manifest (required; never web-served)
  backend.py           # exposes a FastAPI `router` (optional; never web-served)
  static/
    frontend.js        # defines a render fn + calls registerView() (optional)
    <assets…>          # everything in static/ is served at /plugins/<name>/…
```

At boot the store walks `plugins/*/plugin.json` (see `app/plugin_host.py`), includes
each `backend.py`'s router, mounts each `static/` dir, and lists the manifests at
`GET /api/plugins`. The frontend `plugin-loader.js` then injects a sidebar nav item per
loaded plugin and script-loads each frontend. A broken plugin is listed as **failed**
(with its error) and otherwise skipped — it can never break boot, routing, or the UI.
Manage plugins (enable/disable, statuses, errors) in **Settings → 🔌 Plugins**.

## plugin.json — the manifest

```json
{
  "name": "My Plugin",          // nav label (required-ish: shown in the sidebar)
  "version": "1.0.0",
  "icon": "🧩",                  // nav icon (emoji)
  "view": "my-plugin",          // unique view id — must not collide with a core view
  "nav_group": "Plugins",       // sidebar group header (default "Plugins")
  "backend": "backend.py",      // backend module filename (default "backend.py")
  "frontend": "frontend.js",    // frontend filename inside static/ (default "frontend.js")
  "requires": [],               // optional: python modules your backend imports,
                                //   e.g. ["pandas", "yaml"] — checked BEFORE your
                                //   backend is imported; missing ones fail the plugin
                                //   cleanly ("missing deps [...]"). Never auto-installed:
                                //   pip-install them into the store's venv yourself.
  "description": "What it does."
}
```

The store adds fields when serving `/api/plugins`: `id` (the folder name),
`frontend_url` (`/plugins/<id>/<frontend>`, or `null` if the file doesn't exist), plus
the hardening fields `status` (`loaded` | `failed` | `disabled`), `error` (truncated,
or `null`), `routes` (how many backend routes registered), `frontend_ok`, `enabled`,
and `pending_restart`.

## backend.py — the router contract (optional)

Expose a module-level `router = APIRouter()` and namespace your routes under
`/api/<plugin>/…`. The store's `app/` dir is on `sys.path`, so you can import the same
shared kernel core routers use — `from deps import *`, `from config import _env`, etc.

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/my-plugin/ping")
def ping():
    return {"ok": True}
```

Your routes ride the store's **normal auth guard** like any core route (session
required; same-box localhost calls bypass, as everywhere else). Guard rails
(`app/plugin_host.py`) — the store protects itself, not you:

- **Import isolation** — if your backend raises at import, the plugin lists as
  `failed` with the error and the store still boots.
- **Route collisions** — if any of your routes' `path`+`method` already exists (a core
  route or an earlier plugin's), your router is **not** included and the plugin lists
  as `failed` with `route collision <path>`. Namespace under `/api/<plugin>/…`.
- **`requires`** — declare your python deps in the manifest; missing ones fail the
  plugin with `missing deps [x,y]` before your code is ever imported.
- **Enable/disable** — Settings → 🔌 Plugins persists `plugin_disabled_<id>`; a
  disabled plugin is listed but never imported or mounted. Backend enable/disable
  takes effect on the next restart (the sidebar honors it on the next refresh).

## static/frontend.js — the view contract (optional)

Define an async render function that draws into `#main-content`, then register it:

```javascript
'use strict';

async function renderMyPlugin() {
  const data = await api('/api/my-plugin/ping');
  document.getElementById('main-content').innerHTML =
    `<div class="card">${statCard('Ping', esc(String(data.ok)))}</div>`;
}
registerView('my-plugin', renderMyPlugin);
```

All the store's frontend globals are available: `api()`, `esc()`, `toast()`,
`statCard()`, `hlp()`, plus the existing CSS classes/variables. Clicking your nav item
goes through the store's normal `renderView()` dispatch — `registerView` is the only
wiring you do. Extra assets in `static/` are reachable at `/plugins/<name>/<file>`
(prefix with the `API` global in JS, e.g. `` `${API}/plugins/my-plugin/logo.png` ``).

## Security notes

- **Only `static/` is web-served.** `plugin.json`, `backend.py`, and anything else at
  the plugin root are never exposed over HTTP.
- Backend routes sit behind the store's auth guard automatically — but a plugin's
  backend runs with the store's full privileges, so only install plugins you trust.
- Don't put secrets in `static/` (it's served to any logged-in browser).

## Example

`plugins/hello-world/` in this folder is a complete working plugin (one backend route,
one view) — copy it to start your own. It also doubles as the plugin-system test
fixture (`tests/test_plugins.py`), so please leave it in place.
