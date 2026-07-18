# Store Architecture & Extension Guide

Written for **future agents (including small-context local models)** working on this
codebase. It explains the load-bearing patterns — *why* they exist and *how to add to
them* — so you can change one subsystem without reading the whole repo.

Start with [`INDEX.md`](../INDEX.md): it maps every tab → JS files → routers → endpoints
→ DB tables → external services. This file explains the *patterns* INDEX.md indexes.

**Two verification harnesses gate every change. Run the relevant one before you claim done:**
- Backend: `./run_tests.sh` (pytest; the smoke test auto-discovers and GETs every
  registered endpoint, so a dropped/renamed route fails it).
- Frontend: `bash tools/verify_spa.sh` (concatenates all `<script>`s in load order and
  `node --check`s the bundle — this **reproduces the browser's shared-global-scope
  redeclaration errors** that `node --check` on a single file cannot catch).

---

## 1. Why files are kept small

The owner runs **local LLM agents with small context windows** against this repo. A
1000-line file doesn't fit, so no single agent can safely edit it. The rule of thumb:
**keep source files under ~450 lines**, split by responsibility. Ten oversized files were
split into packages/modules (see §2–§4). When you add code, add it to the *smallest*
file that owns that responsibility; if a file crosses ~450 lines, split it using the
patterns below rather than growing it.

---

## 2. Backend: the router-package pattern

Big routers are **Python packages** that expose one shared `router`, so `main.py` (which
does `from routers import X` and includes `X.router`) never changes. Examples:
`app/routers/github/` and `app/routers/peers/`.

Layout (using `github/` as the template):
```
app/routers/github/
  __init__.py   # from ._base import router; from . import repos, models, jobs  (+ re-exports)
  _base.py      # the shared `router = APIRouter()`, shared helpers, import-time side effects
  repos.py      # from ._base import router; @router.get("/api/github/...") def ...
  models.py     #   "
  jobs.py       #   "
```

Rules:
- **One `router` object** lives in `_base.py`. Every submodule does `from ._base import
  router` and decorates its endpoints on it. `__init__.py` imports the submodules so their
  decorators execute (registering the routes) at package-import time.
- **Import-time side effects run once, in `_base.py`**: e.g. `_ensure_schema()` (idempotent
  `CREATE TABLE`/`ALTER`) and any startup reconcile. Never duplicate these per submodule.
- **A helper used by two submodules → `_base.py`**; both import it. A helper used by one
  submodule stays local to it.
- **Intra-package imports are relative** (`from ._base import router`); imports of app
  modules keep the flat/absolute style the repo uses (`from deps import *`) because `app/`
  is on `sys.path` (modules are imported as `deps`, `swarm`, `routers.github`, *not*
  `app.deps`).
- **No cycles**: if submodule A calls a function in submodule B and vice-versa, break it
  with a lazy import *inside the function body* (`def f(): from .b import g`). `peers/` and
  `swarm/` both do this.

**To add a new endpoint** to an existing router package: add the function to the submodule
that owns that domain (or a new submodule imported from `__init__.py`), decorate with
`@router.<method>("/api/...")`, run `./run_tests.sh`.

**To add a whole new tab/router**: create `app/routers/<name>.py` (single file is fine
until it grows) with `router = APIRouter()` + your endpoints; add `<name>` to the two
`from routers import (...)` / include lists in `app/main.py`; if it needs tables, add an
idempotent `_ensure_schema()` called at import (per-module schema is the repo convention —
see §5). Then add the frontend tab (§3).

### Engine packages
`app/swarm/` is the same idea for a non-router module (imported as `import swarm`). Its
`__init__.py` **re-exports the public surface** (`start_job`, `is_running`,
`reconcile_on_start`, `propose_system_task`, `run_system_task`, plus the `*_SYS` prompt
constants that `prompts.py` resolves by name) so `swarm.X` keeps working for callers.
Submodules: `_base` (shared state) → `llm`, `workspace` → `systasks` → `engine`.

