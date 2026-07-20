"""Real sprite animation — app/world_anim.py (pose scripts, splitter, frame QA).

The bug being pinned: a "4-frame" sheet built by rotating/nudging ONE still image
is not an animation. `test_old_transform_method_is_rejected` rebuilds a sheet the
old way and asserts the QA throws it out, so the regression cannot come back.
"""
import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

PACK = (Path(__file__).resolve().parent.parent / "static" / "world_assets" / "packs"
        / "anokolisa-pixel-crawler" / "Pixel Crawler - Free Pack" / "Entities"
        / "Characters" / "Body_A" / "Animations")


def _figure(size=64, leg_dx=0, arm_up=False, hue=(200, 90, 60)):
    """A crude character: head, torso, two legs (offset by `leg_dx`), one arm.
    `leg_dx` is what makes two frames a real POSE change rather than a nudge."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, top = size // 2, size // 5
    d.ellipse([cx - 7, top, cx + 7, top + 14], fill=(240, 200, 170, 255))     # head
    d.rectangle([cx - 8, top + 14, cx + 8, size - 22], fill=hue + (255,))      # torso
    d.rectangle([cx - 8 - leg_dx, size - 22, cx - 2 - leg_dx, size - 4], fill=(60, 60, 110, 255))
    d.rectangle([cx + 2 + leg_dx, size - 22, cx + 8 + leg_dx, size - 4], fill=(60, 60, 110, 255))
    ay = top + 12 if arm_up else top + 20
    d.rectangle([cx + 8, ay, cx + 16, ay + 6], fill=hue + (255,))              # arm
    return im


def _pack_frames(rel):
    from PIL import Image
    im = Image.open(PACK / rel).convert("RGBA")
    n = im.width // im.height
    return [im.crop((i * 64, 0, (i + 1) * 64, 64)) for i in range(n)]


def _old_transform_sheet(base, action="walk"):
    """The DELETED fake-animation method, rebuilt here on purpose: one still,
    rotated / nudged / brightened into '4 frames'."""
    from PIL import Image, ImageEnhance
    # the exact transform tables the deleted code shipped
    strike = [(-8, 0, 0, 1.0), (0, 0, -1, 1.03), (12, 1, 0, 1.0), (5, 0, 0, 0.97)]
    bob = [(0, 0, 0, 1.0), (0, 0, -1, 1.05), (0, 0, 0, 1.0), (0, 0, 1, 0.95)]
    sway = [(-3, 0, 0, 1.0), (0, 0, -1, 1.02), (3, 0, 0, 1.0), (0, 0, -1, 1.02)]
    tilt = [(0, 0, 0, 1.0), (6, 0, 1, 1.0), (10, 1, 1, 0.98), (5, 0, 0, 1.0)]
    spec = {"idle": bob, "carryidle": bob, "fishing": bob, "walk": sway, "carrywalk": sway,
            "work": strike, "slice": strike, "collect": tilt, "water": tilt}.get(action, bob)
    cell = base.size[0]
    out = []
    for rot, dx, dy, lum in spec:
        fr = base
        if rot:
            pad = Image.new("RGBA", (cell * 2, cell * 2), (0, 0, 0, 0))
            pad.paste(fr, (cell // 2, cell // 2), fr)
            pad = pad.rotate(-rot, resample=Image.NEAREST,
                             center=(cell, cell + cell // 2 - 4))
            fr = pad.crop((cell // 2, cell // 2, cell // 2 + cell, cell // 2 + cell))
        if lum != 1.0:
            a = fr.getchannel("A")
            fr = ImageEnhance.Brightness(fr).enhance(lum)
            fr.putalpha(a)
        shifted = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
        shifted.paste(fr, (dx, dy), fr)
        out.append(shifted)
    return out


# ── pose scripts stay drop-in compatible with the packs ──────────────────────
def test_pose_scripts_match_pack_frame_counts():
    """Generated sheets must have the frame count the renderer already expects
    for that action (world-assets.js CHAR), or they animate at the wrong speed."""
    import world_anim
    expected = {"walk": 6, "idle": 4, "work": 8, "slice": 8, "collect": 8,
                "fishing": 8, "water": 8, "carrywalk": 6, "carryidle": 4, "lying": 8}
    for action, frames in expected.items():
        spec = world_anim.script_for(action)
        assert spec["frames"] == frames, action
        assert len(spec["cycle"]) == frames, action
        assert max(spec["cycle"]) < len(spec["keys"]), action     # no dangling key index


def test_every_action_has_at_least_two_keys_unless_static():
    import world_anim
    for action, spec in world_anim.POSE_SCRIPTS.items():
        if spec.get("static"):
            continue
        assert len(spec["keys"]) >= 2, f"{action} cannot animate from one pose"


def test_expand_maps_keys_through_the_cycle():
    import world_anim
    keys = [_figure(leg_dx=0), _figure(leg_dx=6), _figure(leg_dx=-6)]
    full = world_anim.expand(keys, "walk")
    assert len(full) == 6
    assert full[0] is keys[0] and full[1] is keys[1] and full[2] is keys[2]


# ── the metric: rigid transforms are NOT animation ───────────────────────────
def test_articulation_is_zero_for_a_rigid_copy():
    """A frame that is just its neighbour moved must score ~0 — this is the
    property the whole bug fix rests on."""
    import world_anim
    from PIL import Image
    a = _figure()
    b = Image.new("RGBA", a.size, (0, 0, 0, 0))
    b.paste(a, (2, -1), a)                       # pure translation
    assert world_anim.articulation(a, b) < 0.05


def test_articulation_is_large_for_a_real_pose_change():
    import world_anim
    assert world_anim.articulation(_figure(leg_dx=0), _figure(leg_dx=7)) > 0.15


def test_pack_walk_clears_its_own_gate():
    """The reference pack is the quality bar — the gates are calibrated off it,
    so a real pack sheet must comfortably pass its own action's gate."""
    import world_anim
    frames = _pack_frames("Walk_Base/Walk_Side-Sheet.png")
    art = world_anim.sheet_articulation(frames)
    assert art >= world_anim.POSE_SCRIPTS["walk"]["gate"]
    assert art == pytest.approx(world_anim.PACK_ARTICULATION["walk"], abs=0.06)


