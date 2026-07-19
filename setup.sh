#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Store Command Center — setup / installer
#
# Bootstraps the store itself (venv, deps, .env, database) and can OPTIONALLY
# fetch the GPU-side tools it talks to (ComfyUI + LM Studio).
#
#   ./setup.sh                    # store bootstrap only
#   ./setup.sh --with-comfyui     # + clone & install ComfyUI
#   ./setup.sh --with-lmstudio    # + download LM Studio AppImage
#   ./setup.sh --with-graphify    # + install Graphify + build the Knowledge Graph
#   ./setup.sh --with-dev         # + test/verify tooling (pytest, playwright)
#   ./setup.sh --service          # + install the systemd --user unit (store.service)
#   ./setup.sh --all              # everything above
#
# The ComfyUI / LM Studio bits are best-effort and belong on your GPU machine
# (STORE_GPU_HOST) — the full GPU-node stack (image/video/3D/audio/LLM services,
# gpu-guard, JellyMiner) is provisioned separately by deploy/node/node-setup.sh,
# driven from Settings → GPU Node in the UI. Re-running is safe — existing pieces
# are skipped, and a post-install checklist of the manual bits prints at the end.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

WITH_COMFYUI=0; WITH_LMSTUDIO=0; WITH_GRAPHIFY=0; WITH_DEV=0; WITH_SERVICE=0
for arg in "$@"; do
  case "$arg" in
    --with-comfyui)  WITH_COMFYUI=1 ;;
    --with-lmstudio) WITH_LMSTUDIO=1 ;;
    --with-graphify) WITH_GRAPHIFY=1 ;;
    --with-dev)      WITH_DEV=1 ;;
    --service)       WITH_SERVICE=1 ;;
    --all)           WITH_COMFYUI=1; WITH_LMSTUDIO=1; WITH_GRAPHIFY=1; WITH_DEV=1; WITH_SERVICE=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

c_g="\033[32m"; c_y="\033[33m"; c_b="\033[36m"; c_r="\033[31m"; c_0="\033[0m"
info() { echo -e "${c_b}==>${c_0} $*"; }
ok()   { echo -e "${c_g} ✓${c_0} $*"; }
warn() { echo -e "${c_y} !${c_0} $*"; }
die()  { echo -e "${c_r} ✗${c_0} $*"; exit 1; }

# ── 0. Prerequisites ─────────────────────────────────────────────────────────
info "Checking prerequisites"
command -v python3 >/dev/null || die "python3 not found — install Python 3.10+"
command -v git     >/dev/null || warn "git not found (needed for --with-comfyui + the GitHub tab)"
command -v node    >/dev/null || warn "node not found (only needed for tools/verify_spa.sh JS checks)"
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
ok "python3 $PYV"

# ── 1. Virtualenv + dependencies ─────────────────────────────────────────────
info "Setting up Python virtualenv"
if [[ ! -d venv ]]; then
  python3 -m venv venv
  ok "created venv/"
else
  ok "venv/ already exists"
fi
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
ok "dependencies installed"

# ── 2. .env ──────────────────────────────────────────────────────────────────
info "Configuration (.env)"
if [[ ! -f .env ]]; then
  cp .env.example .env
  ok "created .env from .env.example"
  warn "Edit .env — set STORE_GPU_HOST, STORE_PUBLIC_URL, and your API keys."
else
  ok ".env already exists (left untouched)"
fi

# ── 3. Database ──────────────────────────────────────────────────────────────
info "Initializing database"
( cd app && ../venv/bin/python -c "from db import init_db; init_db()" )
ok "store.db ready"

# ── 3b. Runtime data directories ─────────────────────────────────────────────
# Everything the app writes at runtime, pre-created so a read-only first render
# never 404s. All are also auto-created lazily; this is the belt to that suspenders.
# Honors STORE_DATA_DIR (defaults to the repo root, matching app/config.py).
info "Creating runtime data directories"
DATA_DIR="${STORE_DATA_DIR:-$SCRIPT_DIR}"
for d in designs/pending designs/approved designs/rejected videos backups archive \
         logs models3d/generated models3d/renders mail_attachments world_audio \
         research_media; do
  mkdir -p "$DATA_DIR/$d"
done
ok "data dirs ready under $DATA_DIR"

