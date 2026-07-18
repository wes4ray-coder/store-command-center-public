# Store Command Center

A self-hosted dashboard for a print-on-demand + resale operation. It runs a full
local AI media suite on your own GPU box:

- **Image** generation (ComfyUI / SDXL) → design → review → approve → publish (Printify / Etsy)
- **Video** generation (diffusers: Wan / LTX / CogVideoX …) with live progress, chains, and a
  **video→audio bridge** that scores a clip with music + optional spoken narration
- **Music & voice** (MusicGen, MMS-TTS, Stable Audio, **ACE-Step** songs w/ vocals+lyrics)
- **3D** (image→mesh: TripoSR / TripoSG / Hunyuan / SF3D / TRELLIS) → Cults3D publishing
- **Resale** local-marketplace workflow (browser auto-fill, AI haggling, inbox reader)
- Trend scanning, a docs **library**, and a Pi-hole **network-security** tab

FastAPI backend + a static single-page frontend. SQLite for storage. No cloud
services required — the only external dependency is a GPU machine running
**LM Studio** (LLM) and **ComfyUI** + Python model stacks (image/video/audio/3D). One-click
provisioning of that box lives in **Settings → GPU Node** (see `deploy/node/`).

---

## Requirements

- **Python 3.10+** on **Linux or macOS**. The app itself is lightweight (FastAPI + SQLite).
- For the **AI generation** features: a machine with an **NVIDIA GPU** running **LM Studio**
  (LLM) and **ComfyUI** (+ the Python model stacks for video/audio/3D). It can be the same
  box or a separate one on your LAN — point `STORE_GPU_HOST` at it in `.env`. Without a GPU
  box the dashboard still runs; generation is just disabled.
- Publishing accounts are optional and only needed for the features you use: Printify / Etsy
  (print-on-demand), Cults3D (3D). Enter keys in the **Settings** tab.

