#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# JellyMiner — standalone installer
#
# Installs ONLY the JellyCoin GPU miner: its own venv, the OpenCL loader, the
# miner script, and (optionally) a systemd user service that survives reboots.
#
# This is deliberately NOT node-setup.sh. That script provisions a full Store GPU
# node — ComfyUI, LM Studio, video, 3D — which is far too much to ask of someone
# who just wants to point a spare graphics card at a friend's network. Everything
# here is idempotent: re-run it any time.
#
#   Fresh box, one line (the Store serves this script):
#     curl -sSL http://<store-host>:8787/api/jelly/mining/install-miner.sh \
#       | bash -s -- --url http://<store-host>:8787 --token <TOKEN> --name rig1
#
#   Or locally:
#     ./install-miner.sh --url http://<store-host>:8787 --token <TOKEN> --name rig1
#     ./install-miner.sh check          # report what's installed, change nothing
#     ./install-miner.sh uninstall      # remove the service + venv (keeps nothing)
#
# Get <TOKEN> from the Store UI: Crypto → 🪼 JellyCoin → Mining.
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

MODE="install"
URL=""; TOKEN=""; NAME="$(hostname -s 2>/dev/null || echo rig)"
THROTTLE=""; DEVICE=""; NO_SERVICE=0

VENV="$HOME/jellyminer-venv"
SCRIPT="$HOME/jellyminer.py"
UNITS="$HOME/.config/systemd/user"
UNIT="$UNITS/jellyminer.service"
ENVF="$HOME/.config/store-node.env"
LOG="${TMPDIR:-/tmp}/install-miner.log"

C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_0=$'\033[0m'
ok(){   printf '%s  ✓ %s%s\n' "$C_OK"   "$*" "$C_0"; }
warn(){ printf '%s  ! %s%s\n' "$C_WARN" "$*" "$C_0"; }
err(){  printf '%s  ✗ %s%s\n' "$C_ERR"  "$*" "$C_0"; }
info(){ printf '\n%s▸ %s%s\n' "$C_DIM" "$*" "$C_0"; }

while [ $# -gt 0 ]; do
  case "$1" in
    install|check|uninstall) MODE="$1" ;;
    --url)      URL="${2:-}"; shift ;;
    --token)    TOKEN="${2:-}"; shift ;;
    --name)     NAME="${2:-}"; shift ;;
    --throttle) THROTTLE="${2:-}"; shift ;;
    --device)   DEVICE="${2:-}"; shift ;;
    --no-service) NO_SERVICE=1 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) err "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

# ── uninstall ────────────────────────────────────────────────────────────────
if [ "$MODE" = "uninstall" ]; then
  info "Removing JellyMiner"
  systemctl --user stop    jellyminer.service >/dev/null 2>&1
  systemctl --user disable jellyminer.service >/dev/null 2>&1
  rm -f "$UNIT" && ok "service removed"
  systemctl --user daemon-reload >/dev/null 2>&1
  rm -rf "$VENV" && ok "venv removed"
  rm -f "$SCRIPT" && ok "miner script removed"
  warn "left $ENVF alone — it may hold config for other node services"
  exit 0
fi

# ── check ────────────────────────────────────────────────────────────────────
gpu_report(){
  if [ -x "$VENV/bin/python" ]; then
    "$VENV/bin/python" "$SCRIPT" --list 2>/dev/null | sed 's/^/     /' && return 0
  fi
  return 1
}

if [ "$MODE" = "check" ]; then
  info "JellyMiner status"
  [ -x "$VENV/bin/python" ] && ok "venv       $VENV" || warn "venv       not installed"
  [ -f "$SCRIPT" ]          && ok "miner      $SCRIPT" || warn "miner      not installed"
  if ldconfig -p 2>/dev/null | grep -q libOpenCL; then ok "OpenCL     loader present"
  else warn "OpenCL     libOpenCL missing"; fi
  if [ -f "$UNIT" ]; then
    ok "service    installed"
    printf '     %s\n' "$(systemctl --user is-active jellyminer.service 2>/dev/null || echo inactive)"
  else warn "service    not installed"; fi
  info "GPUs the miner can see"
  gpu_report || warn "could not enumerate — install first, or no OpenCL GPU present"
  exit 0
