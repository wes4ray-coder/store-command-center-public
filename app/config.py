"""
Central configuration — EDIT HERE to move the Store to another machine.
Every value can be overridden with the environment variable shown in [brackets];
otherwise the default below is used.  Nothing else in the app hard-codes a host,
path, key, or model name — it all funnels through this file.
"""
import os
from pathlib import Path

def _env(name, default):
    return os.getenv(name, default)

# ── Filesystem paths (relative to the store/ project root) ───────────────────
# App display name (shown in the browser title, login page, and sidebar).
APP_NAME = _env("STORE_APP_NAME", "Store Command Center")

# BASE = code root (this repo). DATA_DIR = where user data lives (db, designs,
# videos, uploads, backups). Keep them equal unless you want data on another disk.
BASE     = Path(__file__).resolve().parent.parent
DATA_DIR = Path(_env("STORE_DATA_DIR", str(BASE)))
DESIGNS_PENDING  = DATA_DIR / "designs/pending"
DESIGNS_APPROVED = DATA_DIR / "designs/approved"
DESIGNS_REJECTED = DATA_DIR / "designs/rejected"
VIDEOS_DIR       = DATA_DIR / "videos"
RESELL_UPLOADS   = BASE / "static" / "resell_uploads"   # served under /static, stays with code
DB_PATH          = DATA_DIR / "store.db"
BACKUP_DIR       = DATA_DIR / "backups"
ARCHIVE_DIR      = DATA_DIR / "archive"   # saved webpage snapshots (time machine)

# ── 3D models (Cults3D pipeline) ─────────────────────────────────────────────
# MODELS3D_DIR holds the working copies + generated assets. MODELS3D_BACKLOG is
# the folder you drop raw 3D files into (STL/OBJ/3MF/ZIP/GLB) for the pipeline to
# scan → review → propose → publish. Point it anywhere with STORE_MODELS_BACKLOG.
MODELS3D_DIR      = DATA_DIR / "models3d"
MODELS3D_BACKLOG  = Path(_env("STORE_MODELS_BACKLOG", str(MODELS3D_DIR / "backlog")))
MODELS3D_RENDERS  = MODELS3D_DIR / "renders"    # turntable PNGs rendered from the mesh
MODELS3D_HERO     = MODELS3D_DIR / "hero"       # SDXL marketing/hero images
MODELS3D_ASSETS   = MODELS3D_DIR / "assets"     # zipped/staged files served to Cults3D
MODELS3D_GENERATED = MODELS3D_DIR / "generated" # locally-generated meshes (kept out of your backlog)
# 3D file extensions the backlog scanner picks up.
MODELS3D_EXTS     = tuple(e.strip().lower() for e in _env(
    "STORE_MODELS_EXTS", ".stl,.obj,.3mf,.glb,.gltf,.ply,.zip").split(",") if e.strip())
# Box-side helper scripts (mirror imagegen/videogen). Live on the GPU box, run via SSH.
RENDER_STL_SCRIPT = _env("STORE_RENDER_STL_SCRIPT", "~/.openclaw/tools/model3d/render_stl.sh")
GEN_3D_SCRIPT     = _env("STORE_GEN_3D_SCRIPT",     "~/.openclaw/tools/model3d/generate_3d.sh")

