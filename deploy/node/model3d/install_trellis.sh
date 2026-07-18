#!/usr/bin/env bash
# TRELLIS (Microsoft, MIT) — heavy/experimental. Needs the CUDA toolkit. Reuses ComfyUI
# torch (never installs torch). Custom CUDA deps are best-effort; check the log on failure.
set -uo pipefail
command -v nvcc >/dev/null || { echo "ERROR: nvcc (CUDA toolkit) not found — install it first" >&2; exit 3; }
export CUDA_HOME="${CUDA_HOME:-/usr}"
cd ~
[ -d TRELLIS ] || git clone --recurse-submodules https://github.com/microsoft/TRELLIS.git
cd ~/TRELLIS
python3 -m venv --system-site-packages ~/TRELLIS/venv
CSITE="$(ls -d "$HOME"/ComfyUI/venv/lib/python*/site-packages | head -1)"
VSITE="$(ls -d ~/TRELLIS/venv/lib/python*/site-packages | head -1)"
echo "$CSITE" > "$VSITE/zzz_comfyui.pth"
PIP=~/TRELLIS/venv/bin/pip
$PIP install -q pillow imageio imageio-ffmpeg tqdm easydict opencv-python scipy ninja rembg onnxruntime trimesh xatlas pyvista pymeshfix igraph transformers safetensors einops || true
$PIP install -q xformers || echo "xformers failed (will try flash-attn)"
$PIP install -q flash-attn --no-build-isolation || echo "flash-attn build failed — TRELLIS can use xformers instead"
$PIP install -q spconv-cu120 || $PIP install -q spconv-cu121 || echo "spconv failed"
$PIP install -q git+https://github.com/NVlabs/nvdiffrast.git || echo "nvdiffrast build failed"
$PIP install -q git+https://github.com/JeffreyXiang/diffoctreerast.git || echo "diffoctreerast build failed"
$PIP install -q kaolin -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html || echo "kaolin failed"
echo TRELLIS_INSTALL_DONE