fi

# ── install ──────────────────────────────────────────────────────────────────
info "JellyMiner installer"

if [ -z "$URL" ]; then
  err "--url is required (your Store, or the buddy's node you're mining for)"
  echo "   e.g. --url http://192.168.1.50:8787 --token <TOKEN> --name rig1"
  exit 2
fi
URL="${URL%/}"

# 1. python3 + venv module
if ! command -v python3 >/dev/null 2>&1; then
  err "python3 not found — install it first (apt install python3 python3-venv)"; exit 1
fi

# 2. OpenCL loader. The GPU driver ships the ICD (the actual implementation); this
#    is only the dispatcher that finds it. Without it pyopencl imports but sees no
#    devices, which looks like "no GPU" and sends people down the wrong rabbit hole.
if ! ldconfig -p 2>/dev/null | grep -q libOpenCL; then
  info "Installing the OpenCL loader"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y ocl-icd-libopencl1 clinfo >>"$LOG" 2>&1 \
      && ok "ocl-icd-libopencl1 installed" \
      || warn "could not install ocl-icd-libopencl1 — see $LOG"
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y ocl-icd clinfo >>"$LOG" 2>&1 && ok "ocl-icd installed" || warn "see $LOG"
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm ocl-icd clinfo >>"$LOG" 2>&1 && ok "ocl-icd installed" || warn "see $LOG"
  else
    warn "unknown package manager — install an OpenCL ICD loader by hand"
  fi
else
  ok "OpenCL loader already present"
fi

if [ ! -d /etc/OpenCL/vendors ] || [ -z "$(ls -A /etc/OpenCL/vendors 2>/dev/null)" ]; then
  warn "no OpenCL vendor ICD in /etc/OpenCL/vendors — your GPU driver provides this."
  warn "NVIDIA: the proprietary driver (incl. legacy 390/470) ships it."
  warn "AMD: apt install mesa-opencl-icd   ·   Intel: apt install intel-opencl-icd"
fi

# 3. venv, kept separate from any AI venvs on the box
info "Python environment"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" >>"$LOG" 2>&1 || { err "venv creation failed — see $LOG"; exit 1; }
  ok "created $VENV"
else
  ok "venv already present"
fi
"$VENV/bin/pip" install -q --upgrade pip >>"$LOG" 2>&1
if "$VENV/bin/python" -c "import pyopencl, numpy, requests" >/dev/null 2>&1; then
  ok "pyopencl / numpy / requests already installed"
else
  echo "     installing pyopencl numpy requests (this can take a minute)…"
  "$VENV/bin/pip" install -q pyopencl numpy requests >>"$LOG" 2>&1 \
    && ok "dependencies installed" \
    || { err "pip install failed — see $LOG"; exit 1; }
fi

# 4. the miner itself — always pulled from the node we'll mine for, so the script
#    matches that node's protocol rather than drifting from a stale copy.
info "Miner script"
if [ -f "$(dirname "$0")/jellyminer.py" ]; then
  install -m 644 "$(dirname "$0")/jellyminer.py" "$SCRIPT" && ok "installed from local bundle"
elif command -v curl >/dev/null 2>&1 && curl -fsSL "$URL/api/jelly/mining/miner.py" -o "$SCRIPT.tmp" 2>>"$LOG"; then
  mv "$SCRIPT.tmp" "$SCRIPT" && ok "downloaded from $URL"
else
  rm -f "$SCRIPT.tmp"
  err "could not obtain jellyminer.py (tried the local bundle and $URL)"; exit 1
fi

# 5. can it actually see a GPU? Say so now rather than letting the service fail later.
info "GPUs the miner can see"
if "$VENV/bin/python" "$SCRIPT" --list 2>/dev/null | sed 's/^/     /' | grep -q .; then
  "$VENV/bin/python" "$SCRIPT" --list 2>/dev/null | sed 's/^/     /'
