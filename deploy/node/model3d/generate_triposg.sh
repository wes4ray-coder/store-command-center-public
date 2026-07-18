#!/usr/bin/env bash
# generate_triposg.sh — image → 3D mesh via TripoSG (MIT) on the box.
# Usage: generate_triposg.sh <input_image> <output.glb>
set -euo pipefail
export HF_HOME="${HF_HOME:-/media/user/SSD/models_3d}"   # 3D models live under models_3d
IN="${1:?usage: generate_triposg.sh <input_image> <output.glb>}"
OUT="${2:?usage: generate_triposg.sh <input_image> <output.glb>}"
DIR="$HOME/TripoSG"
PY="$DIR/venv/bin/python3"
[ -x "$PY" ] || { echo "ERROR: TripoSG venv missing at $PY — install it first" >&2; exit 3; }
cd "$DIR"
"$PY" -m scripts.inference_triposg --image-input "$IN" --output-path "$OUT"
[ -f "$OUT" ] || { echo "ERROR: TripoSG produced no mesh" >&2; exit 4; }
echo "$OUT"
