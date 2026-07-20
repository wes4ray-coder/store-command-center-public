"""
THE COMPANY — real animation for generated sprite sheets.

This module exists because of one bug: the old `world_sprites.make_action_sheet`
built a "4-frame" sheet by rotating / nudging / brightening ONE still image. A
walk cycle was the same sprite swaying — the legs never moved. The owner named
it exactly: "a walk animation just needs 3 of the same sprite with variations of
a walk", i.e. genuinely different drawings, like the premade packs.

So the pipeline changed shape:

    ONE still  →  transform  →  fake sheet          (old — deleted)
    base sprite → K real POSE renders → cycle → sheet  (new)

Three parts live here, all pure/CPU so they are testable without a GPU:

  POSE SCRIPTS   Per action: a handful of KEY poses (a prompt phrase each) and a
                 `cycle` that expands those keys into the frame count the
                 anokolisa pack uses for that action (walk 6, idle 4, work 8 …).
                 Keys are what costs GPU — 2-3 renders buy a 6-8 frame sheet, and
                 the result is drop-in compatible with the pack layout, so the
                 renderer (world-assets.js WSP.draw / WA.drawActor) needs no fork.

  SPLITTER       `split_sheet` turns a multi-frame SHEET image back into cells —
                 the grid is inferred from the dimensions and/or transparent
                 gutters, every cell is validated, and `build_sheet` rebuilds a
                 normalized strip in the pack layout. This is what lets a
                 generation that returns a contact-sheet still be used, and what
                 lets an owner drop in their own sheet later.

  FRAME QA       `vet_frames` catches THIS bug class. The naive check (are the
                 frames different?) does NOT work: rotating a sprite by 3° changes
                 plenty of pixels, and the old fake walk actually scored HIGHER on
                 raw pixel diff than the real pack walk. The discriminator that
                 works is `articulation` — the silhouette mismatch that REMAINS
                 after searching for the best rigid (rotate + translate) alignment
                 between two frames. A rigid transform of one drawing aligns back
                 onto itself (residual → 0); a real pose change cannot (the limbs
                 are somewhere else). Thresholds are calibrated off the pack sheets
                 themselves — see PACK_ARTICULATION.

Nothing here spends GPU or touches the DB; `world_sprites` owns that.
"""
import itertools
import logging

logger = logging.getLogger("store")

CELL = 64                      # frame size (px) — the pack's character cell