# ── 3c. (optional) Dev / verification tooling ────────────────────────────────
if [[ "$WITH_DEV" == "1" ]]; then
  info "Installing dev tooling (pytest + playwright)"
  ./venv/bin/pip install --quiet -r requirements-dev.txt \
    && ok "dev deps installed (./run_tests.sh now works)" \
    || warn "dev deps install failed (needs network) — ./run_tests.sh will not run"
  # headless chromium for tests/ui_regression.py + browser-verify (big download; best-effort)
  ./venv/bin/playwright install chromium >/dev/null 2>&1 \
    && ok "playwright chromium installed" \
    || warn "playwright chromium download skipped/failed — run: ./venv/bin/playwright install chromium"
fi

# ── 3d. (optional) systemd --user service ────────────────────────────────────
if [[ "$WITH_SERVICE" == "1" ]]; then
  info "Installing systemd --user unit (store.service)"
  if command -v systemctl >/dev/null 2>&1; then
    UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
    sed "s#<ABSOLUTE_PATH_TO>/store#$SCRIPT_DIR#g" deploy/store.service > "$UNIT_DIR/store.service"
    systemctl --user daemon-reload || true
    systemctl --user enable store.service >/dev/null 2>&1 || true
    if systemctl --user is-active store.service >/dev/null 2>&1; then
      ok "store.service already running — unit refreshed, NOT restarted (restart it when ready)"
    else
      ok "store.service installed + enabled — start it with: systemctl --user start store.service"
      loginctl enable-linger "$USER" >/dev/null 2>&1 || true
    fi
  else
    warn "systemctl not found — run ./run.sh directly, or see deploy/store.service"
  fi
fi

# ── 4. (optional) ComfyUI ────────────────────────────────────────────────────
if [[ "$WITH_COMFYUI" == "1" ]]; then
  info "Installing ComfyUI (image/video backend)"
  COMFY_DIR="${COMFYUI_DIR:-$HOME/ComfyUI}"
  if [[ -d "$COMFY_DIR/.git" ]]; then
    ok "ComfyUI already present at $COMFY_DIR"
  else
    git clone --depth 1 https://github.com/comfyanonymous/ComfyUI "$COMFY_DIR" \
      && ok "cloned ComfyUI -> $COMFY_DIR" || warn "ComfyUI clone failed"
  fi
  if [[ -f "$COMFY_DIR/requirements.txt" ]]; then
    python3 -m venv "$COMFY_DIR/venv" 2>/dev/null || true
    warn "Install ComfyUI deps + a GPU build of PyTorch manually:"
    echo "    $COMFY_DIR/venv/bin/pip install -r $COMFY_DIR/requirements.txt"
    echo "    (choose the torch build matching your CUDA/ROCm: https://pytorch.org/get-started)"
    echo "    then run:  cd $COMFY_DIR && ./venv/bin/python main.py --listen 0.0.0.0 --port 8188"
  fi
fi

# ── 5. (optional) LM Studio ──────────────────────────────────────────────────
if [[ "$WITH_LMSTUDIO" == "1" ]]; then
  info "Downloading LM Studio (LLM backend)"
  APPS="${LMSTUDIO_DIR:-$HOME/Applications}"; mkdir -p "$APPS"
  if ls "$APPS"/LM*Studio*.AppImage >/dev/null 2>&1; then
    ok "LM Studio AppImage already in $APPS"
  else
    warn "LM Studio is a desktop app — download the latest build for your OS from:"
    echo "    https://lmstudio.ai/download"
    echo "  Then in LM Studio: load a model, enable the local server on port 1234,"
    echo "  and set STORE_LLM_URL / STORE_ENHANCE_MODEL in .env to match."
  fi
fi