# ── 3D generation models (image/text → mesh, on the GPU box) ─────────────────
# Analogous to RECOMMENDED_MODELS / RECOMMENDED_VIDEO_MODELS but for 3D gen. Each
# entry is installed as a repo + venv on the box (not a single file), so it carries
# an install script rather than a download_url. `marker` is a path that exists once
# installed. TripoSR is the default, set up 2026-07-12.
RECOMMENDED_3D_MODELS = [
    {
        "key": "triposr",
        "label": "TripoSR (fast, default)",
        "style": "Image → 3D · fast (~2 min on a 3060) · good for figurines/props",
        "vram": "~6 GB",
        "marker": "~/TripoSR/run.py",
        "script": "~/.openclaw/tools/model3d/generate_3d.sh",
        "license": "MIT",
        "commercial": True,   # safe to SELL the output
        "note": "Lightweight and reliable. MIT-licensed — safe for models you sell. Uses PyMCubes.",
        "install": (
            "cd ~ && ([ -d TripoSR ] || git clone --depth 1 https://github.com/VAST-AI-Research/TripoSR.git) && "
            "python3 -m venv --system-site-packages ~/TripoSR/venv && "
            "echo /home/user/ComfyUI/venv/lib/python3.12/site-packages > "
            "~/TripoSR/venv/lib/python3.12/site-packages/zzz_comfyui.pth && "
            "~/TripoSR/venv/bin/pip install -q 'transformers==4.35.0' 'tokenizers>=0.14,<0.15' "
            "'huggingface-hub<0.18' 'omegaconf==2.3.0' 'einops==0.7.0' PyMCubes xatlas rembg imageio moderngl"
        ),
    },
    {
        "key": "triposg",
        "label": "TripoSG ★ (MIT — sellable, higher quality)",
        "style": "Image → 3D · sharper geometry than TripoSR · commercial-safe",
        "vram": "~8–10 GB",
        "marker": "~/TripoSG/venv/bin/python",
        "script": "~/.openclaw/tools/model3d/generate_triposg.sh",
        "license": "MIT",
        "commercial": True,      # safe to SELL the output
        "size": "~2–3 GB",
        "note": "MIT — safe to sell. Cleaner geometry than TripoSR. Reuses ComfyUI's torch and "
                "uses the CPU mesh extractor (no CUDA toolkit needed). Recommended upgrade. ~2–3 GB.",
        "install": "bash ~/.openclaw/tools/model3d/install_triposg.sh",
    },
    # Hunyuan3D-2 mini was removed: NON-commercial license (can't be sold) AND its
    # shapegen loader is broken on this box. Re-add only for personal/non-sale use.
    {
        "key": "sf3d",
        "label": "Stable Fast 3D (fast + textured)",
        "style": "Image → 3D · fast (~1 min) · textured · needs CUDA toolkit",
        "vram": "~7 GB",
        "marker": "~/stable-fast-3d/venv/bin/python",
        "script": "~/.openclaw/tools/model3d/generate_sf3d.sh",
        "license": "Stability Community (free < $1M rev)",
        "commercial": True,      # sellable if your revenue is under $1M/yr
        "needs_cuda": True,
        "size": "~3 GB",
        "note": "Community license — free to sell if your revenue is under $1M/yr. Textured meshes. "
                "Needs the CUDA toolkit (builds texture-baker ops) AND a HuggingFace token "
                "(gated model — accept the license on huggingface.co/stabilityai/stable-fast-3d).",
        "install": "bash ~/.openclaw/tools/model3d/install_sf3d.sh",
    },
    {
        "key": "trellis",
        "label": "TRELLIS (Microsoft) — top quality, experimental",
        "style": "Image → 3D · best open quality · heavy build · needs CUDA toolkit",
        "vram": "~16 GB (great on 2×3060/24 GB)",
        "marker": "~/TRELLIS/venv/bin/python",
        "script": "~/.openclaw/tools/model3d/generate_trellis.sh",
        "license": "MIT",
        "commercial": True,      # MIT — safe to sell
        "needs_cuda": True,
        "size": "~10 GB",
        "note": "MIT — safe to sell. Highest open quality, but a HEAVY / experimental install "
                "(custom CUDA ops: nvdiffrast, spconv, flash-attn). Needs the CUDA toolkit. "
                "May need a follow-up if a build step fails — tell me and I'll fix it.",
        "install": "bash ~/.openclaw/tools/model3d/install_trellis.sh",
    },
]

# ── Cults3D publishing defaults ──────────────────────────────────────────────
# createCreation requires PUBLIC https asset URLs. We serve them from a token-
# guarded route under PUBLIC_BASE_URL + STORE_BASE (see routers/models3d.py).
CULTS_DEFAULT_LOCALE   = _env("STORE_CULTS_LOCALE",   "en")
CULTS_DEFAULT_CURRENCY = _env("STORE_CULTS_CURRENCY", "USD")
CULTS_DEFAULT_LICENSE  = _env("STORE_CULTS_LICENSE",  "standard")  # cults license code
# Random token guarding the public asset route; persisted in settings on first use.
MODELS3D_ASSET_TOKEN   = _env("STORE_MODELS_ASSET_TOKEN", "")