def test_old_transform_method_is_rejected():
    """THE regression test. A sheet built the old way (one still + rotate/nudge/
    brighten) must fail frame QA for every animated action."""
    import world_anim
    base = _pack_frames("Walk_Base/Walk_Side-Sheet.png")[0]
    for action in ("walk", "idle", "work", "collect"):
        frames = _old_transform_sheet(base, action)
        ok, why, metrics = world_anim.vet_frames(frames, action)
        assert not ok, f"{action}: the old fake sheet passed QA"
        assert "near-identical" in why
        assert metrics["articulation"] < metrics["gate"]


def test_real_pack_sheets_pass_frame_qa():
    import world_anim
    for action, rel in (("walk", "Walk_Base/Walk_Side-Sheet.png"),
                        ("work", "Crush_Base/Crush_Side-Sheet.png"),
                        ("collect", "Collect_Base/Collect_Side-Sheet.png")):
        ok, why, _ = world_anim.vet_frames(_pack_frames(rel), action)
        assert ok, f"{action} rejected the real pack sheet: {why}"


def test_static_actions_skip_the_articulation_gate():
    """`lying` is drawn frozen by the renderer — a still sheet is correct there."""
    import world_anim
    frames = [_figure()] * 8
    ok, why, _ = world_anim.vet_frames(frames, "lying")
    assert ok and "static" in why


# ── identity drift ───────────────────────────────────────────────────────────
def test_identity_distance_separates_same_from_different_character():
    import world_anim
    same_a, same_b = _figure(leg_dx=0), _figure(leg_dx=7)
    other = _figure(hue=(40, 190, 90))
    assert world_anim.identity_distance(same_a, same_b) < world_anim.IDENTITY_MAX
    assert world_anim.identity_distance(same_a, other) > world_anim.IDENTITY_MAX


def test_identity_drift_is_rejected():
    import world_anim
    base = _figure(hue=(200, 90, 60))
    drifted = [_figure(leg_dx=0, hue=(30, 80, 220)), _figure(leg_dx=7, hue=(30, 200, 90))]
    ok, why, metrics = world_anim.vet_frames(drifted, "walk", base=base)
    assert not ok and "drifted" in why
    assert metrics["identity_max"] > world_anim.IDENTITY_MAX


def test_different_characters_across_frames_are_rejected_without_any_base():
    """A brand-new entity has no base sprite, so identity can only be checked
    BETWEEN the frames. Text-to-image really does return three different
    villagers for three pose prompts (measured spread 0.70 against the pack's
    0.03), and that must not install as one walk cycle."""
    import world_anim
    three_people = [_figure(leg_dx=0, hue=(200, 90, 60)),
                    _figure(leg_dx=8, hue=(40, 190, 90)),
                    _figure(leg_dx=-8, hue=(60, 90, 220))]
    ok, why, metrics = world_anim.vet_frames(three_people, "walk", base=None)
    assert not ok and "changes between frames" in why
    assert metrics["identity_spread"] > world_anim.IDENTITY_MAX