# ── pose scripts ──────────────────────────────────────────────────────────────
# Per action: the KEY poses to render (prompt phrase each) and the `cycle` that
# expands them to the pack's frame count for that action. `gate` is the minimum
# articulation a sheet must show — see PACK_ARTICULATION for where it comes from.
# `static` marks actions that are SUPPOSED to hold still (lying is drawn with a
# frozen frame by the renderer), which are exempt from the articulation gate.
POSE_SCRIPTS = {
    "idle": {
        "spd": 200, "frames": 4, "cycle": [0, 0, 1, 1], "gate": 0.040,
        "keys": [("stand", "standing still, arms relaxed at the sides, weight on both feet"),
                 ("breathe", "standing still, chest lifted mid-breath, shoulders slightly raised")],
    },
    "walk": {
        # the owner's "3 of the same sprite with variations of a walk", expanded
        # to the pack's 6-frame walk by ping-ponging through the passing pose
        "spd": 110, "frames": 6, "cycle": [0, 1, 2, 2, 1, 0], "gate": 0.105,
        "keys": [("contact", "mid-stride walking, LEFT leg striding forward and right leg trailing back, legs clearly apart"),
                 ("passing", "walking, legs together passing under the body, one foot lifted off the ground"),
                 ("contact_opposite", "mid-stride walking, RIGHT leg striding forward and left leg trailing back, legs clearly apart")],
    },
    "work": {
        "spd": 90, "frames": 8, "cycle": [0, 0, 1, 1, 2, 2, 1, 0], "gate": 0.440,
        "keys": [("windup", "swinging a pickaxe, wound up with the pickaxe raised high overhead, body coiled back"),
                 ("strike", "swinging a pickaxe, the pickaxe slammed down at the rock, arms fully extended low"),
                 ("follow", "swinging a pickaxe, following through with the pickaxe low and the body leaning forward")],
    },
    "slice": {
        "spd": 90, "frames": 8, "cycle": [0, 0, 1, 1, 2, 2, 1, 0], "gate": 0.520,
        "keys": [("windup", "swinging a sword, wound up with the blade raised back behind the shoulder"),
                 ("strike", "swinging a sword, the blade slashing across at full extension in front"),
                 ("follow", "swinging a sword, following through with the blade low across the body")],
    },
    "collect": {
        "spd": 150, "frames": 8, "cycle": [0, 0, 1, 1, 2, 2, 1, 0], "gate": 0.265,
        "keys": [("reach", "bending down low, reaching one hand to the ground to gather an item"),
                 ("grab", "crouched right down, both hands at the ground picking an item up"),
                 ("rise", "straightening back up, holding the gathered item at chest height")],
    },
    "fishing": {
        "spd": 170, "frames": 8, "cycle": [0, 0, 1, 1, 2, 2, 2, 1], "gate": 0.420,
        "keys": [("cast_back", "holding a fishing rod, rod swung back over the shoulder ready to cast"),
                 ("cast_out", "holding a fishing rod, rod whipped forward and out, line cast ahead"),
                 ("reel", "holding a fishing rod low and steady, reeling the line in")],
    },
    "water": {
        "spd": 150, "frames": 8, "cycle": [0, 0, 0, 1, 1, 1, 1, 0], "gate": 0.100,
        "keys": [("lift", "holding a watering can up, tilted back, not yet pouring"),
                 ("pour", "tipping a watering can right over, water pouring out onto the ground")],
    },
    "carrywalk": {
        "spd": 110, "frames": 6, "cycle": [0, 1, 2, 2, 1, 0], "gate": 0.075,
        "keys": [("contact", "carrying a wooden crate in both arms, LEFT leg striding forward, legs apart"),
                 ("passing", "carrying a wooden crate in both arms, legs together passing under the body"),
                 ("contact_opposite", "carrying a wooden crate in both arms, RIGHT leg striding forward, legs apart")],
    },
    "carryidle": {
        "spd": 200, "frames": 4, "cycle": [0, 0, 1, 1], "gate": 0.036,
        "keys": [("hold", "standing still holding a wooden crate in both arms at waist height"),
                 ("shift", "standing still holding a wooden crate, hoisted a little higher against the chest")],
    },
    "lying": {
        # the renderer freezes this one on a single frame — a still sheet is CORRECT
        "spd": 120, "frames": 8, "cycle": [0] * 8, "gate": 0.0, "static": True,
        "keys": [("flat", "lying flat on the ground on their back, asleep, arms at the sides")],
    },
}

# Articulation actually measured on the anokolisa pack side-sheets (max over all
# frame pairs). The gates above sit at ~40% of these: a generated sheet must show
# a real fraction of the movement the reference pack shows for the same action.
# For reference, the OLD transform method scored: walk 0.079, idle 0.000,
# work 0.217, collect 0.101 — every one of them below its gate.
PACK_ARTICULATION = {"walk": 0.271, "idle": 0.106, "work": 1.157, "slice": 1.377,
                     "collect": 0.700, "fishing": 1.109, "water": 0.267,
                     "carrywalk": 0.196, "carryidle": 0.095, "lying": 1.499}

# identity drift: how far a pose frame's palette may move from the base sprite
# before we call it a different character (L1/2 over a 4×4×4 RGB histogram of the
# opaque pixels — 0 = same palette, 1 = no colours in common). Calibrated on the
# pack, which is the only ground truth we have for "same character":
#     same character, same action ....... 0.02 – 0.11
#     same character, different action .. up to 0.24   (walk vs crush)
#     genuinely different characters .... 0.67 – 0.69  (pack Body_A vs an entity)
# 0.35 sits clear of the widest same-character reading and far below the
# different-character floor.
IDENTITY_MAX = 0.35


