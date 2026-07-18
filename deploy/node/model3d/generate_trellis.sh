#!/usr/bin/env bash
# TRELLIS: image -> mesh (glb). Shape+texture via the image-large model.
set -euo pipefail
export HF_HOME="${HF_HOME:-/media/user/SSD/models_3d}"   # 3D models live under models_3d
IN="${1:?}"; OUT="${2:?}"
cd ~/TRELLIS
~/TRELLIS/venv/bin/python - "$IN" "$OUT" <<'PY'
import os, sys
os.environ.setdefault("ATTN_BACKEND", "xformers")   # falls back if flash-attn missing
os.environ.setdefault("SPCONV_ALGO", "native")
from PIL import Image
from trellis.pipelines import TrellisImageTo3DPipeline
from trellis.utils import postprocessing_utils
inp, outp = sys.argv[1], sys.argv[2]
pipe = TrellisImageTo3DPipeline.from_pretrained("microsoft/TRELLIS-image-large")
pipe.cuda()
out = pipe.run(Image.open(inp).convert("RGB"), seed=1)
glb = postprocessing_utils.to_glb(out["gaussian"][0], out["mesh"][0], simplify=0.95, texture_size=1024)
glb.export(outp)
print(outp)
PY
echo "$OUT"