# Headless browser used to capture JS-heavy / lightly-protected pages for the web archive
# (falls back to a plain HTTP fetch if not found). chromium works too.
CHROME_BIN = _env("STORE_CHROME_BIN", "google-chrome")

# Folders scanned by "Auto-populate → Import" to pull loose markdown into the library.
LIBRARY_IMPORT_DIRS = [str(BASE)]         # override with STORE_LIBRARY_IMPORT_DIRS (os.pathsep-separated)
if _env("STORE_LIBRARY_IMPORT_DIRS", ""):
    LIBRARY_IMPORT_DIRS = [p for p in _env("STORE_LIBRARY_IMPORT_DIRS", "").split(os.pathsep) if p]

# External helper scripts for image / video generation on the GPU box.
GENERATE_SCRIPT   = Path(_env("STORE_GENERATE_SCRIPT",   str(Path.home() / ".openclaw/tools/imagegen/generate.sh")))
VIDEO_GEN_SCRIPT  = Path(_env("STORE_VIDEO_GEN_SCRIPT",  str(Path.home() / ".openclaw/tools/videogen/generate_video.sh")))
VIDEO_CONT_SCRIPT = Path(_env("STORE_VIDEO_CONT_SCRIPT", str(Path.home() / ".openclaw/tools/videogen/generate_video_continuation.sh")))

# ── Web server / reverse-proxy ───────────────────────────────────────────────
STORE_BASE = _env("STORE_BASE_PATH", "/store")   # URL path prefix behind your reverse proxy ("" for root)
HOST       = _env("STORE_HOST", "0.0.0.0")       # [STORE_HOST]
PORT       = int(_env("STORE_PORT", "8787"))     # [STORE_PORT]

# ── GPU box: the machine running LM Studio (LLM) + ComfyUI (image/video) ──────
GPU_HOST       = _env("STORE_GPU_HOST", "127.0.0.1")   # <- change to your GPU machine's IP/host
GPU_SSH_USER   = _env("STORE_GPU_SSH_USER", "user")     # <- ssh user on the GPU box
# Total GPU VRAM (GB). With ~20+ GB the LLM and the image/video model can coexist,
# so set STORE_GPU_EXCLUSIVE=0 to stop unloading the LLM for image gen (2x 3060 = 24 GB).
GPU_VRAM_GB    = int(_env("STORE_GPU_VRAM_GB", "12"))
GPU_EXCLUSIVE  = _env("STORE_GPU_EXCLUSIVE", "1" if GPU_VRAM_GB < 20 else "0") == "1"
LLM_URL_DEFAULT = _env("STORE_LLM_URL", f"http://{GPU_HOST}:1234/v1")
COMFYUI_URL     = _env("STORE_COMFYUI_URL", f"http://{GPU_HOST}:8188")
# Audio / music generation node (future model type) — no default endpoint yet.
AUDIO_URL       = _env("STORE_AUDIO_URL", "")
BOX_SSH = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
           "-o", "ConnectTimeout=10", f"{GPU_SSH_USER}@{GPU_HOST}"]
COMFY_CKPT      = _env("STORE_COMFY_CKPT", "~/ComfyUI/models/checkpoints")
BOX_VENV_PYTHON = _env("STORE_BOX_VENV_PYTHON", "~/ComfyUI/venv/bin/python3")
BOX_HF_CACHE    = _env("STORE_BOX_HF_CACHE", "~/.cache/huggingface/hub")
# Per-type HuggingFace homes on the node's model SSD (models separated by type).
# Each pipeline sets HF_HOME to its own folder so video/audio/3D weights never mix.
# These env values are FALLBACKS — the live `models_dir_<kind>` settings (Settings →
# 🧠 Models → 📁 Storage, resolved via app/model_paths.py) win when set.
NODE_HF_VIDEO   = _env("STORE_HF_VIDEO", "/media/user/SSD/models_video")
NODE_HF_AUDIO   = _env("STORE_HF_AUDIO", "/media/user/SSD/models_audio")
NODE_HF_3D      = _env("STORE_HF_3D",    "/media/user/SSD/models_3d")
NODE_LLM_DIR    = _env("STORE_NODE_LLM_DIR", "/media/user/SSD/models_llm")   # LM Studio's folder (informational)

