"""img_cutout.knockout (transparent cutout) + world_auto._web_bytes (WP 2MB downscale)."""
import os
from PIL import Image
import numpy as np

import img_cutout
import world_auto


def test_knockout_makes_flat_bg_transparent(tmp_path):
    p = str(tmp_path / "s.png")
    im = Image.new("RGB", (200, 200), (255, 255, 255))          # flat white background
    for x in range(60, 140):
        for y in range(60, 140):
            im.putpixel((x, y), (200, 30, 30))                  # opaque red subject
    im.save(p)
    assert img_cutout.knockout(p) is True
    out = Image.open(p).convert("RGBA")
    assert out.getpixel((2, 2))[3] == 0        # corner (bg) → transparent
    assert out.getpixel((100, 100))[3] == 255  # centre (subject) → opaque


def test_web_bytes_shrinks_big_image_keeps_png(tmp_path):
    p = str(tmp_path / "big.png")
    arr = (np.random.rand(2048, 2048, 4) * 255).astype("uint8")
    arr[:, :, 3] = 255
    Image.fromarray(arr, "RGBA").save(p)
    assert os.path.getsize(p) > 1_900_000
    name, data = world_auto._web_bytes(p)
    assert len(data) <= 1_900_000
    assert name.endswith(".png")               # transparency preserved


def test_web_bytes_small_image_untouched(tmp_path):
    p = str(tmp_path / "small.png")
    Image.new("RGB", (64, 64), (10, 20, 30)).save(p)
    name, data = world_auto._web_bytes(p)
    assert data == open(p, "rb").read()