else
  warn "no OpenCL GPU found. The miner will not start until a driver + ICD are in place."
  warn "'clinfo' is the tool to debug this. CPUs are excluded by design — that is not a bug."
fi

# 6. service (opt-out) — env-file driven so the token never lands in the unit
RUN="$VENV/bin/python $SCRIPT --url $URL --name $NAME"
[ -n "$TOKEN" ]    && RUN="$RUN --token $TOKEN"
[ -n "$THROTTLE" ] && RUN="$RUN --throttle $THROTTLE"
[ -n "$DEVICE" ]   && RUN="$RUN --device $DEVICE"

if [ "$NO_SERVICE" = "1" ]; then
  info "Skipping the service (--no-service). Run it by hand:"
  echo "     $RUN"
  exit 0
fi

if ! command -v systemctl >/dev/null 2>&1; then
  info "No systemd here. Run the miner by hand:"
  echo "     $RUN"
  exit 0
fi

info "Service"
mkdir -p "$UNITS" "$(dirname "$ENVF")"
touch "$ENVF"; chmod 600 "$ENVF"
_envf_set(){                       # keep other node services' keys intact
  local k="$1" v="$2"
  if grep -q "^$k=" "$ENVF" 2>/dev/null; then
    sed -i "s#^$k=.*#$k=$v#" "$ENVF"
  else
    printf '%s=%s\n' "$k" "$v" >> "$ENVF"
  fi
}
_envf_set STORE_URL "$URL"
[ -n "$TOKEN" ] && _envf_set JELLY_TOKEN "$TOKEN"

if [ -f "$UNIT" ]; then
  ok "jellyminer.service already exists — left untouched (it may carry your own edits)"
  echo "     remove it first if you want this installer to rewrite it"
else
  EXTRA=""
  [ -n "$THROTTLE" ] && EXTRA="$EXTRA --throttle $THROTTLE"
  [ -n "$DEVICE" ]   && EXTRA="$EXTRA --device $DEVICE"
  cat > "$UNIT" <<EOF
# JellyMiner — JellyCoin GPU miner. Written by install-miner.sh.
# STORE_URL and JELLY_TOKEN come from $ENVF (mode 600), so the token is not in
# this unit file. Change the node you mine for by editing that file.
[Unit]
Description=JellyMiner — JellyCoin GPU miner
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=$ENVF
ExecStart=$VENV/bin/python $SCRIPT --url \${STORE_URL} --token \${JELLY_TOKEN} --name $NAME$EXTRA
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
EOF
  ok "wrote $UNIT"
fi

systemctl --user daemon-reload >/dev/null 2>&1
systemctl --user enable jellyminer.service >>"$LOG" 2>&1 && ok "service enabled (starts at login)"

# linger: without it a --user service dies when the session ends, so the rig stops
# mining the moment you close the SSH window.
if command -v loginctl >/dev/null 2>&1; then
  if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = "yes" ]; then
    ok "linger already enabled (survives logout + reboot)"
  else
    sudo loginctl enable-linger "$USER" >>"$LOG" 2>&1 \
      && ok "linger enabled (survives logout + reboot)" \
      || warn "could not enable linger — the miner will stop when you log out"
  fi
fi

if [ -n "$TOKEN" ]; then
  systemctl --user restart jellyminer.service >>"$LOG" 2>&1
  sleep 2
  if [ "$(systemctl --user is-active jellyminer.service 2>/dev/null)" = "active" ]; then
    ok "miner running — rewards land in the wallet miner:$NAME"
  else
    warn "service did not stay up. Logs:  journalctl --user -u jellyminer -n 30"
  fi
else
  warn "no --token given, so the miner is installed but not started."
  warn "Add JELLY_TOKEN=<token> to $ENVF then: systemctl --user start jellyminer"
fi

info "Done"
echo "   status:  systemctl --user status jellyminer"
echo "   logs:    journalctl --user -u jellyminer -f"
echo "   stop:    systemctl --user stop jellyminer"
echo "   remove:  $0 uninstall"