def script_for(action):
    """The pose script for `action` — unknown actions animate like idle."""
    return POSE_SCRIPTS.get(action) or POSE_SCRIPTS["idle"]


def frames_for(action):
    return script_for(action)["frames"]


def keys_for(action):
    """[(key_name, prompt phrase)] — one GPU render each."""
    return list(script_for(action)["keys"])


# ── metrics ───────────────────────────────────────────────────────────────────
def _mask(im, size=CELL):
    """Binary silhouette of a frame as a float array (numpy)."""
    import numpy as np
    a = im.convert("RGBA").getchannel("A")
    if a.size != (size, size):
        from PIL import Image
        a = a.resize((size, size), Image.NEAREST)
    return (np.asarray(a, dtype=np.float32) > 128).astype(np.float32)


# rotation pivots to try when looking for a rigid alignment. The old fake sheet
# rotated about the feet; covering hip/centre/feet means a transform-derived
# frame always finds its own inverse and scores ~0.
_PIVOTS = ((0.5, 0.69), (0.5, 0.5), (0.5, 0.9))


def articulation(a, b, size=CELL):
    """How much of frame `b` CANNOT be explained as a rigid move of frame `a`.

    Searches rotations (±14°, three pivots) and shifts (±4px) for the best
    silhouette alignment and returns the leftover mismatch, normalised by the
    character's own area. ~0 means "b is just a rotated/nudged copy of a" — the
    exact signature of the old fake-animation bug. Real limb movement leaves a
    residual no rigid transform can absorb.
    """
    import numpy as np
    from PIL import Image
    mb = _mask(b, size)
    denom = max(1e-6, float((mb.sum() + _mask(a, size).sum()) / 2))
    src = a.convert("RGBA")
    w, h = src.size
    best = float("inf")
    for cx, cy in _PIVOTS:
        for rot in range(-14, 15):
            rm = _mask(src.rotate(rot, resample=Image.NEAREST, center=(w * cx, h * cy)), size)
            for dy in range(-4, 5):
                row = np.roll(rm, dy, axis=0)
                for dx in range(-4, 5):
                    d = float(np.abs(np.roll(row, dx, axis=1) - mb).sum()) / denom
                    if d < best:
                        best = d
    return best


