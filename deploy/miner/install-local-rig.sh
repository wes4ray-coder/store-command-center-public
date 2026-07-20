#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# JellyMiner — second rig on the STORE BOX's own idle GPU.
#
# The store box already has a graphics card sitting at ~1% doing nothing while it
# serves the store, nginx and a docker stack. This turns that idle silicon into a
# second JellyCoin rig — deliberately at the LOWEST viable intensity, because the
# box's day job is serving, not mining.
#
# Measured on this box's GTX 1060 3GB (30s samples, store latency measured live
# against /api/jelly/status during each run):
#
#   setting                       hashrate     SM%     power    temp    store p50
#   idle (no mining)                    —      1.0%    28.5 W   61 °C   20.6 ms
#   throttle 90 / batch 2^20   26.1 MH/s      9.9%    31.0 W   63 °C   20.4 ms   ← default
#   throttle 85 / batch 2^20   38.6 MH/s     15.5%    32.1 W   65 °C   22.9 ms
#   throttle 75 / batch 2^22   68.1 MH/s     24.2%    35.1 W   66 °C   18.0 ms
#   throttle  0 / batch 2^22  333.7 MH/s     95.5%    87.1 W   78 °C   17.3 ms
#
# The default costs ~2.5 W and ~2 °C over idle and left store request latency
# indistinguishable from baseline (the store is CPU/IO bound, not GPU bound).
# Intensity is NOT baked in here — it is set server-side per rig and delivered
# live inside getwork, so you can retune it from the UI without touching this box:
#   Crypto → 🪼 JellyCoin → ⛏️ GPU rigs → per-rig intensity.
#
#   ./install-local-rig.sh                 # install + start at lowest intensity
#   ./install-local-rig.sh --name myrig    # different rig name
#   ./install-local-rig.sh check           # report, change nothing
#   ./install-local-rig.sh uninstall       # remove it again
#
# Refuses to install if no OpenCL GPU is visible — see the notes at the bottom.
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODE="install"
NAME="$(hostname -s 2>/dev/null || echo server)-gpu"
URL=""
DEVICE=""
# "Lowest viable": high throttle keeps the card mostly idle; the small batch keeps
# each kernel launch short so nothing else on the box ever waits long for the GPU.
THROTTLE=90
BATCH=$((1 << 20))

C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_0=$'\033[0m'
ok(){   printf '%s  ✓ %s%s\n' "$C_OK"   "$*" "$C_0"; }
warn(){ printf '%s  ! %s%s\n' "$C_WARN" "$*" "$C_0"; }
err(){  printf '%s  ✗ %s%s\n' "$C_ERR"  "$*" "$C_0"; }
info(){ printf '\n%s▸ %s%s\n' "$C_DIM" "$*" "$C_0"; }

while [ $# -gt 0 ]; do
  case "$1" in
    install|check|uninstall) MODE="$1" ;;
    --name)     NAME="${2:-}"; shift ;;
    --url)      URL="${2:-}"; shift ;;
    --device)   DEVICE="${2:-}"; shift ;;
    --throttle) THROTTLE="${2:-}"; shift ;;
    --batch)    BATCH="${2:-}"; shift ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) err "unknown argument: $1"; exit 2 ;;
  esac
  shift
done

if [ "$MODE" = "uninstall" ]; then
  exec "$HERE/install-miner.sh" uninstall
fi

# The store is on this same box, so ask it for its own URL + rig token over the
# localhost auth bypass rather than making the operator paste either one.
PORT="${STORE_PORT:-8787}"
api(){ curl -fsS --max-time 10 "http://127.0.0.1:$PORT$1" ${2:+-X POST -H 'Content-Type: application/json' -d "$2"}; }

info "Reading this store's rig token (localhost)"
TOKINFO="$(api /api/jelly/miner-token || true)"
if [ -z "$TOKINFO" ]; then
  err "could not reach the store on http://127.0.0.1:$PORT — is it running?"
  echo "   (systemctl --user status store)  ·  override the port with STORE_PORT=…"
  exit 1
fi
TOKEN="$(printf '%s' "$TOKINFO" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
[ -z "$URL" ] && URL="http://127.0.0.1:$PORT"
[ -n "$TOKEN" ] && ok "token obtained" || warn "no token in the response — continuing without one"

if [ "$MODE" = "check" ]; then
  info "Local rig status"
  "$HERE/install-miner.sh" check
  info "Server-side intensity for this rig"
  api /api/jelly/miner-policy 2>/dev/null | tr ',' '\n' | grep -E "\"name\"|throttle|batch|hours_today" | sed 's/^/     /'
  exit 0
fi

# ── refuse rather than ship a broken install ─────────────────────────────────
info "Checking for an OpenCL GPU on this box"
if ! ldconfig -p 2>/dev/null | grep -q libOpenCL; then
  warn "no OpenCL loader yet — install-miner.sh will add ocl-icd-libopencl1"
fi
if [ ! -d /etc/OpenCL/vendors ] || [ -z "$(ls -A /etc/OpenCL/vendors 2>/dev/null)" ]; then
  err "no OpenCL vendor ICD in /etc/OpenCL/vendors — this box's GPU driver must provide one."
  err "NVIDIA: the proprietary driver ships it. AMD: mesa-opencl-icd. Intel: intel-opencl-icd."
  err "Not installing a rig that cannot start. Fix the driver, then re-run."
  exit 1
fi
ok "vendor ICD present: $(ls /etc/OpenCL/vendors | tr '\n' ' ')"

info "Installing the miner (its own venv; nothing else on this box is touched)"
"$HERE/install-miner.sh" install --url "$URL" --token "$TOKEN" --name "$NAME" \
  --throttle "$THROTTLE" ${DEVICE:+--device "$DEVICE"} || exit 1

# ── register the rig's intensity server-side ─────────────────────────────────
# The CLI --throttle above is only the value used until the first getwork answers;
# from then on the Store's per-rig policy is authoritative and live-adjustable.
# cost=free marks this card as spare capacity: the chain-defence ladder may ramp
# it without asking, because unlike the AI node it costs no model time.
info "Registering intensity with the store"
if api /api/jelly/miner-policy \
     "{\"rigs\":{\"$NAME\":{\"throttle\":$THROTTLE,\"batch\":$BATCH,\"cost\":\"free\"}}}" >/dev/null; then
  ok "server-side policy set: throttle ${THROTTLE}%, batch $BATCH, cost=free"
  ok "retune any time in Crypto → 🪼 JellyCoin → ⛏️ GPU rigs (no restart needed)"
else
  warn "could not register the policy — the rig still runs at --throttle $THROTTLE"
fi

info "Done"
echo "   status:  systemctl --user status jellyminer"
echo "   logs:    journalctl --user -u jellyminer -f"
echo "   remove:  $0 uninstall"
