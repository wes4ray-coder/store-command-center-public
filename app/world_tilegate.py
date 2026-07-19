"""THE COMPANY — deterministic tile QA + style-consistency gate.

Extracted from world_tileset: the pure image-analysis primitives (seamless-ize,
QA slab/dark reject, per-tile luma/sat/hue stats, stripe-profile) and the
per-kind STYLE gate that decides whether a candidate terrain tile may join the
shared atlas. No ML — palette anchors + a brightness-harmony band against the
tiles already live. world_tileset imports and re-exports this whole surface.

The one outward tie: `_style_check(live=None)` compares against the tiles
currently live in the atlas, which it reads via `world_tileset._live_tiles`
(the atlas/manifest plumbing stays in the parent) — lazy-imported at call time
so there is no import cycle.
"""
import colorsys

CELL = 64          # pixel size of one atlas cell (mirrors world_tileset.CELL)

# ── style anchors: what each terrain kind is ALLOWED to look like ────────────
# hue in degrees (0-360, red=0); luma 0-255; sat 0-1. Deterministic, no ML.
STYLE_ANCHORS = {
    "grass": {"hue": (55, 175),  "luma": (35, 185), "sat_min": 0.14},
    "water": {"hue": (155, 285), "luma": (30, 180), "sat_min": 0.10},
    "floor": {"hue": (8, 60),    "luma": (45, 200), "sat_min": 0.08},
    "path":  {"hue": None,       "luma": (55, 205), "sat_min": None},
    "plaza": {"hue": None,       "luma": (75, 215), "sat_min": None},
    "wall":  {"hue": None,       "luma": (40, 200), "sat_min": None},
}
HARMONY_LUMA_BAND = 75      # candidate mean-luma must sit this close to the live set's median
STRIPE_SD_MAX = 18          # max row/column luma-profile stddev — above this the tile BANDS when tiled


def _seamless(src_path):
    from PIL import Image
    return _seamless_im(Image.open(src_path).convert("RGB"))


def _seamless_im(im):
    """Half-offset the image so the tile seams land on a center cross, then blend
    that cross from a blurred copy — cheap, reliable tileability."""
    from PIL import Image, ImageChops, ImageFilter, ImageDraw
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2,
                  (im.width + s) // 2, (im.height + s) // 2))
    rolled = ImageChops.offset(im, s // 2, s // 2)
    smooth = rolled.filter(ImageFilter.GaussianBlur(s // 42))
    band = max(6, s // 16)
    mask = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(mask)
    d.rectangle([s // 2 - band, 0, s // 2 + band, s], fill=255)
    d.rectangle([0, s // 2 - band, s, s // 2 + band], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(band // 2))
    out = Image.composite(smooth, rolled, mask)
    return out.resize((CELL, CELL), Image.NEAREST)


def _tile_ok(im):
    """QA gate: reject tiles the model botched — near-uniform slabs (e.g. a solid
    red 'floor') or near-black renders. A rejected kind simply keeps the
    procedural art, which always looks correct."""
    from PIL import ImageStat
    st = ImageStat.Stat(im.convert("RGB"))
    mean_luma = sum(st.mean) / 3.0
    spread = sum(st.stddev) / 3.0
    return mean_luma >= 28 and spread >= 6


# ── style-consistency gate (deterministic; no ML) ────────────────────────────
def _tile_stats(im):
    """Mean luma (0-255), mean saturation (0-1) and the saturation-weighted
    circular mean hue (degrees) of a tile."""
    im = im.convert("RGB").resize((32, 32))
    import math
    sx = sy = 0.0
    sat_sum = luma_sum = 0.0
    data = im.tobytes()                        # packed RGB triplets
    n = len(data) // 3
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        w = s * v                              # gray/dark pixels barely vote on hue
        sx += w * math.cos(h * 6.2831853)
        sy += w * math.sin(h * 6.2831853)
        sat_sum += s
        luma_sum += 0.299 * r + 0.587 * g + 0.114 * b
    hue = (math.degrees(math.atan2(sy, sx)) + 360.0) % 360.0
    hue_strength = math.hypot(sx, sy) / n      # ~0 when the tile is essentially gray
    return {"luma": luma_sum / n, "sat": sat_sum / n, "hue": hue,
            "hue_strength": hue_strength}


def _stripe_sd(im):
    """Stddev of the per-row and per-column mean-luma profiles. A uniform texture
    stays low (noise averages out across the tile); a tile with a bright band or
    strong gradient scores high — and repeats as UGLY periodic stripes when tiled
    (seen live: a grass tile with a flower band → whole-map banding)."""
    import statistics
    from PIL import ImageStat
    im = im.convert("RGB")
    w, h = im.size
    rows = [sum(ImageStat.Stat(im.crop((0, y, w, y + 1))).mean) / 3 for y in range(h)]
    cols = [sum(ImageStat.Stat(im.crop((x, 0, x + 1, h))).mean) / 3 for x in range(w)]
    return max(statistics.pstdev(rows), statistics.pstdev(cols))


def _style_check(key, im, live=None):
    """(ok, reason). Three deterministic parts:
    1) per-kind anchor — the tile must read as its terrain (grass green, water
       blue, plaza light …), so a gray concrete slab can't become 'grass';
    2) stripe gate — no strong internal bands/gradients (they repeat as
       map-wide stripes when tiled);
    3) harmony — mean brightness must sit within HARMONY_LUMA_BAND of the
       median of the tiles already live, keeping the growing set coherent."""
    st = _tile_stats(im)
    a = STYLE_ANCHORS.get(key) or {}
    lo, hi = a.get("luma") or (25, 230)
    if not (lo <= st["luma"] <= hi):
        return False, f"brightness {st['luma']:.0f} outside {lo}-{hi} for {key}"
    smin = a.get("sat_min")
    if smin is not None and st["sat"] < smin:
        return False, f"too gray for {key} (saturation {st['sat']:.2f} < {smin})"
    hr = a.get("hue")
    if hr is not None:
        # only enforce hue when the tile actually has one to speak of
        if st["hue_strength"] < 0.03:
            return False, f"no dominant colour — {key} must read {hr[0]}-{hr[1]}°"
        if not (hr[0] <= st["hue"] <= hr[1]):
            return False, f"hue {st['hue']:.0f}° outside {hr[0]}-{hr[1]}° for {key}"
    sd = _stripe_sd(im)
    if sd > STRIPE_SD_MAX:
        return False, f"banded texture (stripe profile {sd:.0f} > {STRIPE_SD_MAX}) — would tile as stripes"
    if live is None:
        from world_tileset import _live_tiles   # atlas-reading helper stays in the parent module
        live = _live_tiles(exclude=key)
    if live:
        lumas = sorted(_tile_stats(t)["luma"] for t in live)
        med = lumas[len(lumas) // 2]
        if abs(st["luma"] - med) > HARMONY_LUMA_BAND:
            return False, (f"clashes with the live set (brightness {st['luma']:.0f} "
                           f"vs set median {med:.0f})")
    return True, ""