# ── Default models (also overridable live in the Settings tab, which wins) ────
ENHANCE_MODEL_DEFAULT       = _env("STORE_ENHANCE_MODEL", "google/gemma-4-12b-qat")
DEFAULT_IMAGE_MODEL_DEFAULT = _env("STORE_DEFAULT_IMAGE_MODEL", "dreamshaperXL_lightningDPMSDE.safetensors")

# ── OpenClaw integration ─────────────────────────────────────────────────────
# The store shells out to the OpenClaw CLI (marketplace posting agent) and uses
# OpenClaw tool scripts for image/video generation (paths above).
OPENCLAW_BIN   = _env("STORE_OPENCLAW_BIN", "openclaw")          # CLI binary/path

# ── GitHub / Dev Swarm ───────────────────────────────────────────────────────
GH_BIN  = _env("STORE_GH_BIN", "gh")     # GitHub CLI (must be `gh auth login`-ed)
GIT_BIN = _env("STORE_GIT_BIN", "git")
# The 3-branch worktrees (see BOOK → git/GitHub workflow). Default to siblings of BASE.
REPO_MASTER = _env("STORE_REPO_MASTER", str(BASE))
REPO_DEV    = _env("STORE_REPO_DEV",    str(Path(BASE).parent.parent / "store-dev"))
REPO_RETAIL = _env("STORE_REPO_RETAIL", str(Path(BASE).parent.parent / "store-retail"))
OPENCLAW_AGENT = _env("STORE_OPENCLAW_AGENT", "agent_store")     # agent used for posting

# Public URL where this app is reachable from the internet (for OAuth callbacks).
PUBLIC_BASE_URL   = _env("STORE_PUBLIC_URL", "http://localhost:8787")
ETSY_REDIRECT_URI = _env("STORE_ETSY_REDIRECT_URI", f"{PUBLIC_BASE_URL}{STORE_BASE}/api/etsy/callback")

# ── Network Security tab (Pi-hole scanner + live monitor) ────────────────────
PIHOLE_API_HOST  = _env("STORE_PIHOLE_API_HOST", "localhost")   # where the Pi-hole API lives
PIHOLE_API_PORT  = _env("STORE_PIHOLE_API_PORT", "8889")
PIHOLE_API_PASS  = _env("STORE_PIHOLE_API_PASS", "")            # Pi-hole admin/API password
PIHOLE_CONTAINER = _env("STORE_PIHOLE_CONTAINER", "pihole")     # docker container name

# ── Restart behaviour ────────────────────────────────────────────────────────
# The "Restart" button in Settings runs this. Leave blank to re-exec the process
# in place (works under any supervisor with restart-on-exit, e.g. systemd
# Restart=always or Docker --restart, and also standalone). Or set a command,
# e.g. "systemctl --user restart store.service".
RESTART_CMD = _env("STORE_RESTART_CMD", "")

# ── Third-party API keys ─────────────────────────────────────────────────────
# These are normally stored in the DB (set them in the Settings tab). Setting the
# env var here provides a default / lets you ship keys with the deployment.
PRINTIFY_API_KEY = _env("PRINTIFY_API_KEY", "")
PRINTIFY_SHOP_ID = _env("PRINTIFY_SHOP_ID", "")
ETSY_API_KEY     = _env("ETSY_API_KEY", "")
ETSY_API_SECRET  = _env("ETSY_API_SECRET", "")

# WordPress / WooCommerce Portal bridge. Normally entered in the Portal tab UI
# (stored in the DB, takes precedence). Set here to ship/pre-seed a deployment
# via a config file before first launch. See app/routers/portal.py.
WP_URL             = _env("STORE_WP_URL", "")
WP_CONSUMER_KEY    = _env("STORE_WP_CONSUMER_KEY", "")
WP_CONSUMER_SECRET = _env("STORE_WP_CONSUMER_SECRET", "")
WP_MCP_URL         = _env("STORE_WP_MCP_URL", "")
WP_MCP_TOKEN       = _env("STORE_WP_MCP_TOKEN", "")

