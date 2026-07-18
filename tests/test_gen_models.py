"""gen_models.resolve — per-product-type LoRA/upscaler/matte selection, gated on installed."""
import gen_models


def _fake_installed(monkeypatch, loras=(), upscalers=(), matte=(), checkpoints=()):
    monkeypatch.setattr(gen_models, "_installed", lambda: {
        "loras": set(loras), "upscalers": set(upscalers),
        "matte": set(matte), "checkpoints": set(checkpoints),
    })


def test_sticker_full_stack_when_installed(monkeypatch):
    _fake_installed(monkeypatch,
                    loras=["SDXL-StickerSheet-Lora.safetensors"],
                    upscalers=["4x-UltraSharp.pth"],
                    matte=["birefnet.safetensors"])
    s = gen_models.resolve("Sticker")
    assert s["lora"] == "SDXL-StickerSheet-Lora.safetensors:0.9"
    assert s["upscale"] == "4x-UltraSharp.pth"
    assert s["matte"] == "birefnet.safetensors"
    assert s["cutout"] is True and "die-cut sticker" in s["prompt_add"]


def test_gating_skips_uninstalled(monkeypatch):
    # nothing installed → no lora/upscale/matte, but the cutout intent + prompt stay
    _fake_installed(monkeypatch)
    s = gen_models.resolve("Sticker")
    assert s["lora"] == "" and s["upscale"] == "" and s["matte"] == ""
    assert s["cutout"] is True and s["prompt_add"]


def test_poster_gets_upscale_only(monkeypatch):
    _fake_installed(monkeypatch, upscalers=["4x-UltraSharp.pth"])
    s = gen_models.resolve("Poster")
    assert s["upscale"] == "4x-UltraSharp.pth"
    assert s["lora"] == "" and s["matte"] == "" and s["cutout"] is False


def test_unknown_type_is_bare(monkeypatch):
    _fake_installed(monkeypatch, loras=["x"], upscalers=["y"])
    s = gen_models.resolve("Mug")
    assert s["lora"] == "" and s["upscale"] == "" and s["cutout"] is False
