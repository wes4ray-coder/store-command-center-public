"""Knock a flat background out to transparency (for die-cut stickers).

Full-res version of The Company sprite knockout: flood-fill inward from the image
borders and make everything the fill reaches transparent. Works when the render has a
flat/solid background (the Sticker policy adds "flat solid white background" to the
prompt). A future BiRefNet matte would handle busy backgrounds — this is the no-extra-
dependency path that works today.
"""


def knockout(path, tol: int = 34) -> bool:
    """Make the flat border-connected background of `path` transparent, in place.
    Returns True on success, False (leaves the file untouched) on any problem."""
    try:
        from PIL import Image, ImageDraw
        import numpy as np
    except Exception:
        return False
    try:
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        work = im.convert("RGB")
        SENT = (255, 0, 255)  # magenta sentinel for the flood-filled region
        seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
        for s in seeds:
            try:
                ImageDraw.floodfill(work, s, SENT, thresh=tol)
            except Exception:
                pass
        mask = np.all(np.array(work) == SENT, axis=-1)
        # bail if the knockout ate almost everything (busy bg → don't wreck the art)
        if mask.mean() > 0.92 or mask.mean() < 0.02:
            return False
        rgba = np.array(im)
        rgba[mask, 3] = 0
        Image.fromarray(rgba, "RGBA").save(path)
        return True
    except Exception:
        return False