# ── Printify base production costs (cents) — used for retail price math ───────
BASE_COSTS: dict[str, int] = {
    "T-Shirt":    950,   # $9.50  — Monster Digital
    "Hoodie":     1750,  # $17.50 — Prima Printing
    "Sweatshirt": 1450,  # $14.50 — Prima Printing
    "Tank Top":   900,   # $9.00  — Monster Digital
    "Mug":        550,   # $5.50  — SPOKE Custom Products
    "Tumbler":    900,   # $9.00  — SPOKE Custom Products
    "Poster":     700,   # $7.00  — T Shirt and Sons
    "Sticker":    250,   # $2.50  — Printify Choice
    "Tote Bag":   800,   # $8.00  — Fulfill Engine
    "Phone Case": 650,   # $6.50  — SPOKE Custom Products
    "Mouse Pad":  500,   # $5.00  — Printed Mint
    "Pillow":     1200,  # $12.00 — MWW On Demand
}

# ── Recommended image models catalog ─────────────────────────────────────────
RECOMMENDED_MODELS = [
    {
        "filename": "sdxl_base_1.0.safetensors",
        "label": "SDXL Base 1.0",
        "style": "General purpose",
        "vram": "~6.7 GB",
        "source": "HuggingFace (no auth)",
        "auto_download": True,
        "download_url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
        "download": "wget -O ~/ComfyUI/models/checkpoints/sdxl_base_1.0.safetensors https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
    },
    {
        "filename": "dreamshaperXL_lightningDPMSDE.safetensors",
        "label": "DreamShaper XL Lightning",
        "style": "Artistic / Illustration — great for merch",
        "vram": "~6.7 GB",
        "source": "CivitAI (no auth — direct link)",
        "auto_download": True,
        "download_url": "https://civitai.com/api/download/models/354657",
        "download": "wget -O ~/ComfyUI/models/checkpoints/dreamshaperXL_lightningDPMSDE.safetensors 'https://civitai.com/api/download/models/354657'",
        "note": "No login needed. Lightning model: use steps=6–8 for best results.",
    },
    {
        "filename": "realvisxlV50_v50LightningBakedvae.safetensors",
        "label": "RealVisXL V5 Lightning",
        "style": "Photorealistic — portraits, products, scenes",
        "vram": "~6.7 GB",
        "source": "CivitAI (no auth — direct link)",
        "auto_download": True,
        "download_url": "https://civitai.com/api/download/models/798204",
        "download": "wget -O ~/ComfyUI/models/checkpoints/realvisxlV50_v50LightningBakedvae.safetensors 'https://civitai.com/api/download/models/798204'",
        "note": "No login needed. Lightning: use steps=6–8, CFG=1.5–2 for best results.",
    },
    {
        "filename": "sd_xl_turbo_1.0_fp16.safetensors",
        "label": "SDXL Turbo (fast, 4-step)",
        "style": "Fast generation / previews",
        "vram": "~6 GB",
        "source": "HuggingFace (no auth, Stability AI)",
        "auto_download": True,
        "download_url": "https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0_fp16.safetensors",
        "download": "wget -O ~/ComfyUI/models/checkpoints/sd_xl_turbo_1.0_fp16.safetensors https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0_fp16.safetensors",
        "note": "Turbo: use steps=4, CFG=1.0 for best results.",
    },
    {
        "filename": "flux1-schnell-fp8.safetensors",
        "label": "FLUX.1 schnell (fp8) ★",
        "style": "State-of-the-art quality + excellent text rendering, fast (4-step)",
        "vram": "~17 GB (needs 24 GB)",
        "source": "HuggingFace (no auth, Comfy-Org)",
        "auto_download": True,
        "download_url": "https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors",
        "download": "wget -O ~/ComfyUI/models/checkpoints/flux1-schnell-fp8.safetensors https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors",
        "note": "Best open image model — ideal for your dual-3060 (24 GB). Steps 4, CFG 1.",
    },
    {
        "filename": "juggernautXL_juggXIByRundiffusion.safetensors",
        "label": "Juggernaut XL XI",
        "style": "Top-tier photorealism — products, people, scenes",
        "vram": "~6.7 GB",
        "source": "CivitAI (no auth — direct link)",
        "auto_download": True,
        "download_url": "https://civitai.com/api/download/models/782002",
        "download": "wget -O ~/ComfyUI/models/checkpoints/juggernautXL_juggXIByRundiffusion.safetensors 'https://civitai.com/api/download/models/782002'",
        "note": "Community favourite for realistic merch mockups.",
    },
]