### The `deps.py` choke point
`deps.py` is imported by ~59 modules via `from deps import *`, so **its export surface must
never shrink**. Cohesive concerns were extracted into their own findable modules while
`deps` keeps re-exporting them:
- `app/auth_core.py` — password hashing, first-run secret, login page, `_AUTH_BYPASS`.
- `app/llm_client.py` — `_call_lmstudio`, model resolution, NSFW flag.

`deps.py` re-exports them with **explicit imports** (`from auth_core import _check_password,
...`) — note `import *` will NOT pull underscore-prefixed names, so private helpers must be
listed explicitly. When you extract more from `deps`, follow this: move the code, add an
explicit re-export line to `deps.py`, and verify the surface is unchanged:
```
venv/bin/python -c "import sys;sys.path.insert(0,'app');import deps;print(sorted(n for n in dir(deps) if not n.startswith('__')))"
```
should be identical before/after. Break cycles with lazy imports (llm_client pulls a few
`deps` settings lazily inside the function body).

---

## 3. Frontend: the classic-script shared-global model

The SPA is **not** ES modules. Every `static/js/*.js` is a classic `<script>` loaded by a
tag in `static/index.html`, and they **all share one global lexical scope**. Functions and
state are bare globals; there is no `import`/`export`. This has three consequences you must
respect:

1. **A top-level `let`/`const` declared in two files is a fatal "Identifier already
   declared" error at load** (it kills the whole app, not one tab). So **each name is
   declared in exactly one file.** Shared state lives in the tab's *core* file, which loads
   *first* among that tab's files.
2. **Load order only matters for parse-time code.** Function bodies run later (post
   `DOMContentLoaded`), so cross-file *calls* work regardless of order as long as every
   file is loaded. But code that runs *at parse time* (e.g. `document.addEventListener`,
   `.modal` wiring, lightbox setup in `app-core.js`) must be in a file loaded in `<body>`
   after the DOM markup — all current tags qualify.
3. **The kernel loads first.** `app-core.js` holds the shared state (`API`, `_currentView`,
   `_settings`, `_productTypes`, …) and the utilities everything uses (`api()`, `esc()`,
   `toast()`, `imgUrl()`, `thumbUrl()`, `thumbAny()`, modal/lightbox). It takes the first
   script slot. Anything referencing these at parse time must load after it.

### How the big files were split (templates to copy)
- **Kernel** `app-main.js` → `app-core.js` (state + utils, first) + `app-nav.js`
  (`renderView` dispatch + bootstrap) + `app-queue.js` + `app-studio.js` +
  `tab-dashboard/designs/products/trends/agent.js`.
- **Tab with sub-tabs** (`network-security.js`, `tab-settings.js`, `tab-resell.js`,
  `tab-models.js`): a `*-core.js` holds the sub-tab dispatcher (`secTab`, `settingsSub`,
  `_renderResellSub`, `renderModels`) + shared timers/state, and each sub-view group gets
  its own file (`sec-command.js`, `settings-models.js`, `resell-new.js`, `models-image.js`,
  …). The core loads first.
- **Canvas layers** (`world-render.js`): core keeps the render loop + shared caches (the
  vignette gradient cache `_vgGrad`), each draw layer gets a file
  (`world-render-buildings/combat/overlays/agents.js`).

### To add a new tab (frontend)
1. Create `static/js/tab-<name>.js` with a `render<Name>()` function (bare global). Put any
   module-level state used only by this tab at the top of this file; if shared, put it in
   `app-core.js`.
2. Add a `<script src='/store/static/js/tab-<name>.js'></script>` tag in
   `static/index.html` (after `app-core.js`).
3. Wire it into the nav markup and the `renderView()` dispatch in `app-nav.js` (map the
   view key → `render<Name>()`).