def test_pack_frames_hold_identity_between_frames():
    """The bar: the reference pack's own walk frames are one character."""
    import world_anim
    frames = _pack_frames("Walk_Base/Walk_Side-Sheet.png")
    spread = max(world_anim.identity_distance(a, b)
                 for a, b in itertools.combinations(frames, 2))
    assert spread < 0.15
    ok, why, _ = world_anim.vet_frames(frames, "walk", base=None)
    assert ok, why


def test_good_frames_pass_with_a_matching_base():
    import world_anim
    base = _figure()
    ok, why, _ = world_anim.vet_frames(
        [_figure(leg_dx=0), _figure(leg_dx=7), _figure(leg_dx=-7)], "walk", base=base)
    assert ok, why


# ── the splitter ─────────────────────────────────────────────────────────────
def _strip(frames, cell=64, gutter=0):
    from PIL import Image
    w = (cell + gutter) * len(frames)
    im = Image.new("RGBA", (w, cell), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        im.paste(f, (i * (cell + gutter), 0), f)
    return im


def test_split_clean_grid():
    import world_anim
    frames = [_figure(leg_dx=d) for d in (0, 6, -6, 3, -3, 0)]
    cells = world_anim.split_sheet(_strip(frames))
    assert len(cells) == 6
    assert all(c.size == (64, 64) for c in cells)


def test_split_respects_expected_count():
    import world_anim
    frames = [_figure(leg_dx=d) for d in (0, 6, -6, 4)]
    assert len(world_anim.split_sheet(_strip(frames), expect=4)) == 4


def test_split_with_transparent_gutters():
    """Padded sheets (gaps between cells) split on the gutters, not the maths."""
    import world_anim
    frames = [_figure(leg_dx=d) for d in (0, 7, -7)]
    cells = world_anim.split_sheet(_strip(frames, gutter=9))
    assert len(cells) == 3
    assert all(c.height == 64 for c in cells)


def test_split_odd_size_falls_back_to_gutters():
    import world_anim
    from PIL import Image
    frames = [_figure(leg_dx=d) for d in (0, 7)]
    src = _strip(frames, gutter=11)
    odd = Image.new("RGBA", (src.width + 7, src.height), (0, 0, 0, 0))   # not divisible
    odd.paste(src, (3, 0), src)
    assert odd.width % odd.height != 0
    assert len(world_anim.split_sheet(odd)) == 2


def test_split_rejects_garbage():
    import world_anim
    from PIL import Image
    assert world_anim.split_sheet(None) == []
    assert world_anim.split_sheet(Image.new("RGBA", (0, 0))) == []
    assert world_anim.split_sheet(Image.new("RGBA", (256, 64), (0, 0, 0, 0))) == []   # empty
    solid = Image.new("RGBA", (256, 64), (10, 10, 10, 255))                           # no gutters
    assert world_anim.split_sheet(solid) == []


def test_split_single_square_frame_is_not_a_sheet():
    import world_anim
    assert len(world_anim.split_sheet(_figure())) == 1


def test_split_roundtrips_a_real_pack_sheet():
    import world_anim
    cells = world_anim.split_sheet(
        __import__("PIL.Image", fromlist=["Image"]).open(PACK / "Walk_Base/Walk_Side-Sheet.png"))
    assert len(cells) == 6


# ── normalized output ────────────────────────────────────────────────────────
def test_build_sheet_writes_pack_layout(tmp_path):
    import world_anim
    frames = [_figure(leg_dx=d) for d in (0, 7, -7)]
    dst = world_anim.build_sheet(world_anim.expand(frames, "walk"), tmp_path / "walk.png",
                                 cell=64, count=6)
    from PIL import Image
    sh = Image.open(dst)
    assert sh.size == (64 * 6, 64) and sh.mode == "RGBA"
    lo, hi = sh.getchannel("A").getextrema()
    assert lo == 0 and hi > 200                          # transparent bg, opaque figure
    # and it splits straight back into the same frames
    assert len(world_anim.split_sheet(sh, expect=6)) == 6


def test_build_sheet_matches_pack_sheet_shape():
    """Drop-in compatibility: our sheet for an action has the same geometry as
    the pack sheet the renderer already draws."""
    import world_anim
    from PIL import Image
    for action, rel in (("walk", "Walk_Base/Walk_Side-Sheet.png"),
                        ("idle", "Idle_Base/Idle_Side-Sheet.png"),
                        ("work", "Crush_Base/Crush_Side-Sheet.png")):
        pack = Image.open(PACK / rel)
        n = world_anim.frames_for(action)
        assert (n * 64, 64) == pack.size, action


def test_build_sheet_needs_a_frame(tmp_path):
    import world_anim
    with pytest.raises(ValueError):
        world_anim.build_sheet([], tmp_path / "x.png")
