#!/usr/bin/env bash
# generate_hunyuan.sh — image → 3D mesh via Hunyuan3D-2 mini (shape only) on the box.
# NON-COMMERCIAL model (Tencent Hunyuan license). Usage: generate_hunyuan.sh <img> <out.glb>
set -euo pipefail
export HF_HOME="${HF_HOME:-/media/user/SSD/models_3d}"   # 3D models live under models_3d
IN="${1:?usage: generate_hunyuan.sh <input_image> <output.glb>}"
OUT="${2:?usage: generate_hunyuan.sh <input_image> <output.glb>}"
DIR="$HOME/Hunyuan3D-2"
PY="$DIR/venv/bin/python3"
[ -x "$PY" ] || { echo "ERROR: Hunyuan3D venv missing at $PY" >&2; exit 3; }
cd "$DIR"
"$PY" - "$IN" "$OUT" <<'PYEOF'
import os, sys
from PIL import Image
inp, outp = sys.argv[1], sys.argv[2]
from hy3dgen.rembg import BackgroundRemover
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
model = os.environ.get("HY3D_MODEL", "tencent/Hunyuan3D-2mini")
sub   = os.environ.get("HY3D_SUBFOLDER", "hunyuan3d-dit-v2-mini")
try:
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model, subfolder=sub)
except Exception as e:
    sys.stderr.write(f"subfolder load failed ({e}); trying default layout\n")
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model)
img = Image.open(inp).convert("RGBA")
img = BackgroundRemover()(img)          # segment the object
mesh = pipe(image=img)[0]               # shape only (untextured — fine for printing)
mesh.export(outp)
print(outp)
PYEOF
echo "$OUT"
