# Store Book

Detailed navigation for the Store application.

## 🚀 App Components
- [Database (`db.py`)](#db)
- [Etsy Client (`etsy_client.py`)](#etsy-client)
- [Price Fixer (`fix_etsy_prices.py`)](#fix-etsy-prices)
- [Library (`library.py`)](#library)
- [Main Entry (`main.py`)](#main)
- [Orchestrator (`orchestrator.py`)](#orchestrator)
- [Printify Client (`printify.py`)](#printify)
- [Trends (`trends.py`)](#trends)
- [Cults3D Client (`cults.py`)](#cults) — shared GraphQL client + `createCreation` publish
- [3D Mesh Renderer (`render3d.py`)](#render3d) — CPU turntable PNGs (trimesh + matplotlib)
- [3D Pipeline (`routers/models3d.py`)](#models3d) — backlog → review → publish to Cults3D
- [GPU Node Deploy (`routers/node.py` + `deploy/node/`)](#node) — provision/health-check the box
- [Video (`routers/videos.py` + `services.py`)](#video) — diffusers gen, chains, live progress, cancel/retry
- [Audio / Music (`routers/audio.py` + `deploy/node/store_audiogen.py`)](#audio) — music + voice + video sound
- [Orchestrator queue](#orchestrator) — one GPU, serialized across LLM / image / video / 3D / audio
- [Store Logs + error handling](#logs) — rotating file log, in-app viewer, global exception handler
- [LLM model picker](#llmpick) — choose the LM Studio model in Settings
- [Web Archive](#archive) — URL → wget/browser save, or upload a saved .html
- [Modular layout](#modular) — how the big files were split (services_media, resell_browser, tab-*)

## 🎨 Design & Assets
- [Designs](#designs)
- [Static Assets](#static)

## 🛡 Security
- [Network Security](#network-security)

## 📅 Goals & Planning
- [Goals (`GOAL.md`)](#goal)
- [Todo (`TODO.md`)](#todo)
- [Resell Plan](#resell-plan)

---

## 📊 Current Status
- **Status:** ✅ Working State
- **Last Updated:** 2026-07-13
- **DB Size:** 544,768 bytes
- **API Routes:** ~197 route handlers across `routers/*.py`

## 🎉 Major Fixes (2026-07-12)
- ✅ **RESOLVED:** Tabs Not Loading - Script paths fixed
- ✅ **RESOLVED:** main.py too big - Modularized into config.py, deps.py, services.py, routers/*.py
- ✅ **RESOLVED:** All API routes verified working
- ✅ **RESOLVED:** All frontend JS modules restored and working

## 🧊 3D Studio + Cults3D Pipeline (2026-07-13)

A full **3D-printable model pipeline** that sells on **Cults3D**, mirroring the merch flow:
`backlog → 🖼 render → 🤖 AI propose → ✏️ edit → ✅ approve → 🚀 publish`. Nothing goes live
without a click (review-gate each). Publishing is **API-driven** via Cults3D's `createCreation`
mutation (assets pulled from a token-guarded public route on this app — no browser scraping).

- **Tab:** sidebar **3D Studio** (`data-view=models3d`, `static/js/tab-models3d.js`). Backlog
  folder is **editable in-app** (Settings key `models3d_backlog_path`; scan preserves each file's
  source **folder + category** and feeds them to the AI listing prompt). Files are **never moved**.
- **Cults3D tab** (`tab-cults3d.js`): dashboard — account, live listings grid, derived stats
  (count / downloads / avg price), and shortcuts into 3D Studio.
- **Backend:** `db.py` → `models3d` table; `cults.py` (GraphQL + publish); `render3d.py` (CPU
  turntable renders — runs on the STORE server, no GPU/GL needed); `routers/models3d.py`
  (scan/propose/render/hero/approve/publish/generate + public asset route). Product images = both
  **real STL renders** and **SDXL hero images** (full prompt control; any image can be the cover).
- **Local text/image → 3D generation** on the GPU box, selectable per-generation (dropdown in
  Generate). See the 3D model catalog below.

## 🧩 3D Generation Models — READ THIS

3D generators install on the GPU box and are catalogued in `config.py` → `RECOMMENDED_3D_MODELS`
(appears as **Install buttons** in the Models tab AND 3D Studio → Generate). **Golden rule: NEVER
install/upgrade torch on the box — it breaks ComfyUI.** Every 3D venv is created with
`python3 -m venv --system-site-packages` + a `zzz_comfyui.pth` pointing at ComfyUI's site-packages,
so it **reuses ComfyUI's exact torch**. The box has **no `nvcc` by default**, so models needing
compiled CUDA ops (torchmcubes/diso) are **patched to CPU extractors** (PyMCubes / skimage).

| Model | License | Sell? | Notes |
|---|---|---|---|
| **TripoSR** | MIT | ✅ | Fast default. CPU-patched (PyMCubes). **Verified working.** |
| **TripoSG** ★ | MIT | ✅ | Higher quality. diso patched → CPU skimage path. Recommended sellable upgrade. |
| **SF3D** | Stability Community | ✅ (<$1M rev) | Textured. Needs CUDA toolkit + a HuggingFace token (gated model). |
| **TRELLIS** | MIT | ✅ | Top quality, heavy/experimental build (nvdiffrast/spconv/flash-attn). Needs CUDA toolkit. |

- **CUDA toolkit:** installed on the box (`nvcc 12.0`) for SF3D/TRELLIS. The box needs a **sudo
  password** for `apt` (no passwordless sudo) — only TripoSR/TripoSG work without the toolkit.
- Box-side scripts live in `~/.openclaw/tools/model3d/` and are bundled in `deploy/node/model3d/`
  (install_*.sh, generate_*.sh, `triposr_isosurface_pymcubes.py` patch).

## 🖥️ Node Hosts + Deploy (2026-07-13)

- **Compute Nodes / Model Hosts** (Settings → admin panel, `admin.js`): per-type host config —
  LLM URL, ComfyUI URL (image+video), 3D GPU host+SSH user, Audio/Music URL. `GET/POST
  /api/settings/nodes` writes to `.env` → **applies on restart** (config reads these env vars).
  The image/video shell scripts honor `$STORE_GPU_HOST` / `$STORE_COMFYUI_URL` (fallback = old IP).
- **GPU Node deploy** (`routers/node.py`, `deploy/node/node-setup.sh`, driven from the admin
  panel's GPU Node section): provisions the whole box (comfyui/video/3d/audio/lmstudio/services),
  Ubuntu-gated, live log. `setup_3d()` reuses ComfyUI torch, installs PyMCubes + TripoSR + TripoSG,
  and deploys the model3d scripts. Re-runnable/idempotent.

## 🎮 GPU & Model Management (READ BEFORE THE 2x 3060 UPGRADE)

The GPU box (`config.py` → `STORE_GPU_HOST`) shares one GPU between **LM Studio** (LLM)
and **ComfyUI** (image/video). The `orchestrator.py` scheduler serialises everything and
manages VRAM. Key behaviours:

- **Borrowing:** before an LLM task it runs `lms ps --json` and *borrows the model already
  loaded* (e.g. your OpenClaw model) instead of forcing a specific one. Falls back to
  `enhance_model` (Settings) / `STORE_ENHANCE_MODEL` only if nothing is loaded.
- **No thrash:** the LLM is **kept loaded** between LLM tasks. It's only unloaded when
  image/video gen actually needs the VRAM, and the evicted model is **restored** afterwards
  (when no LLM task is queued).
- **Queue:** all AI features (Assistant, library rip/guide/enrich/summarize/audit, security
  AI hunt, enhance/research/listing/price) go through `orch.submit_llm` — one at a time.

### ⚙️ Tuning for the 24 GB (dual RTX 3060) upgrade — do this after installing the 2nd card
Set these (in `.env` or environment), then restart:
```
STORE_GPU_VRAM_GB=24      # total VRAM across both cards
# STORE_GPU_EXCLUSIVE=0   # auto-derived: 0 when VRAM>=20, so LLM + image model COEXIST
```
With `GPU_EXCLUSIVE=0` the orchestrator **stops freeing ComfyUI / unloading the LLM for
image gen** — they run concurrently. (Video still frees the LLM: T5-XXL alone is ~9.5 GB.)
**Verify after upgrade:** kick an image gen while an LLM task runs; both should proceed
without the "waiting for LLM / freeing VRAM" log lines. If VRAM errors appear, set
`STORE_GPU_EXCLUSIVE=1` to go back to swapping.

### 🤖 AI Assistant vs OpenClaw agent_store
- The **AI Assistant tab** now runs on the **Store's own LLM** (borrows the loaded model via
  the orchestrator) — reliable, no OpenClaw dependency. See `routers/agent.py`.
- The full **OpenClaw `agent_store`** (web/browser/memory tools) is configured in
  `~/.openclaw/openclaw.json` (`"model": "lmstudio/google/gemma-4-12b-qat"`). That 12B model
  is too weak for its big tool schemas (gibberish/blocked) and can't load when a large model
  fills the GPU. To use the full agent, point it at a capable model there (you have
  `nvidia/z-ai/glm-5.2` and `anthropic/claude-sonnet-4-6` configured) — `--model` overrides
  are blocked by the agent's allowlist, so it must be changed in `openclaw.json`.

### 📥 Adding image/video/3D models
Catalogs live in `config.py`: `RECOMMENDED_MODELS` (image, ComfyUI checkpoints with a
`download_url`), `RECOMMENDED_VIDEO_MODELS` (video, HuggingFace diffusers `model_id`), and
`RECOMMENDED_3D_MODELS` (image→3D generators, with `install`/`script`/`license`/`commercial`).
Add a dict entry and it appears in the matching tab with a download/install button.
Good 24 GB picks already added: FLUX.1 schnell, Juggernaut XL, Wan2.1 14B, CogVideoX 5B,
Hunyuan Video. For 3D, TRELLIS especially benefits from the dual-3060 (24 GB).
**Note:** 2×3060 = 24 GB *total* but two 12 GB pools, not one — a single model still sees 12 GB
unless it shards; the real win is running LLM + image/3D concurrently (`STORE_GPU_VRAM_GB=24`).

## 💾 Model Storage on the SSD (2026-07-13)

The node's system drive was filling, so all model stores live on the **model SSD**
(`/media/user/SSD`, ntfs-3g but symlinks work), **separated by type** into sibling folders:

| Folder | Contents | Wiring |
|---|---|---|
| `models_llm/` (154G) | LM Studio models | **LM Studio must be re-linked to this path** |
| `models_image/` (20G) | ComfyUI checkpoints | `~/ComfyUI/models` symlinks here |
| `models_video/` (27G) | Wan2.1 etc. | `HF_HOME` in `generate_video.sh` (`STORE_HF_VIDEO`) |
| `models_audio/` (14G) | musicgen, mms-tts, ace-step | **wired:** `STORE_AUDIO_MODELS_DIR` → `HF_HOME=<dir>` + ACE `<dir>/ace-step` |
| `models_3d/` (17G) | TripoSR/TripoSG/Hunyuan/RMBG + TripoSG weights | `HF_HOME` in the 3D scripts (`STORE_HF_3D`) |

HuggingFace's cache is normally unified — the split works via **per-type `HF_HOME`** (config
`NODE_HF_VIDEO/AUDIO/3D`). Each pipeline's download AND generation point at its own folder.
`node-setup.sh` → `relocate_models_to_ssd()` maintains this (idempotent; `STORE_MODELS_SSD` or the
`/media/user/SSD` mount). Freed ~69G on the system drive (68G→137G). The SSD's `.Trash-1000`
(~23G) can be emptied for more.

<a name="audio"></a>
## 🎵 Audio / Music + Video Sound (2026-07-13)

Music & voice generate on the node via `~/store_audiogen.py` (invoked over SSH by
`services._node_audio`, always inside `orch.video_acquire()` so the LLM's VRAM is freed
first — else CUDA OOM). Engines:

| Engine | Kind | Model | venv |
|---|---|---|---|
| MusicGen (small/med) | music | `facebook/musicgen-*` | ComfyUI venv (`transformers`) |
| MMS-TTS | voice | `facebook/mms-tts-eng` | ComfyUI venv (Bark rejected: needs torch ≥2.6) |
| Stable Audio Open | music | `stabilityai/stable-audio-open-1.0` (gated — HF token) | ComfyUI venv (diffusers) |
| **ACE-Step** | songs + vocals + **lyrics** | `ACE-Step/ACE-Step-v1-3.5B` (~8 GB) | **own venv `~/ace-venv`** |

**ACE-Step gotchas** (all fixed): venv must NOT be named `~/acestep` (shadows the package);
run adds `~/ACE-Step` to `sys.path` (script-by-path doesn't get cwd on path); its torchaudio
2.11 saves via **torchcodec** (install `soundfile` + `torchcodec`). Lyrics use
`[verse]`/`[chorus]` tags; empty = instrumental. Storage: `STORE_AUDIO_MODELS_DIR`.

**Surfaces:** the **Music/Audio** tab (standalone clips + ✨ AI prompt-enhance + engine-aware
lengths to 4 min), **Audio Models** cards in the Models tab (download/install), and **🎵 Add
sound** on finished videos — the **video→audio bridge** generates music (+optional narration)
and ffmpeg-muxes it (music looped/ducked under voice, trimmed to length).

<a name="coordination"></a>
## 🚦 One GPU, many jobs — queue + restart coordination (2026-07-13)

All heavy GPU work (LLM / image / video / 3D / audio) serializes on the orchestrator's
`_active_images` counter — a queued job waits (up to `STORE_GPU_QUEUE_TIMEOUT`, default
**1800s**) for the GPU to free, so jobs never collide on the single card. The **LLM model**
is picked in Settings → Compute Nodes (`enhance_model`; `/api/settings/llm-models` lists LM
Studio's models; applied per-task, no restart). **Restarting the store kills in-flight
generations** (reconciled to `failed`), so Settings shows a live **"⏳ GPU busy — N job(s)"**
banner and `POST /api/system/restart` returns **409** unless `force` — check
`/api/system/gpu-status` before restarting (matters with 2 people/agents).

LM Studio autostart on the node is a systemd **user** unit tied to `graphical-session.target`
with `DISPLAY=:0` + `--bind 0.0.0.0` (fixes the boot-time error dialog + LAN reachability).

<a name="logs"></a>
## 📜 Store Logs + error handling (2026-07-13)

`main._setup_file_logging()` writes a rotating log to `<data-dir>/logs/store.log`
(2 MB × 3), capturing the `store` + `orch` loggers and uvicorn errors. A global
`@app.exception_handler(Exception)` logs every unhandled endpoint failure with its
method+path+traceback (so silent-except failures still surface). **Settings → Store
Logs** = `/api/system/logs` (level filter + text search + error/warning tally).

<a name="llmpick"></a>
## 🧠 LLM model picker (2026-07-13)

Settings → Compute Nodes has a model dropdown. `/api/settings/llm-models` lists LM
Studio's models (LLMs vs embeddings); picking one PATCHes `enhance_model`, which the
orchestrator reads per task — applies to the next generation, no restart.

<a name="archive"></a>
## 🗃 Web Archive — save any page (2026-07-13)

`library.capture_snapshot(url)` escalates **HTTP fetch → `wget` → the persistent
logged-in Store browser** (`browser.py`); the last carries your real session so it
clears Cloudflare where the old headless `--dump-dom` couldn't. Or
`POST /api/library/archive/upload` a page you saved yourself (File → Save Page As →
.html) — scripts neutralized, `<base>` added, stored as a normal snapshot version.
All paths feed `_store_snapshot()` + the in-store iframe viewer.

<a name="modular"></a>
## 🧩 Modular layout (2026-07-13)

Big files were split so each stays editable (local-model-friendly): `index.html` (2276→
614) extracted `app-main.js`, which further split `tab-models.js` + `tab-settings.js`;
`services.py` (1318→643) re-exports `services_media.py` (video+audio, with `__all__` so
underscored helpers stay importable); `resell.py` (1074→527) + `resell_browser.py` are
two routers; `tab-resell.js` split off `tab-resell-browser.js`. Backend uses re-export /
second-router; frontend uses ordered `<script>` loads.

## 🌐 Portal → WordPress (2026-07-13)
The **Portal → WordPress** tab pushes what you promote to the **example.com WooCommerce**
store. Curate-then-push: tick items, click push — nothing goes live without a click.
- **Products** → WooCommerce "external/affiliate" products (Buy button links OUT to Amazon/
  Etsy/Cults3D/your software). Uses the WooCommerce REST API over **HTTPS** with Basic Auth
  (consumer key/secret). MUST be the public https URL — WooCommerce rejects Basic auth over
  plain http (`localhost:8090` would demand OAuth-1.0a).
- **Media** → a Portfolio gallery page. Generated images/videos upload via the WordPress MCP
  endpoint (Bearer token, base64) — no public URL needed.
- **7 sources**: affiliate + software (entered in the tab), live Etsy/Printify/Cults3D
  listings, and generated images/videos. Etsy auto-refreshes its ~1h OAuth token.
- **Creds**: enter in the tab (Portal → WordPress connection panel, stored in the DB) *or*
  pre-seed via `.env` (`STORE_WP_URL`, `STORE_WP_CONSUMER_KEY`, `STORE_WP_CONSUMER_SECRET`,
  `STORE_WP_MCP_URL`, `STORE_WP_MCP_TOKEN`). Code: `app/wc_client.py`, `app/routers/portal.py`,
  `static/js/tab-portal.js`.

## 🌿 Git / GitHub workflow — READ THIS (2026-07-13)
Three branches, each a **git worktree** (a separate folder sharing one history), so all three
can run at once on different ports:

| Branch  | Folder                                  | Port | URL              | Purpose |
|---------|-----------------------------------------|------|------------------|---------|
| `master`| `platform_dev/store`                    | 8787 | `/store`         | **Live personal app.** Claude works here. Keeps all creds (in `store.db`, untracked). |
| `dev`   | `projects/store-dev`                    | 8788 | `/store-dev`     | **Local-model experiments.** Own venv + DB. Break it freely — `master` is untouched. |
| `retail`| `projects/store-retail`                 | —    | —                | **Clean distributable.** No creds, genericized defaults, for sharing. |

**Golden rules**
- **`store.db` and `.env` are gitignored** — they hold every credential and are NEVER committed.
  A fresh empty DB is created on first run. This is why retail is safe to share.
- Each worktree has its **own** `.env` + `store.db` (via `STORE_DATA_DIR`) → isolated data.
- Services: `systemctl --user {status|restart} store.service` (main) / `store-dev.service` (dev).
  Both are linger-enabled (survive reboot). The Settings → "Restart Server" button uses systemd.

**Daily flow**
```bash
# experiment on dev (won't touch the live app)
cd ~/projects/store-dev && git add -A && git commit -m "try new local model"
# ...test at http://localhost:8787/store-dev/ ...

# promote working dev work up to master (the live app)
cd ~/projects/platform_dev/store
git merge dev            # or: git cherry-pick <commit>
systemctl --user restart store.service     # ship it

# refresh the shareable retail copy from master, keep it clean
cd ~/projects/store-retail
git reset --hard master
# re-genericize the 5 defaults in app/config.py (APP_NAME, GPU_HOST, GPU_SSH_USER,
#   PUBLIC_BASE_URL) if the reset overwrote them, then:
git add -A && git commit -m "sync retail + genericize"
```

**GitHub (private repo)**
```bash
gh auth login                                  # one-time; browser flow
gh repo create store-command-center --private --source=. --remote=origin
git push -u origin master && git push origin dev retail
```
The whole repo is private (visibility is per-repo, not per-branch). To share **retail** publicly
later: either `git archive retail -o store.zip` (a clean snapshot, no history) or push the retail
branch to a *separate* public repo. Never make this repo public — its history predates the scrub
only for non-secret personal refs; creds are already purged.

**Before any push:** `git grep -nE "wpmcp_|ck_[0-9a-f]{30}|<your-passwords>"` should return nothing.

## ⚠️ Known Issues
- **WP Plugin:** Superseded — the Portal → WordPress tab now drives WooCommerce directly.
- **Pihole Security Tab:** Orphaned scanner, no automated remediation
- **Hardcoded Price Logic:** `fix_etsy_prices.py` uses hardcoded $25.00 → $15.99
- **Settings API:** Returns `_auth_secret` and `_auth_password_hash` (should be filtered)
- ~~3D "Installed" badge is weak~~ — RESOLVED: per-model "Test" button runs a real
  one-shot generation → pass/fail (`test3dModel`).
- ~~SF3D needs a HuggingFace token~~ — RESOLVED: HF-token field in Settings → Compute
  Nodes (passed to gated 3D/audio downloads).
- **Cults3D `createCreation`** may require a `categoryId` (not sent yet) — first real publish
  will confirm; add a category picker if it rejects.
- **ZIP backlog files** without a top-level mesh can't be auto-rendered (handled: shows an error
  on the card). Hunyuan3D-2 mini was removed (non-commercial + broken loader).

## 🏛️ The Company runs the store — autonomous system (2026-07-14)

"The game runs the store." The Company (World tab) isn't just a pixel town — it's
the autonomous operator of the whole business. It creates, strategizes, learns,
publishes, and earns on its own. **Nothing real or costly ever happens without
your blessing** — that's the spine of the design.

**The control surfaces** (World tab HUD + the Treasury nav tab):
- **🎛️ Control** — Mission Control. A MASTER switch for the whole Company, a
  toggle for every autonomy system (create, self-govern, crew thinking, meetings,
  incidents, autonomous listing, dev-swarm cron, security), and CAPABILITIES (a
  "mini-MCP") you can trigger on demand: make art/music/video/3D, convene the
  assembly, commission research, scan trends, list on Etsy/Printify.
- **🏛️ God Console** — the prayer (approval) queue + budget + community board.
- **🏛️ Republic** — the survival strategy engine: assess → the citizens vote →
  a mandate → real actions. Self-convenes on a heartbeat when automation is on.
- **📖 Bible** — scripture. The **Word is this very BOOK.md**; the Teachings are
  what scholar-agents research and record (blessed research prayers).
- **📋 Info Board** / **🗂️ Workboard** — the collage of new creations, and the
  whole pipeline (mandate → awaiting-you → done).
- **🏦 Treasury** (nav tab) — the national gold: real-money ledger, PayPal
  manager, survival health, full transaction history.

**The safety model** (why it can run unattended):
- **Prayers** — an agent wanting a real/costly action files a prayer; you bless
  or deny. `automation_mode`: *review* (all wait) or *budget* (free + within-cap
  run; over-cap waits).
- **ALWAYS_GATE** = `{paypal_payout, add_software, post_etsy, post_printify}` —
  real money, code changes, and public paid listings NEVER auto-run, even in
  budget mode.
- **Budget** — a postpaid ledger like Etsy bills you. Only Etsy/Printify ($0.20)
  cost; WordPress + Cults3D publishing are free. Cults3D/store earnings fund it;
  a monthly cap gates spend.
- **Two-deaths ethos** — ☢️ catastrophe (one bad line nukes the project → code
  gated hard) and 💀 stagnation (doing nothing decays national standing). Act
  boldly, with safeguards.

**Money flow:** create (free, local GPU) → publish free to WordPress + Cults3D →
list paid on Etsy/Printify (blessed) → earnings credit the treasury → when in
profit, the Company pays YOU via PayPal Payouts (blessed, Live once real keys are
set). Payout receiver = the app-identity email, not the Claude login.

**File map** (all decoupled from the world sim — own tables + own JS modules):
- `app/world_ops.py` — pray()/budget ledger (table `world_ops_ledger`, NOT the
  sim's `world_ledger`)/messages + executor registry.
- `app/world_strategy.py` — the Republic. `app/world_bible.py` — the Bible.
- `app/world_auto.py` — creation loop (image/music/video/3D) + governance + sell
  heartbeats. `app/world_sell.py` — Etsy/Printify listings.
- `app/world_control.py` — the control plane (master cascades into each system's
  native setting; non-invasive). `app/paypal_client.py` — PayPal.
- `app/routers/world_ops.py` — `/api/world/ops/*`, `/api/world/republic/*`,
  `/api/world/bible/*`, `/api/world/control/*`.
- JS: `world-god/republic/bible/board/workboard/control.js`, `tab-treasury.js`.

**Gotchas:** classic scripts — `api()` does NOT stringify bodies (use
`JSON.stringify`); `world-god.js` consts are bare globals, not on `window`;
`get_conn()` sets `busy_timeout=5000` (many concurrent writers now); the Etsy key
setting is `etsy_key`, Printify is `printify_key` (not `*_api_key`).

---

## 🧠 OpenClaw long-context fix — LLM proxy consumers READ THIS (2026-07-18)

Long OpenClaw chats were dying with `Context overflow: prompt too large for the model
(precheck)` / `estimated context size exceeds safe threshold` and compaction timeouts.
Root cause: **LM Studio on the node loads `google/gemma-4-12b-qat` at contextLength
115000** (`~/.lmstudio/.internal/user-concrete-model-default-config/google/gemma-4-12b-qat.json`),
but OpenClaw's config claimed a 262144 window with a 1,000,000-token agent default —
so sessions grew past 115k before compaction ever fired (overflow diag showed
`compactionTokens=115001`, one token over the real limit).

Fixes (in `~/.openclaw/openclaw.json`, backup `openclaw.json.bak-ctxfix-2026-07-18`):
- `agents.defaults.contextTokens`: 1000000 → **100000** (headroom under 115k).
- `models.providers.lmstudio.models[*].contextWindow` set to the node's REAL
  LM Studio load values: gemma-4-12b-qat / qwen3.5-9b / ministral-3-3b = 115000;
  glm-4.6v-flash = 131072; qwen3-coder-30b + gemma-4-12b-it-qat-cpu = 262144;
  qwen2.5-coder-32b / gemma-4-26b(-qat) / qwen3.6-35b / others without node
  config = 8192 (conservative).
- `agents.defaults.contextInjection`: always → **continuation-skip** (bootstrap
  files no longer re-injected on safe continuation turns). Toggle back with
  `openclaw config patch` if unwanted.
- `agents.defaults.compaction.reserveTokens` = 12000.
- Workspace bootstrap slimmed: injected set (AGENTS/SOUL/TOOLS/IDENTITY/USER/
  HEARTBEAT/MEMORY.md) 25.0k → **10.8k chars**; bulk detail moved to
  `memory/etiquette-heartbeats.md` + `memory/promotions-archive-2026-07.md`.

**Rules going forward:** if you change a model's context length in LM Studio on the
node, mirror it in `models.providers.lmstudio.models[].contextWindow` — the proxy
passes bodies verbatim and cannot clamp for you. Anything driving the proxy
(`/api/llm/v1`) should keep prompts ≤ ~100k tokens for the local models.

---

*This is a nested book within the main Platform Dev Book.*