# ── ComfyUI LoRA directory + recommended LoRAs ───────────────────────────────
COMFY_LORA = _env("STORE_COMFY_LORA", "~/ComfyUI/models/loras")

RECOMMENDED_LORAS = [
    {
        "filename": "pixel-art-xl.safetensors",
        "label": "Pixel Art XL",
        "style": "Pixel-art LoRA for SDXL — the world / sprite generator",
        "vram": "~170 MB",
        "source": "HuggingFace (no auth)",
        "kind": "lora",
        "dest_dir": COMFY_LORA,
        "auto_download": True,
        "download_url": "https://huggingface.co/nerijs/pixel-art-xl/resolve/main/pixel-art-xl.safetensors",
        "download": "wget -O ~/ComfyUI/models/loras/pixel-art-xl.safetensors https://huggingface.co/nerijs/pixel-art-xl/resolve/main/pixel-art-xl.safetensors",
        "note": "Powers The Company's pixel-art sprite generator (Settings → 🧠 Models → LoRA · world sprites, default strength 0.9).",
    },
    {
        "filename": "pixel-art-slider.safetensors",
        "label": "Pixel Art Slider (ntc-ai)",
        "style": "SDXL pixel-art slider LoRA — dial pixel-ness up/down",
        "vram": "~9 MB",
        "source": "HuggingFace (no auth)",
        "kind": "lora",
        "dest_dir": COMFY_LORA,
        "auto_download": True,
        "download_url": "https://huggingface.co/ntc-ai/SDXL-LoRA-slider.pixel-art/resolve/main/pixel%20art.safetensors",
        "download": "wget -O ~/ComfyUI/models/loras/pixel-art-slider.safetensors \"https://huggingface.co/ntc-ai/SDXL-LoRA-slider.pixel-art/resolve/main/pixel%20art.safetensors\"",
        "note": "Second, adjustable pixel style axis for sprites — pair with pixel-art-xl, tune strength for more/less pixelation.",
    },
    {
        "filename": "pixel-art-wzqacky.safetensors",
        "label": "Pixel Art XL (wzqacky)",
        "style": "SDXL pixel-art LoRA — grittier base style",
        "vram": "~23 MB",
        "source": "HuggingFace (no auth)",
        "kind": "lora",
        "dest_dir": COMFY_LORA,
        "auto_download": True,
        "download_url": "https://huggingface.co/wzqacky/pixel-art-model-sdxl-lora/resolve/main/pytorch_lora_weights.safetensors",
        "download": "wget -O ~/ComfyUI/models/loras/pixel-art-wzqacky.safetensors https://huggingface.co/wzqacky/pixel-art-model-sdxl-lora/resolve/main/pytorch_lora_weights.safetensors",
        "note": "Alternate pixel base — grittier than pixel-art-xl; good for prop/building sprites.",
    },
    # ── Merch / design-style LoRAs (map to Etsy/Printify product types) ──
    {
        "filename": "SDXL-StickerSheet-Lora.safetensors",
        "label": "Sticker Sheet (Norod78)",
        "style": "SDXL LoRA — die-cut sticker-sheet style · trigger: StickerSheet",
        "vram": "~29 MB", "source": "HuggingFace (no auth)", "kind": "lora", "dest_dir": COMFY_LORA,
        "auto_download": True,
        "download_url": "https://huggingface.co/Norod78/SDXL-StickerSheet-Lora/resolve/main/SDXL-StickerSheet-Lora.safetensors",
        "download": "wget -O ~/ComfyUI/models/loras/SDXL-StickerSheet-Lora.safetensors https://huggingface.co/Norod78/SDXL-StickerSheet-Lora/resolve/main/SDXL-StickerSheet-Lora.safetensors",
        "note": "Sticker sheets / die-cut sticker packs → Etsy/Printify sticker products.",
    },
    {
        "filename": "Canopus-Pencil-Art-LoRA.safetensors",
        "label": "Pencil / Line Art (Canopus)",
        "style": "SDXL LoRA — B&W line-art / coloring-book outlines",
        "vram": "~456 MB", "source": "HuggingFace (no auth)", "kind": "lora", "dest_dir": COMFY_LORA,
        "auto_download": True,
        "download_url": "https://huggingface.co/prithivMLmods/Canopus-Pencil-Art-LoRA/resolve/main/Canopus-Pencil-Art-LoRA.safetensors",
        "download": "wget -O ~/ComfyUI/models/loras/Canopus-Pencil-Art-LoRA.safetensors https://huggingface.co/prithivMLmods/Canopus-Pencil-Art-LoRA/resolve/main/Canopus-Pencil-Art-LoRA.safetensors",
        "note": "Line-art / coloring-book tees & printables.",
    },
    {
        "filename": "SDXL_Yarn_Art_Style.safetensors",
        "label": "Yarn / Embroidery (Norod78)",
        "style": "SDXL LoRA — yarn / embroidered-patch aesthetic · trigger: Yarn art style",
        "vram": "~57 MB", "source": "HuggingFace (no auth)", "kind": "lora", "dest_dir": COMFY_LORA,
        "auto_download": True,
        "download_url": "https://huggingface.co/Norod78/SDXL-YarnArtStyle-LoRA/resolve/main/SDXL_Yarn_Art_Style.safetensors",
        "download": "wget -O ~/ComfyUI/models/loras/SDXL_Yarn_Art_Style.safetensors https://huggingface.co/Norod78/SDXL-YarnArtStyle-LoRA/resolve/main/SDXL_Yarn_Art_Style.safetensors",
        "note": "Embroidered-patch / crafty look → patch & craft product lines.",
    },
]