def _palette(im, bins=4):
    """Normalised RGB histogram over the OPAQUE pixels only — the background is
    transparent, so counting it would make every sprite look alike."""
    import numpy as np
    px = np.asarray(im.convert("RGBA"), dtype=np.uint8).reshape(-1, 4)
    px = px[px[:, 3] > 128][:, :3]
    if not len(px):
        return np.zeros(bins ** 3)
    step = 256 // bins
    q = np.minimum(px // step, bins - 1).astype(int)
    idx = q[:, 0] * bins * bins + q[:, 1] * bins + q[:, 2]
    v = np.bincount(idx, minlength=bins ** 3).astype(float)
    return v / max(1.0, v.sum())


def identity_distance(a, b):
    """0 = same palette, 1 = nothing in common. Cheap stand-in for a character
    embedding: a diffusion model that wandered off and drew a different villager
    changes the colours, which is what we can actually detect for free."""
    import numpy as np
    return float(np.abs(_palette(a) - _palette(b)).sum() / 2)


def sheet_articulation(frames):
    """Max articulation over every pair of frames — a sheet whose frames are all
    rigid copies of one drawing scores ~0 no matter how many frames it has."""
    if len(frames) < 2:
        return 0.0
    return max(articulation(a, b) for a, b in itertools.combinations(frames, 2))


# ── frame QA (the gate that pins the bug) ────────────────────────────────────
def gate_for(action, strict_pct=None):
    """The articulation a sheet must reach for `action`.

    Expressed as a percentage of what the reference pack actually achieves, so
    the owner tunes ONE number (`world_sprites_qa_strict`) instead of ten
    thresholds. 40% reproduces the tuned defaults. Falls back to the script's
    own gate for actions the pack does not cover.
    """
    ref = PACK_ARTICULATION.get(action)
    if ref is None or not strict_pct:
        return script_for(action)["gate"]
    return round(ref * (max(0, min(100, int(strict_pct))) / 100.0), 4)


def vet_frames(key_images, action, base=None, gate=None, identity_max=None):
    """Is this set of KEY pose frames a real animation of the right character?

    Returns (ok, reason, metrics). Rejects, in order:
      * empty / wrong-shaped input
      * identity drift — a frame whose palette wandered off the base sprite
      * different characters BETWEEN frames (a fresh entity has no base)
      * near-identical frames — the sheet is static, i.e. the old bug
    `action`s marked static (lying) skip the articulation check by design.
    `gate`/`identity_max` override the defaults so the caller can honour the
    owner's settings without this module importing them (keeps it pure).
    """
    spec = script_for(action)
    gate = spec["gate"] if gate is None else gate
    identity_max = IDENTITY_MAX if identity_max is None else identity_max
    metrics = {"action": action, "keys": len(key_images), "gate": gate,
               "pack_reference": PACK_ARTICULATION.get(action)}
    if not key_images:
        return False, "no frames", metrics
    metrics["identity_limit"] = identity_max
    if base is not None:
        drift = [identity_distance(base, im) for im in key_images]
        metrics["identity_max"] = round(max(drift), 4)
        if max(drift) > identity_max:
            return False, (f"character drifted (palette distance {max(drift):.3f} > "
                           f"{identity_max}) — that is a different character"), metrics
    # Identity has to hold BETWEEN the frames too, not just against a base — a
    # brand-new entity has no base yet, and text-to-image happily returns three
    # different villagers for three pose prompts. Measured: the pack's own walk
    # frames sit at 0.03 spread, a real generated set came back at 0.70.
    if len(key_images) >= 2:
        spread = max(identity_distance(a, b)
                     for a, b in itertools.combinations(key_images, 2))
        metrics["identity_spread"] = round(spread, 4)
        if spread > identity_max:
            return False, (f"the character changes between frames (spread {spread:.3f} > "
                           f"{identity_max}) — these are different characters, not poses"), metrics
    if spec.get("static"):
        metrics["articulation"] = None
        return True, "static action (articulation gate not applicable)", metrics
    art = sheet_articulation(key_images)
    metrics["articulation"] = round(art, 4)
    if len(key_images) < 2:
        return False, "an animated action needs at least 2 distinct pose frames", metrics
    if art < gate:
        return False, (f"frames are near-identical (articulation {art:.3f} < gate "
                       f"{gate:.3f}) — this is a still image, not an animation"), metrics
    return True, "ok", metrics


# ── sheet splitting ───────────────────────────────────────────────────────────
def _blocks(profile, min_run=1):
    """Contiguous runs of non-empty entries in a 1-D occupancy profile."""
    out, start = [], None
    for i, v in enumerate(profile):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_run:
                out.append((start, i))
            start = None
    if start is not None and len(profile) - start >= min_run:
        out.append((start, len(profile)))
    return out


def _cell_ok(cell, min_cover=0.015, max_cover=0.92, min_extent=0.18):
    """A split cell must actually hold a character: some opaque pixels, not a
    solid block, and a bounding box that is a reasonable fraction of the cell."""
    try:
        a = cell.convert("RGBA").getchannel("A")
        w, h = a.size
        n = w * h
        if not n:
            return False
        data = a.tobytes()
        cover = sum(1 for v in data if v > 128) / n
        if not (min_cover <= cover <= max_cover):
            return False
        bbox = a.point(lambda v: 255 if v > 128 else 0).getbbox()
        if not bbox:
            return False
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        return bw >= w * min_extent and bh >= h * min_extent
    except Exception:
        return False


def split_sheet(im, expect=None, validate=True):
    """Split a multi-frame sheet image into its cells.

    Strategy, cheapest first:
      1. exact grid — width divisible by height (or by `expect`) gives a clean
         horizontal strip, which is what every pack sheet is;
      2. transparent gutters — columns that are entirely transparent separate the
         cells, which handles padded/irregular sheets and hand-dropped art;
      3. give up (returns []) rather than hand back garbage cells.

    Returns a list of PIL images (may be []). With `validate` on, a split whose
    cells are empty/solid/tiny is rejected — a wrong grid guess produces exactly
    those, so this doubles as the "did I split correctly" check.
    """
    from PIL import Image
    if im is None:
        return []
    try:
        im = im.convert("RGBA")
    except Exception:
        return []
    w, h = im.size
    if w <= 0 or h <= 0:
        return []

    def _cut(n, cw=None):
        cw = cw or w // n
        return [im.crop((i * cw, 0, (i + 1) * cw, h)) for i in range(n)]

    def _accept(cells):
        if not cells or (expect and len(cells) != expect):
            return None
        if validate and not all(_cell_ok(c) for c in cells):
            return None
        return cells

    # (0) a single square frame is not a sheet
    if w == h and not expect:
        return [im]
    # (1) exact grid — SQUARE cells first. `expect` is only a hint: trusting it
    # over the geometry splits a 3-frame 192×64 strip into six 32×64 half-figures.
    cands = []
    if h and w % h == 0 and 2 <= w // h <= 16:
        cands.append(w // h)
    if expect and w % expect == 0 and expect not in cands:
        cands.append(expect)
    for n in cands:
        got = _accept(_cut(n))
        if got:
            return got
    # (2) transparent gutters
    try:
        import numpy as np
        a = np.asarray(im.getchannel("A"), dtype=np.uint8)
        colcover = (a > 128).sum(axis=0)
        runs = _blocks(colcover > 0)
        if len(runs) >= 2 and (not expect or len(runs) == expect):
            # pad every block out to a common cell width so the strip stays uniform
            cw = max(r[1] - r[0] for r in runs)
            cells = []
            for x0, x1 in runs:
                cell = Image.new("RGBA", (cw, h), (0, 0, 0, 0))
                part = im.crop((x0, 0, x1, h))
                cell.paste(part, ((cw - part.width) // 2, 0), part)
                cells.append(cell)
            got = _accept(cells)
            if got:
                return got
    except Exception:
        logger.exception("gutter split failed")
    # (3) last resort: an exact grid we could not validate is still better than
    # nothing IF the caller asked for a specific count and the maths is clean
    if expect and w % expect == 0 and not validate:
        return _cut(expect)
    return []


def build_sheet(frames, dst, cell=CELL, count=None):
    """Write `frames` out as a normalized horizontal strip in the pack layout
    (count × cell wide, cell tall, RGBA, transparent gutters). Frames are
    resized to the cell with NEAREST so pixel art stays crisp; a short list is
    cycled to fill `count`. Returns dst."""
    from PIL import Image
    frames = [f for f in frames if f is not None]
    if not frames:
        raise ValueError("build_sheet needs at least one frame")
    count = count or len(frames)
    sheet = Image.new("RGBA", (cell * count, cell), (0, 0, 0, 0))
    for i in range(count):
        fr = frames[i % len(frames)].convert("RGBA")
        if fr.size != (cell, cell):
            fr = fr.resize((cell, cell), Image.NEAREST)
        sheet.paste(fr, (cell * i, 0), fr)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst)
    return dst


def expand(key_images, action):
    """Key poses → the action's full frame list, via its cycle."""
    spec = script_for(action)
    if not key_images:
        return []
    return [key_images[i % len(key_images)] for i in spec["cycle"]]


def sheet_frames(path_or_im, expect=None):
    """Read a saved sheet back as frames — used by QA and by the tests."""
    from PIL import Image
    im = path_or_im if hasattr(path_or_im, "convert") else Image.open(path_or_im)
    return split_sheet(im, expect=expect, validate=False)
