"""Per-task model selection for image generation.

Maps a product_type (Sticker, Poster, Coloring Book, T-Shirt, …) to the right
LoRA + upscaler + a prompt nudge, so The Company (and the manual Studio path) use the
CORRECT specialty model for what they're making. Everything is gated on what's actually
installed on the ComfyUI box — if a LoRA/upscaler hasn't been downloaded yet, it's
simply skipped (generation still works), and it activates automatically once present.

Wired at services.run_generation (product art + autonomous) — see also generate.sh
(arg 8 = lora "file:strength", arg 9 = upscaler filename).
"""

# product_type -> style. lora/upscale are FILENAMES (matched against installed models);
# strength for the lora; cutout=True flood-fills the flat bg to transparency (stickers);
# prompt_add is appended to the prompt so the render matches the product.
POLICY = {
    "Sticker": {
        "lora": "SDXL-StickerSheet-Lora.safetensors", "strength": 0.9,
        "upscale": "4x-UltraSharp.pth", "cutout": True,
        "prompt_add": "die-cut sticker, bold clean outline, flat solid white background, centered",
    },
    "Coloring Book": {
        "lora": "Canopus-Pencil-Art-LoRA.safetensors", "strength": 0.85,
        "prompt_add": "black and white line art, coloring book page, clean bold outlines, no shading, white background",
    },
    "Patch": {
        "lora": "SDXL_Yarn_Art_Style.safetensors", "strength": 0.8,
        "prompt_add": "embroidered patch, yarn art style, stitched border",
    },
    "Poster":     {"upscale": "4x-UltraSharp.pth"},
    "T-Shirt":    {"upscale": "4x-UltraSharp.pth"},
    "Hoodie":     {"upscale": "4x-UltraSharp.pth"},
    "Sweatshirt": {"upscale": "4x-UltraSharp.pth"},
    "Tank Top":   {"upscale": "4x-UltraSharp.pth"},
    "Tote Bag":   {"upscale": "4x-UltraSharp.pth"},
    "Canvas":     {"upscale": "4x_foolhardy_Remacri.pth"},
}


def _compute_installed():
    """Models actually loadable in ComfyUI right now (LoraLoader / UpscaleModelLoader /
    CheckpointLoaderSimple option lists). One HTTP call each; cached by the caller."""
    out = {"loras": set(), "upscalers": set(), "checkpoints": set(), "matte": set()}
    try:
        import httpx
        from config import COMFYUI_URL
        for node, key, dest in (("LoraLoader", "lora_name", "loras"),
                                ("UpscaleModelLoader", "model_name", "upscalers"),
                                ("CheckpointLoaderSimple", "ckpt_name", "checkpoints"),
                                ("LoadBackgroundRemovalModel", "bg_removal_name", "matte")):
            try:
                r = httpx.get(f"{COMFYUI_URL}/object_info/{node}", timeout=5)
                spec = r.json()[node]["input"]["required"][key]
                opts = spec[0]
                # ComfyUI has two schema forms: old = the options LIST directly; new =
                # the string "COMBO" with the list under spec[1]["options"].
                if isinstance(opts, str):
                    opts = (spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}).get("options", [])
                if isinstance(opts, (list, tuple)):
                    out[dest] = {o for o in opts if isinstance(o, str)}
            except Exception:
                pass
    except Exception:
        pass
    return out


def _installed():
    try:
        from cache import cached
        return cached("gen-installed-models", 120, _compute_installed)
    except Exception:
        return _compute_installed()


def resolve(product_type: str) -> dict:
    """What to generate `product_type` WITH. Returns:
      lora      "file.safetensors:strength" or "" (only if installed)
      upscale   "file.pth" or ""              (only if installed)
      cutout    bool — knock the flat bg out to transparency after render
      prompt_add extra prompt text for this product (always applied)
    """
    p = POLICY.get(product_type or "", {})
    inst = _installed()
    lora = ""
    if p.get("lora") and p["lora"] in inst["loras"]:
        lora = f"{p['lora']}:{p.get('strength', 0.9)}"
    upscale = p["upscale"] if (p.get("upscale") and p["upscale"] in inst["upscalers"]) else ""
    # cutout products (stickers): prefer a real BiRefNet matte in-workflow if a bg-removal
    # model is installed (clean cutouts on busy art); else the Python flood-fill fallback.
    matte = ""
    if p.get("cutout") and inst["matte"]:
        matte = sorted(inst["matte"])[0]
    return {"lora": lora, "upscale": upscale, "matte": matte,
            "cutout": bool(p.get("cutout")), "prompt_add": p.get("prompt_add", "")}