# ── Specialty ComfyUI models grouped by type (upscalers / controlnet / matting) ──
# Each group has its own ComfyUI dir. Downloads reuse the same flow (dest_dir per entry).
COMFY_UPSCALE    = _env("STORE_COMFY_UPSCALE",    "~/ComfyUI/models/upscale_models")
COMFY_CONTROLNET = _env("STORE_COMFY_CONTROLNET", "~/ComfyUI/models/controlnet")
COMFY_RMBG       = _env("STORE_COMFY_RMBG",       "~/ComfyUI/models/background_removal")

EXTRA_MODEL_GROUPS = [
    {
        "key": "upscalers", "label": "\U0001F50D Upscalers", "dir": COMFY_UPSCALE,
        "sub": "ESRGAN upscalers (models/upscale_models/) — print-quality merch before Etsy/Printify",
        "models": [
            {"filename": "4x-UltraSharp.pth", "label": "4x-UltraSharp", "vram": "~67 MB",
             "style": "Sharp general upscaler — the print-quality default",
             "download_url": "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x-UltraSharp.pth",
             "note": "Default 4× upscale for merch art before print-on-demand."},
            {"filename": "4x_foolhardy_Remacri.pth", "label": "4x Remacri", "vram": "~67 MB",
             "style": "Detail-preserving upscaler",
             "download_url": "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x_foolhardy_Remacri.pth",
             "note": "Sharper detail for posters / large-format prints."},
            {"filename": "4x_NMKD-Siax_200k.pth", "label": "4x NMKD-Siax", "vram": "~67 MB",
             "style": "Clean upscaler for illustration/vector art",
             "download_url": "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x_NMKD-Siax_200k.pth",
             "note": "Clean upscale for illustration/vector-style merch."},
        ],
    },
    {
        "key": "bgremoval", "label": "✂️ Background removal", "dir": COMFY_RMBG,
        "sub": "Matting model (models/rmbg/) — transparent stickers + cleaner sprite cutouts",
        "models": [
            {"filename": "birefnet.safetensors", "label": "BiRefNet (MIT)", "vram": "~444 MB",
             "style": "High-quality matting — commercially safe (MIT)",
             "download_url": "https://huggingface.co/Comfy-Org/BiRefNet/resolve/main/background_removal/birefnet.safetensors",
             "note": "Transparent PNGs for die-cut stickers + sprite alpha. Use the ComfyUI-RMBG / BiRefNet node (models/rmbg/)."},
        ],
    },
    {
        "key": "controlnet", "label": "\U0001F39B️ ControlNet", "dir": COMFY_CONTROLNET,
        "sub": "SDXL ControlNet (models/controlnet/) — consistent poses/layouts across a product line",
        "models": [
            {"filename": "controlnet-union-sdxl-promax.safetensors", "label": "ControlNet++ Union SDXL ProMax", "vram": "~2.5 GB",
             "style": "All-in-one: pose / depth / canny / tile",
             "download_url": "https://huggingface.co/xinsir/controlnet-union-sdxl-1.0/resolve/main/diffusion_pytorch_model_promax.safetensors",
             "note": "One model = 12+ control types → coherent poses/layouts across a merch collection."},
        ],
    },
]