# ── 6. (optional) Graphify — Knowledge Graph tab ─────────────────────────────
if [ "$WITH_GRAPHIFY" = 1 ]; then
  info "Setting up Graphify (Knowledge Graph)…"
  GV="$SCRIPT_DIR/../graphify-venv"
  if [ ! -x "$GV/bin/graphify" ]; then
    python3 -m venv "$GV" && "$GV/bin/pip" install --quiet --upgrade pip && "$GV/bin/pip" install --quiet graphifyy \
      && ok "graphify installed → $GV" || warn "graphify install failed (needs network)"
  else
    ok "graphify already installed"
  fi
  if [ -x "$GV/bin/graphify" ]; then
    [ -f .graphifyignore ] || printf 'venv/\ngraphify-venv/\nnode_modules/\ndesigns/\nvideos/\naudio/\nmodels3d/\narchive/\nbackups/\nlogs/\nworld_assets/packs/\n*.db\n*.png\n*.mp4\n*.safetensors\ngraphify-out/\n' > .graphifyignore
    "$GV/bin/graphify" update . >/dev/null 2>&1 && "$GV/bin/graphify" tree --label "The Company / Store" >/dev/null 2>&1 \
      && ok "knowledge graph built → graphify-out/" || warn "graph build had issues (rebuild from the Knowledge Graph tab)"
    "$GV/bin/graphify" install --platform claude >/dev/null 2>&1 || true   # /graphify for Claude Code
    "$GV/bin/graphify" install --platform claw   >/dev/null 2>&1 || true   # /graphify for OpenClaw
    ok "graphify skill registered for Claude Code + OpenClaw"
  fi
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo
ok "Setup complete."
echo
echo "Next steps:"
echo "  1. Edit .env         (GPU host, public URL, API keys)"
echo "  2. Start the server: ./run.sh    (http://localhost:\${STORE_PORT:-8787})"
echo "     (or as a service: ./setup.sh --service, then systemctl --user start store.service)"
echo "  3. First login password is 'store' — change it in Settings."
echo "  4. In Settings → System → GitHub: sign in with a token, then click"
echo "     'Make this install yours' — it creates YOUR private repo (origin)"
echo "     and keeps the repo you cloned as 'upstream' for updates."
echo
echo "Post-install checklist — things setup can't do for you:"
echo "  □ Reverse proxy: the app expects to live under a path prefix (default /store)."
echo "    nginx snippet is in README.md; a Caddy example is in deploy/caddy/Caddyfile.example."
echo "  □ GPU node (Ubuntu + NVIDIA box at STORE_GPU_HOST): deploy the full model stack"
echo "    (ComfyUI image, diffusers video, TripoSR 3D, MusicGen audio, LM Studio LLM,"
echo "    plus gpu-guard + JellyMiner services) from Settings → GPU Node → Deploy/Update,"
echo "    or on the node itself: deploy/node/node-setup.sh deploy [--with-audio]."
echo "    gpu-guard auto-pauses the unified AI queue while a Steam game / heavy GPU app"
echo "    runs on the node, and starts/stops the miner around AI work."
echo "  □ Models (not bundled — large): an SDXL checkpoint into ComfyUI models/checkpoints,"
echo "    an LLM via LM Studio (lms get <model> --gguf), and accept any gated HuggingFace"
echo "    licenses on the node for audio models (e.g. Stable Audio) before first use."
echo "  □ JellyCoin mining rigs: token + run command in the UI under Crypto → JellyCoin →"
echo "    Mining; per-rig install recipe in miner/README.md (miner/requirements.txt)."
echo "  □ Pearl mining (optional): install the OFFICIAL Pearl miner yourself on the miner"
echo "    host and wrap it in a systemd --user unit named 'pearl-miner' (Crypto → Pearl"
echo "    explains; the tab only start/stops that unit — it never installs miners)."
echo "  □ Research tab web/image search: needs a local searxng instance on :8899"
echo "    (e.g. docker run -d -p 8899:8080 searxng/searxng)."
echo "  □ Crypto extras (all optional, function-gated): bitcoind regtest, freqtrade"
echo "    dry-run, monero-wallet-rpc — paths/URLs configurable via STORE_* env vars."
echo "  □ External accounts: Printify / Etsy / Cults3D / PayPal / Square (Cash App) /"
echo "    WordPress-WooCommerce keys go in .env or Settings once the app is up."
echo "  □ OpenClaw/MCP: the full API auto-mounts as MCP tools at /api/mcp — nothing to"
echo "    install; point your MCP client at http://localhost:\${STORE_PORT:-8787}/api/mcp."
if [[ "$WITH_GRAPHIFY" != "1" ]]; then
  echo "  □ Knowledge Graph tab: run ./setup.sh --with-graphify to install graphify and"
  echo "    build the repo graph (also registers the /graphify skill for Claude/OpenClaw)."
fi
if [[ "$WITH_DEV" != "1" ]]; then
  echo "  □ Tests/verify tooling: ./setup.sh --with-dev installs pytest + playwright."
fi
