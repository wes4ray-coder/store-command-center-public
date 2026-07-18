#!/usr/bin/env bash
# Stable Fast 3D — needs the CUDA toolkit (builds texture_baker/uv_unwrapper) and a
# HuggingFace token (gated model). Reuses ComfyUI torch; never installs torch.
set -euo pipefail
command -v nvcc >/dev/null || { echo "ERROR: nvcc (CUDA toolkit) not found — install it first" >&2; exit 3; }
export CUDA_HOME="${CUDA_HOME:-/usr}"
cd ~
[ -d stable-fast-3d ] || git clone --depth 1 https://github.com/Stability-AI/stable-fast-3d.git
cd ~/stable-fast-3d
python3 -m venv --system-site-packages ~/stable-fast-3d/venv
CSITE="$(ls -d "$HOME"/ComfyUI/venv/lib/python*/site-packages | head -1)"
VSITE="$(ls -d ~/stable-fast-3d/venv/lib/python*/site-packages | head -1)"
echo "$CSITE" > "$VSITE/zzz_comfyui.pth"
PIP=~/stable-fast-3d/venv/bin/pip
# gpytoolbox's sdist can't build (missing CMakeLists) — force its prebuilt wheel first.
$PIP install --only-binary=:all: gpytoolbox || echo "WARN: gpytoolbox wheel unavailable"
# Requirements minus torch/torchvision/numpy (reuse ComfyUI's) and gpytoolbox (done above).
grep -viE '^(torch|torchvision|numpy|gpytoolbox)([=<>! ]|$)' requirements.txt > /tmp/sf3d_reqs.txt 2>/dev/null || cp requirements.txt /tmp/sf3d_reqs.txt
$PIP install -r /tmp/sf3d_reqs.txt
# rembg drags in onnxruntime-GPU which bundles CUDA-13 libs that clash with our CUDA 12
# → force the CPU build (bg removal is small; CPU is fine).
$PIP uninstall -y onnxruntime-gpu nvidia-cuda-runtime nvidia-cublas nvidia-cuda-cupti nvidia-cuda-nvrtc nvidia-cudnn-cu13 2>/dev/null || true
$PIP install onnxruntime
# SF3D is NOT a pip package (run.py + sf3d/ pkg). Build its CUDA op SUBpackages instead.
$PIP install ./texture_baker ./uv_unwrapper
(cd ~/stable-fast-3d && python3 -c "from sf3d.system import SF3D; print('sf3d import OK')")
echo SF3D_INSTALL_DONE