4. **Run `bash tools/verify_spa.sh`** — must print `BUNDLE OK` and `RESULT: PASS`. If it
   says "already been declared", you duplicated a top-level `let`/`const`; move it to one
   file.

### Rendering server/LLM/agent text safely (XSS)
Any string that came from the server, an LLM, or another agent must be escaped before it
enters `innerHTML`. Use the global `esc()` for text and attributes; for a URL used in a
click handler, put it in a `data-` attribute and read `this.dataset.x` rather than
interpolating into inline `onclick`. (Grep for `esc(` to see the pattern.)

### Thumbnails (avoid full-size image decode)
Galleries must not load multi-MB originals. Two helpers:
- `thumbUrl(path)` — designs only (`/thumb/{sub}/{filename}`).
- `thumbAny(relPath, w)` — any **local** file under an allowlisted root, via
  `GET /api/thumb?path=&w=` (`app/routers/designs.py`). The backend enforces a realpath
  allowlist (`_THUMB_ROOTS`: designs, models3d renders/hero, videos, resell_uploads) and
  rejects traversal. **To make a new local image dir thumbnailable**, add its real on-disk
  path to `_THUMB_ROOTS`. External CDN URLs and `data:` URIs cannot be thumbnailed (no
  local file) — leave those as-is.
Always keep the original in the lightbox/`data-full` and add an `onerror` fallback to the
original.

---

## 4. Always run the SPA harness after frontend edits

`tools/verify_spa.sh` is the frontend equivalent of the test suite. It catches the exact
failure mode of this shared-scope architecture (duplicate declarations / load-order syntax)
that per-file linting misses. Baseline: `RESULT: PASS`. If a split drops the function count
a lot, a file wasn't wired into `index.html`. (Note: the count is a grep heuristic and
ignores `_`-prefixed functions — the authoritative gate is `BUNDLE OK` + `RESULT: PASS`.)

---

## 5. Money & gating (real-money safety)

Real-money and secret-export actions flow through the **prayer/approval system** in
`app/world_ops.py` (the God Console UI). This is the security backbone — respect it:

- `pray(kind, cost_cents, payload)` files a request; a human blesses it in the God Console
  before it executes. `can_spend()` enforces the monthly budget cap.
- **`ALWAYS_GATE`** (`paypal_payout`, `wallet_send`, `secret_export`) is **non-toggleable by
  design** — `gated_kinds()` unconditionally unions it, and the gate-toggle endpoint
  refuses to turn these off. This is the *one* exception to the owner's standing "every gate
  gets a user toggle" preference: irreversible money-out must not be self-approvable by a
  local agent or an SSRF pivot riding the localhost/MCP auth bypass.
- Status transitions are **atomic** (`UPDATE ... WHERE status='pending'`, act only if
  `rowcount==1`) to prevent double-approve double-spend. PayPal payouts carry a
  `sender_batch_id` idempotency key and refund the ledger if execution fails.

**To add a new spendable/irreversible action**: file it through `pray()` with the real
`cost_cents`; if it moves real money out or exports secrets, add its kind to `ALWAYS_GATE`
and give it a dedicated endpoint (never let it be filed via the generic `ops_pray`). For a
*reversible* gated action, add a normal toggle-able gate kind (honor the toggle preference).
Cover it with a test in `tests/test_money_gates.py`.

---

## 6. Schema convention

Two conventions coexist: core tables in `app/db.py:init_db`, and **per-module
`_ensure_schema()`** (idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER` in try/except) in
the module that owns the domain (`world_*`, `crypto`, `peers`, `github`, `money`,
`wallets`, …), run at import. For new subsystems prefer **per-module `_ensure_schema()`** —
it keeps the schema next to the code that uses it and keeps `db.py` from becoming a
god-file. SQLite runs in WAL with `busy_timeout=5000` (`db.py`); wrap multi-step money
writes so a failure can't leave a half-applied ledger.
