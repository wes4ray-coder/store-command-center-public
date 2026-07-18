#!/usr/bin/env bash
# generate_3d.sh — image → 3D mesh via TripoSR on the RTX 3060 box.
# Usage: generate_3d.sh <input_image.png> <output_mesh.glb>
# Prints the output path on success; non-zero exit on failure.
set -euo pipefail
export HF_HOME="${HF_HOME:-/media/user/SSD/models_3d}"   # 3D models live under models_3d

IN="${1:?usage: generate_3d.sh <input_image> <output_mesh.glb>}"
OUT="${2:?usage: generate_3d.sh <input_image> <output_mesh.glb>}"

TRIPO_DIR="$HOME/TripoSR"
# Isolated TripoSR venv (pinned transformers 4.35) — falls back to ComfyUI's venv.
if [ -x "$HOME/TripoSR/venv/bin/python3" ]; then
  PY="$HOME/TripoSR/venv/bin/python3"
else
  PY="$HOME/ComfyUI/venv/bin/python3"
fi

if [ ! -f "$TRIPO_DIR/run.py" ]; then
  echo "ERROR: TripoSR not installed at $TRIPO_DIR — run the installer first" >&2
  exit 3
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cd "$TRIPO_DIR"
# TripoSR writes <output-dir>/0/mesh.<fmt>. Ask for glb; fall back to obj.
if "$PY" run.py "$IN" --output-dir "$WORK" --model-save-format glb >/dev/null 2>"$WORK/err.log"; then
  FMT=glb
elif "$PY" run.py "$IN" --output-dir "$WORK" >/dev/null 2>>"$WORK/err.log"; then
  FMT=obj
else
  echo "TripoSR failed:" >&2; tail -20 "$WORK/err.log" >&2; exit 4
fi

SRC="$(find "$WORK" -name "mesh.*" | head -1)"
if [ -z "$SRC" ]; then echo "ERROR: no mesh produced" >&2; exit 5; fi

# Normalize to the requested container (glb) using trimesh if needed.
if [ "${SRC##*.}" = "glb" ]; then
  cp "$SRC" "$OUT"
else
  "$PY" - "$SRC" "$OUT" <<'PYEOF'
import sys, trimesh
m = trimesh.load(sys.argv[1], force='mesh')
m.export(sys.argv[2])
PYEOF
fi
echo "$OUT"