# Every downloadable model, flattened with a dest_dir — used by the download endpoint.
def all_downloadable_models():
    items = []
    for m in RECOMMENDED_MODELS:
        items.append({**m, "dest_dir": m.get("dest_dir", COMFY_CKPT)})
    for m in RECOMMENDED_LORAS:
        items.append({**m, "dest_dir": m.get("dest_dir", COMFY_LORA)})
    for g in EXTRA_MODEL_GROUPS:
        for m in g["models"]:
            items.append({**m, "dest_dir": m.get("dest_dir", g["dir"]), "auto_download": m.get("auto_download", True), "kind": g["key"]})
    return items

# ── Recommended video models catalog ─────────────────────────────────────────
RECOMMENDED_VIDEO_MODELS = [
    {
        "model_id": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "label": "Wan2.1 T2V 1.3B (Default)",
        "style": "General purpose text-to-video",
        "vram": "~8 GB",
        "size": "~5.5 GB",
        "source": "HuggingFace (no auth)",
        "note": "Auto-downloads on first video gen. Recommended starting point.",
        "rec_steps": 20,
        "steps_options": [15, 20, 30],
    },
    {
        "model_id": "Lightricks/LTX-Video",
        "label": "LTX-Video (Fast)",
        "style": "Fast generation, good for previews",
        "vram": "~10 GB",
        "size": "~9 GB",
        "source": "HuggingFace (no auth)",
        "note": "Use steps=6\u201310 for best results. bfloat16.",
        "rec_steps": 8,
        "steps_options": [6, 8, 10, 15],
    },
    {
        "model_id": "THUDM/CogVideoX-2b",
        "label": "CogVideoX 2B",
        "style": "High quality, cinematic",
        "vram": "~12 GB",
        "size": "~9 GB",
        "source": "HuggingFace (no auth)",
        "note": "Use steps=50, CFG=6.0. May be tight on 12 GB VRAM.",
        "rec_steps": 50,
        "steps_options": [30, 40, 50],
    },
    {
        "model_id": "Wan-AI/Wan2.1-T2V-14B-Diffusers",
        "label": "Wan2.1 T2V 14B ★ (high quality)",
        "style": "Much sharper motion & detail than the 1.3B default",
        "vram": "~20-24 GB",
        "size": "~28 GB",
        "source": "HuggingFace (no auth)",
        "note": "Great fit for your dual-3060 (24 GB).",
        "rec_steps": 25,
        "steps_options": [20, 25, 30],
    },
    {
        "model_id": "THUDM/CogVideoX-5b",
        "label": "CogVideoX 5B",
        "style": "Higher fidelity than 2B",
        "vram": "~16-24 GB",
        "size": "~20 GB",
        "source": "HuggingFace (no auth)",
        "note": "Steps 50, CFG 6. Needs 24 GB comfortably.",
        "rec_steps": 50,
        "steps_options": [30, 40, 50],
    },
    {
        "model_id": "tencent/HunyuanVideo",
        "label": "Hunyuan Video (SOTA)",
        "style": "State-of-the-art open video — cinematic",
        "vram": "~24 GB+ (with offload)",
        "size": "~40 GB",
        "source": "HuggingFace (no auth)",
        "note": "Very heavy; use CPU offload even on 24 GB.",
        "rec_steps": 30,
        "steps_options": [20, 30, 50],
    },
]
