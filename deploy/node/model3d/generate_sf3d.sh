#!/usr/bin/env bash
# Stable Fast 3D: image -> textured mesh. Needs HUGGING_FACE_HUB_TOKEN for the gated model.
set -euo pipefail
export HF_HOME="${HF_HOME:-/media/user/SSD/models_3d}"   # 3D models live under models_3d
IN="${1:?}"; OUT="${2:?}"
cd ~/stable-fast-3d
OD="$(mktemp -d)"; trap 'rm -rf "$OD"' EXIT
~/stable-fast-3d/venv/bin/python run.py "$IN" --output-dir "$OD" >&2
SRC="$(find "$OD" -name 'mesh.glb' -o -name '*.glb' | head -1)"
[ -n "$SRC" ] || { echo "ERROR: SF3D produced no mesh" >&2; exit 4; }
cp "$SRC" "$OUT"; echo "$OUT"