> **This is a public self-host snapshot.** Every default is a generic `localhost` value —
> nothing points at anyone's real infrastructure. Set your own hosts/keys in `.env`
> (see [Configuration](#configuration)).

## Quick start (run it anywhere)

```bash
git clone <repo-url> store && cd store   # the green "Code" button above has the URL

# One-shot bootstrap: venv, deps, .env, database
./setup.sh                       # add --all to also fetch ComfyUI + LM Studio
$EDITOR .env                     # set STORE_GPU_HOST, STORE_PUBLIC_URL, keys
./run.sh                         # serves on http://0.0.0.0:8787
```

<details><summary>…or do it manually</summary>

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env && $EDITOR .env
( cd app && ../venv/bin/python -c "from db import init_db; init_db()" )
./run.sh
```
</details>

**`setup.sh` flags:** `--with-comfyui` (clone + prep ComfyUI), `--with-lmstudio`
(guide LM Studio download), `--with-graphify` (install Graphify and build the
Knowledge Graph tab's index from your checkout), `--all` (everything). The GPU
tools belong on your `STORE_GPU_HOST` machine; graphify runs fine on this one.

First login password is **`store`** (you'll set your own on first sign-in / in
Settings). If you're behind a reverse proxy, see **Reverse proxy** below.

---

## Configuration

Everything you'd change to move machines lives in **`app/config.py`**, and every
value there can be overridden with an environment variable (put them in `.env`).
See **`.env.example`** for the full list. The important ones:

| What | Env var | Default |
|------|---------|---------|
| GPU box host (LM Studio + ComfyUI) | `STORE_GPU_HOST` | `127.0.0.1` |
| SSH user on the GPU box | `STORE_GPU_SSH_USER` | `user` |
| LLM endpoint | `STORE_LLM_URL` | `http://<GPU_HOST>:1234/v1` |
| ComfyUI endpoint | `STORE_COMFYUI_URL` | `http://<GPU_HOST>:8188` |
| Listen host / port | `STORE_HOST` / `STORE_PORT` | `0.0.0.0` / `8787` |
| Reverse-proxy path prefix | `STORE_BASE_PATH` | `/store` |
| App display name | `STORE_APP_NAME` | `Store Command Center` |
| Data directory (db/designs/videos/backups) | `STORE_DATA_DIR` | repo root |
| Public URL (Etsy OAuth callback) | `STORE_PUBLIC_URL` | `http://localhost:8787` |
| OpenClaw CLI / agent | `STORE_OPENCLAW_BIN` / `STORE_OPENCLAW_AGENT` | `openclaw` / `agent_store` |
| Printify key / shop | `PRINTIFY_API_KEY` / `PRINTIFY_SHOP_ID` | (Settings tab) |

API keys can also be entered live in the **Settings** tab (stored in the DB,
which takes precedence over env vars).

### In-app admin (Settings → System)

- **Server**: change app name, port, URL base path, and data directory (written
  to `.env`; applied on restart).
- **Compute Nodes / Model Hosts**: point LLM / ComfyUI / 3D / audio at any machine,
  and **pick the LM Studio model** the LLM uses (prompts, listings, haggling, enhance).
- **GPU Node**: one-click **Deploy / health-check** the GPU box — image, video, 3D,
  audio, LM Studio, and the autostart services — with a live log. Requires Ubuntu.
- **Backups**: create / download / restore / delete backups (stored in
  `<data-dir>/backups`). Restore takes a safety backup first, then restarts.
- **Store Logs**: a live, filterable view of the rotating log at
  `<data-dir>/logs/store.log` (errors/warnings filter + text search + tally). Every
  unhandled endpoint failure is logged with its path + traceback by a global handler.
- **Restart Server** — guarded: a live "GPU busy — N job(s)" banner warns when a
  generation is in flight (a restart would kill it); restart requires confirmation
  while busy. Plus **Sign Out** and **Fix Browser Lock**.

### Library — web archive

Save any page for offline recall. Paste a URL and it auto-escalates **HTTP fetch →
`wget` → your logged-in Store browser** (the last one carries your real session, so it
clears Cloudflare where a headless grab can't). For the toughest sites, use **Upload
saved page (.html)** — File → Save Page As in your own browser, then upload the file.
Re-saving a URL builds a version history (a "time machine").

### Network Security tab

Scans a Pi-hole DNS firewall (`network-security/scripts/pihole-security-scan.sh`),
parses the report into findings, and gives an Approve / Ignore / Remediate
workflow with a live security score. Configure via `STORE_PIHOLE_*` env vars.

---

## Architecture

The backend is split into small, single-purpose modules — edit the one that
matches your change, not one giant file:

```
app/
├── main.py            # thin assembler: app, middleware, static mounts, router wiring,
│                      #   file logging + a global exception handler
├── config.py          # ALL machine-specific settings (hosts, paths, keys, models)
├── deps.py            # shared kernel: settings, auth, clients, LLM helper, prompts
├── services.py        # background jobs (image gen, publishing, geo, resale-agent, 3D)
├── services_media.py  # video + audio generation + the video→audio bridge (re-exported)
└── routers/           # one module per feature area — the API endpoints
    ├── auth.py        proposals.py   models.py    printify.py   videos.py
    ├── dashboard.py   designs.py     trends.py    etsy.py       resell.py
    ├── generate.py    tasks.py       settings.py  agent.py      library.py
    ├── security.py    system.py      audio.py     node.py       models3d.py
    └── cults3d.py     resell_browser.py   # 2nd router: headless-Chrome resale automation
```

Big files are split so each stays editable (and small enough for a local model to
open): `services.py` re-exports `services_media.py`; `resell.py` + `resell_browser.py`
are two routers; the frontend's `app-main.js` re-uses per-tab modules (`tab-models.js`,
`tab-settings.js`, `tab-resell.js` + `tab-resell-browser.js`, `tab-audio.js`, …).

Supporting modules (`db.py`, `printify.py`, `etsy_client.py`, `orchestrator.py`
— the single-GPU scheduler that serializes LLM vs image/video/3D/audio work,
`browser.py` — CDP resale automation) are unchanged domain logic.

Frontend is `static/index.html` (markup) + `static/js/app-main.js` (core router +
helpers) + one JS module per tab under `static/js/` (`tab-videos.js`, `tab-audio.js`,
`tab-models3d.js`, `admin.js`, …). The node provisioner is `deploy/node/node-setup.sh`
(run from Settings → GPU Node or directly on the Ubuntu GPU box).

**To add or change an endpoint:** edit `routers/<area>.py`. Shared helpers live
in `deps.py`; long-running jobs in `services.py`.

---

## Running as a service

A per-user systemd template is in `deploy/store.service` (no root required):

```bash
mkdir -p ~/.config/systemd/user
cp deploy/store.service ~/.config/systemd/user/store.service
$EDITOR ~/.config/systemd/user/store.service   # fill in the two <ABSOLUTE_PATH_TO> lines
systemctl --user daemon-reload
systemctl --user enable --now store.service
loginctl enable-linger "$USER"                 # survive logout
```

**Restart** and **Sign Out** are available in the app under **Settings → System**.
The Restart button re-execs the process in place by default (works with or
without a supervisor). To route restarts through systemd instead, set
`STORE_RESTART_CMD=systemctl --user restart store.service` in `.env`.

---

## Reverse proxy

The app is designed to sit under a path prefix (default `/store`). Example nginx:

```nginx
location ^~ /store/ {
    proxy_pass http://127.0.0.1:8787/;   # trailing slash strips the /store prefix
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Set `STORE_BASE_PATH` to match (`/store`), or to `""` to serve at the domain
root. The frontend base path is injected server-side, so static assets and the
API resolve correctly under whatever prefix you choose.

> Note: the session cookie is `Secure`, so sign-in requires **HTTPS** (or
> `http://localhost`, which browsers treat as secure).
