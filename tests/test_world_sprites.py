"""Per-entity sprite-sheet registry — app/world_sprites.py (GPU stubbed).

Covers the gates (transparency / pack-first / toggles / budget / frame QA), the
real per-pose sheet build, and the core get-or-enqueue contract: a sheet is
generated ONCE, cached in the entity's manifest, and every later request is a
cache hit. The animation maths itself lives in tests/test_world_anim.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


class _NoGPU:
    def image_acquire(self): pass
    def image_release(self): pass


def _patch(monkeypatch, tmp_path):
    import world_sprites as wsp
    monkeypatch.setattr(wsp, "ENTITIES_DIR", tmp_path / "entities")
    monkeypatch.setattr(wsp, "orch", _NoGPU())
    monkeypatch.setattr(wsp, "_qa", lambda p, l: (True, 8, ""))
    wsp._mem["pack_actions"] = None
    return wsp


def _sprite(transparent=True, size=64, leg_dx=0):
    """A PIL sprite: a centered figure on a transparent (or baked) background.
    `leg_dx` swings the legs — that is what makes two frames a real pose change
    rather than the same drawing nudged (see tests/test_world_anim.py)."""
    from PIL import Image, ImageDraw
    bg = (0, 0, 0, 0) if transparent else (90, 140, 200, 255)
    im = Image.new("RGBA", (size, size), bg)
    d = ImageDraw.Draw(im)
    cx = size // 2
    d.rectangle([size // 4, size // 5, 3 * size // 4, size - 22], fill=(200, 90, 60, 255))
    d.rectangle([cx - 9 - leg_dx, size - 22, cx - 2 - leg_dx, size - 4], fill=(60, 60, 110, 255))
    d.rectangle([cx + 2 + leg_dx, size - 22, cx + 9 + leg_dx, size - 4], fill=(60, 60, 110, 255))
    return im


def _stub_render(wsp, monkeypatch, transparent=True, animate=True):
    """Stub the GPU render + pixelate. With `animate` on, each POSE prompt lands a
    genuinely different drawing (the pose phrase picks the leg swing) — which is
    what the real pipeline has to do to get past frame QA. With it off every pose
    renders the same still, i.e. the old bug, and the sheet must be refused."""
    calls = {"n": 0, "prompts": []}

    def _for(prompt):
        """Which KEY pose was asked for? Match the pose phrase itself — keyword
        sniffing collides with the look text ('bold dark outline' contains 'out')."""
        if not animate:
            return _sprite(transparent)
        import world_anim
        for spec in world_anim.POSE_SCRIPTS.values():
            for i, (_key, phrase) in enumerate(spec["keys"]):
                if phrase in (prompt or ""):
                    return _sprite(transparent, leg_dx=(0, 15, -15)[i % 3])
        return _sprite(transparent)

    def fake_render(prompt, out_raw, seed=None):
        calls["n"] += 1
        calls["prompts"].append(prompt)
        _for(prompt).save(out_raw)
        return True

    monkeypatch.setattr(wsp, "_render_sprite", fake_render)
    import world_build
    monkeypatch.setattr(
        world_build, "_pixelate",
        lambda src, dst, cells=64, colors=28: __import__("PIL.Image", fromlist=["Image"])
        .open(src).convert("RGBA").save(dst))
    return calls


# ── gates ────────────────────────────────────────────────────────────────────
def test_alpha_ok_accepts_cutout_rejects_boxes():
    import world_sprites as wsp
    assert wsp.alpha_ok(_sprite(transparent=True))
    assert not wsp.alpha_ok(_sprite(transparent=False))          # baked background
    from PIL import Image
    assert not wsp.alpha_ok(Image.new("RGBA", (64, 64), (0, 0, 0, 0)))   # shredded/empty


def test_make_static_sheet_is_one_honest_frame(tmp_path):
    """The hold sheet is ONE frame and says so — it must never masquerade as a
    multi-frame animation, which is exactly what the old code did."""
    import world_sprites as wsp
    from PIL import Image
    for action in ("idle", "lying"):
        dst = tmp_path / f"{action}.png"
        wsp.make_static_sheet(_sprite(), action, dst)
        sh = Image.open(dst)
        assert sh.size == (wsp.CELL, wsp.CELL)
        lo, hi = sh.getchannel("A").getextrema()
        assert lo == 0 and hi > 200                              # transparent bg, opaque figure


def test_pack_first_for_agents_without_own_look(monkeypatch, tmp_path):
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = {"walk", "idle", "work"}
    r = wsp.get_or_enqueue("agent_x", "walk", kind="agent")
    assert r["status"] == "pack"


def test_pack_match_is_conservative(monkeypatch, tmp_path):
    wsp = _patch(monkeypatch, tmp_path)
    ex = tmp_path / "_extracted"
    ex.mkdir()
    (ex / "prop_barrel.png").write_bytes(b"x")
    monkeypatch.setattr(wsp, "EXTRACTED", ex)
    assert "prop_barrel.png" in (wsp.pack_match("a wooden barrel") or "")
    assert wsp.pack_match("lava lamp") is None
    assert wsp.pack_match("") is None


def test_disabled_toggle_blocks_generation(monkeypatch, tmp_path):
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()
    monkeypatch.setattr(wsp.ws, "b", lambda k, c=None: False)
    r = wsp.get_or_enqueue("agent_x", "fishing", kind="agent")
    assert r["status"] == "disabled"


def test_budget_cap_blocks_generation(monkeypatch, tmp_path):
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()
    monkeypatch.setattr(wsp, "_hour_budget_ok", lambda c=None: False)
    r = wsp.get_or_enqueue("agent_x", "fishing", kind="agent")
    assert r["status"] == "capped"


# ── the core contract: generated ONCE, cached forever ────────────────────────
def test_get_or_enqueue_generates_once_then_cache_hits(monkeypatch, tmp_path):
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()                    # nothing pack-covered
    calls = _stub_render(wsp, monkeypatch, transparent=True)
    monkeypatch.setattr(wsp, "_hour_budget_spend", lambda: None)

    ran = {}
    def sync_runner():
        ran["res"] = wsp._generate("agent_t", "fishing", "test agent")
    r1 = wsp.get_or_enqueue("agent_t", "fishing", label="test agent", _runner=sync_runner)
    assert r1["status"] == "queued"
    assert ran["res"]["ok"] and ran["res"]["source"] == "generated"

    # one GPU render per KEY pose — not one render stretched into a sheet
    import world_anim
    assert calls["n"] == len(world_anim.keys_for("fishing"))
    # manifest has the sheet + provenance, in the PACK's frame count for the action
    m = wsp.manifest("agent_t")
    meta = m["sheets"]["fishing"]
    assert meta["frames"] == world_anim.frames_for("fishing") and meta["score"] == 8
    sheet = tmp_path / "entities" / "agent_t" / "fishing.png"
    assert sheet.exists()
    from PIL import Image
    assert Image.open(sheet).size == (wsp.CELL * meta["frames"], wsp.CELL)
    assert not m["pending"]

    # second request = cache hit — no new render, ever
    r2 = wsp.get_or_enqueue("agent_t", "fishing", label="test agent",
                            _runner=lambda: (_ for _ in ()).throw(AssertionError("regenerated!")))
    assert r2["status"] == "ready" and r2["url"].endswith("fishing.png")
    assert calls["n"] == len(world_anim.keys_for("fishing"))


def test_opaque_render_never_installs(monkeypatch, tmp_path):
    """Picture-box outputs are rejected; with no base sprite to derive from the
    action fails cleanly (pending cleared, nothing in the manifest)."""
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()
    _stub_render(wsp, monkeypatch, transparent=False)
    monkeypatch.setattr(wsp, "_hour_budget_spend", lambda: None)
    res = wsp._generate("agent_o", "work", "test")
    assert not res["ok"]
    m = wsp.manifest("agent_o")
    assert "work" not in m["sheets"] and not m["pending"]


def test_opaque_render_installs_nothing_even_with_a_base(monkeypatch, tmp_path):
    """An entity WITH a vetted base sprite must NOT get a sheet derived from that
    still when the fresh render fails — deriving a "sheet" from one drawing is
    the bug. Nothing installs, so the render chain falls back to the pack."""
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()
    wsp.install_base("agent_d", _sprite(), "pixel villager", actions=("idle",))
    _stub_render(wsp, monkeypatch, transparent=False)
    res = wsp._generate("agent_d", "work", "test")
    assert not res["ok"]
    assert not (tmp_path / "entities" / "agent_d" / "work.png").exists()
    assert "work" not in wsp.manifest("agent_d")["sheets"]


def test_static_frames_are_refused_and_the_reason_is_recorded(monkeypatch, tmp_path):
    """THE bug, end to end: every pose renders the same still, so the sheet is
    near-identical frames. It must be refused and the reason surfaced."""
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()
    _stub_render(wsp, monkeypatch, transparent=True, animate=False)
    monkeypatch.setattr(wsp, "_hour_budget_spend", lambda: None)
    res = wsp._generate("agent_static", "walk", "test")
    assert not res["ok"] and "near-identical" in res["reason"]
    m = wsp.manifest("agent_static")
    assert "walk" not in m["sheets"] and not m["pending"]
    assert "near-identical" in m["failed"]["walk"]["reason"]
    assert "walk" in (wsp.index().get("agent_static") or {}).get("failed", {})


def test_install_base_registers_the_look_but_fabricates_no_animation(monkeypatch, tmp_path):
    """install_base records the look and what the entity WANTS; it must not
    manufacture animated sheets out of the single base still."""
    wsp = _patch(monkeypatch, tmp_path)
    m = wsp.install_base("agent_p", _sprite(), "pixel art hero", seed="42",
                         score=9, actions=("idle", "walk", "lying"))
    assert m["look"] == "pixel art hero" and m["seed"] == "42"
    assert set(m["sheets"]) == {"lying"}                    # only the genuinely-static one
    assert m["sheets"]["lying"]["frames"] == 1 and m["sheets"]["lying"]["source"] == "static"
    assert set(m["wanted"]) == {"idle", "walk"}             # recorded, to be rendered properly
    assert (tmp_path / "entities" / "agent_p" / "base.png").exists()


def test_regenerate_clears_the_sheet_and_requeues(monkeypatch, tmp_path):
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()
    calls = _stub_render(wsp, monkeypatch, transparent=True)
    monkeypatch.setattr(wsp, "_hour_budget_spend", lambda: None)
    assert wsp._generate("agent_r", "walk", "test")["ok"]
    sheet = tmp_path / "entities" / "agent_r" / "walk.png"
    assert sheet.exists()
    started = {}
    monkeypatch.setattr(wsp.threading, "Thread",
                        lambda target, args=(), daemon=None: type(
                            "T", (), {"start": lambda s: started.setdefault("a", args)})())
    r = wsp.regenerate("agent_r", "walk")
    assert r["status"] == "queued" and started["a"][1] == "walk"
    assert not sheet.exists()                              # old sheet dropped
    assert "walk" not in wsp.manifest("agent_r")["sheets"]


def test_regenerate_respects_the_toggles(monkeypatch, tmp_path):
    """Re-rolling is not a way around the gates."""
    wsp = _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(wsp.ws, "b", lambda k, c=None: False)
    assert wsp.regenerate("agent_r", "walk")["status"] == "disabled"
    monkeypatch.setattr(wsp.ws, "b", lambda k, c=None: True)
    monkeypatch.setattr(wsp, "_hour_budget_ok", lambda c=None: False)
    assert wsp.regenerate("agent_r", "walk")["status"] == "capped"


def test_install_sheet_image_splits_and_vets_a_dropped_in_sheet(monkeypatch, tmp_path):
    """An owner-supplied SHEET is split into cells, vetted, and rebuilt in the
    pack layout — and a static one is refused like any other."""
    wsp = _patch(monkeypatch, tmp_path)
    import world_anim
    from PIL import Image
    good = [_sprite(leg_dx=d) for d in (0, 9, -9)]
    strip = Image.new("RGBA", (64 * 3, 64), (0, 0, 0, 0))
    for i, f in enumerate(good):
        strip.paste(f, (64 * i, 0), f)
    ok, why, meta = wsp.install_sheet_image("agent_drop", "walk", strip)
    assert ok, why
    # 3 key poses in → normalized out to the pack's 6-frame walk layout
    assert meta["frames"] == world_anim.frames_for("walk") == 6
    assert meta["source"] == "dropped-in"
    assert Image.open(tmp_path / "entities" / "agent_drop" / "walk.png").size == (64 * 6, 64)

    flat = Image.new("RGBA", (64 * 3, 64), (0, 0, 0, 0))    # the same still, three times
    for i in range(3):
        flat.paste(good[0], (64 * i, 0), good[0])
    ok2, why2, _ = wsp.install_sheet_image("agent_drop2", "walk", flat)
    assert not ok2 and "near-identical" in why2


def test_pack_stays_the_fallback_when_generation_is_refused(monkeypatch, tmp_path):
    """Fallback ordering: a refused own sheet must leave the entity resolving to
    the pack, never to a blank or a fake sheet."""
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = {"walk"}
    _stub_render(wsp, monkeypatch, transparent=True, animate=False)
    monkeypatch.setattr(wsp, "_hour_budget_spend", lambda: None)
    assert not wsp._generate("agent_fb", "walk", "test")["ok"]
    # no own look established → the pack answers for it
    assert wsp.get_or_enqueue("agent_fb", "walk", kind="agent")["status"] == "pack"


def test_prop_generation_prefers_pack_asset(monkeypatch, tmp_path, client):
    """world_build.generate_world_prop resolves a pack-covered label WITHOUT
    touching the GPU: the extracted sprite becomes the prop image directly."""
    import world_build
    from deps import get_conn
    ex = tmp_path / "_extracted"
    ex.mkdir()
    (ex / "prop_barrel.png").write_bytes(b"x")
    import world_sprites as wsp
    monkeypatch.setattr(wsp, "EXTRACTED", ex)
    monkeypatch.setattr(world_build, "_render_candidates",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("GPU was hit!")))
    conn = get_conn()
    try:
        pid = conn.execute(
            "INSERT INTO world_props (kind,label,location,prompt,status) "
            "VALUES ('furniture','wooden barrel','home','', 'queued')").lastrowid
        conn.commit()
    finally:
        conn.close()
    world_build.generate_world_prop(pid)
    conn = get_conn()
    try:
        row = conn.execute("SELECT status,image_path,verdict FROM world_props WHERE id=?", (pid,)).fetchone()
    finally:
        conn.close()
    assert row["status"] == "done"
    assert row["image_path"].endswith("_extracted/prop_barrel.png")
    assert row["verdict"] == "pack asset"


def test_failed_action_is_not_re_enqueued_until_the_cooldown(monkeypatch, tmp_path):
    """A frame-QA rejection is systematic, so re-asking every render tick would
    just burn the hourly budget on the same answer. The owner's Re-roll (force)
    still gets through."""
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()
    _stub_render(wsp, monkeypatch, transparent=True, animate=False)
    monkeypatch.setattr(wsp, "_hour_budget_spend", lambda: None)
    assert not wsp._generate("agent_cool", "walk", "test")["ok"]

    r = wsp.get_or_enqueue("agent_cool", "walk",
                           _runner=lambda: (_ for _ in ()).throw(AssertionError("re-burned GPU!")))
    assert r["status"] == "failed" and "near-identical" in r["reason"]

    # once the cooldown lapses it may try again
    m = wsp.manifest("agent_cool")
    m["failed"]["walk"]["t"] = 0
    wsp._save_manifest("agent_cool", m)
    ran = {}
    r2 = wsp.get_or_enqueue("agent_cool", "walk", _runner=lambda: ran.setdefault("go", True))
    assert r2["status"] == "queued" and ran.get("go")


def test_manifest_drops_pre_qa_derived_sheets(monkeypatch, tmp_path):
    """Sheets made by the old transform trick carry no frame-QA record. They are
    dropped on read so the world stops playing the fake animations; genuinely
    static holds and pack entries survive."""
    wsp = _patch(monkeypatch, tmp_path)
    eid = "agent_legacy"
    d = tmp_path / "entities" / eid
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"entity": eid, "sheets": {
        "walk": {"file": "walk.png", "frames": 4, "source": "derived",
                 "provenance": {"t": 1}},                              # fake
        "idle": {"file": "idle.png", "frames": 4, "source": "generated",
                 "provenance": {"t": 1}},                              # fake too
        "lying": {"file": "lying.png", "frames": 1, "source": "static",
                  "provenance": {"t": 1}},                             # honest hold
        "run": {"file": "run.png", "frames": 6, "source": "generated",
                "provenance": {"t": 2, "qa": {"articulation": 0.4}}},  # real
    }, "pending": {}}))
    m = wsp.manifest(eid)
    assert set(m["sheets"]) == {"lying", "run"}


def test_manifest_drops_stale_pending(monkeypatch, tmp_path):
    wsp = _patch(monkeypatch, tmp_path)
    eid = "agent_s"
    d = tmp_path / "entities" / eid
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(
        {"entity": eid, "sheets": {}, "pending": {"work": 1.0}}))   # ancient
    m = wsp.manifest(eid)
    assert m["pending"] == {}


# ── the owner-facing endpoints ───────────────────────────────────────────────
def test_regenerate_endpoint_is_wired_and_gated(monkeypatch, tmp_path, client):
    """POST /api/world/sprites/{entity}/{action}/regenerate reaches
    world_sprites.regenerate and reports its gated status."""
    import world_sprites as wsp
    seen = {}

    def fake_regen(entity_id, action, label=""):
        seen.update(entity=entity_id, action=action, label=label)
        return {"status": "queued", "entity": entity_id, "action": action}

    monkeypatch.setattr(wsp, "regenerate", fake_regen)
    r = client.post("/api/world/sprites/agent_zz/walk/regenerate",
                    json={"label": "a villager"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued"
    assert seen == {"entity": "agent_zz", "action": "walk", "label": "a villager"}

    # the plain get-or-enqueue route still resolves (no path-shadowing)
    monkeypatch.setattr(wsp, "get_or_enqueue",
                        lambda *a, **k: {"status": "pack"})
    assert client.post("/api/world/sprites/agent_zz/walk", json={}).json()["status"] == "pack"


def test_sprites_index_exposes_frames_speed_and_failures(monkeypatch, tmp_path, client):
    """The renderer needs frames+spd per sheet, and the owner needs to see WHY an
    action has no own sheet rather than it silently falling back."""
    import world_sprites as wsp
    monkeypatch.setattr(wsp, "ENTITIES_DIR", tmp_path / "entities")
    d = tmp_path / "entities" / "agent_ix"
    d.mkdir(parents=True)
    _sprite().save(d / "walk.png")
    (d / "manifest.json").write_text(json.dumps({
        "entity": "agent_ix",
        "sheets": {"walk": {"file": "walk.png", "frames": 6, "fw": 64, "fh": 64,
                            "spd": 110, "source": "generated",
                            "provenance": {"t": 9, "qa": {"articulation": 0.4}}}},
        "pending": {}, "failed": {"work": {"reason": "near-identical frames", "t": 9}}}))
    j = client.get("/api/world/sprites").json()
    ent = j["entities"]["agent_ix"]
    assert ent["sheets"]["walk"]["frames"] == 6
    assert ent["sheets"]["walk"]["spd"] == 110
    assert ent["failed"]["work"] == "near-identical frames"


# ── the frame-QA gate ships with a toggle (house rule: never hard-code gating) ─
def test_frame_qa_toggle_off_installs_whatever_rendered(monkeypatch, tmp_path):
    """world_sprites_frame_qa OFF = the owner has chosen to accept the output,
    so a static set installs instead of being refused."""
    wsp = _patch(monkeypatch, tmp_path)
    wsp._mem["pack_actions"] = set()
    _stub_render(wsp, monkeypatch, transparent=True, animate=False)
    monkeypatch.setattr(wsp, "_hour_budget_spend", lambda: None)
    monkeypatch.setattr(wsp.ws, "b",
                        lambda k, c=None: False if k == "world_sprites_frame_qa" else True)
    res = wsp._generate("agent_qaoff", "walk", "test")
    assert res["ok"]
    assert "walk" in wsp.manifest("agent_qaoff")["sheets"]


def test_qa_strictness_setting_moves_the_gate(monkeypatch, tmp_path):
    """world_sprites_qa_strict is a % of what the reference pack achieves, so one
    dial tunes every action's gate."""
    import world_anim
    assert world_anim.gate_for("walk", 40) == round(world_anim.PACK_ARTICULATION["walk"] * 0.4, 4)
    assert world_anim.gate_for("walk", 10) < world_anim.gate_for("walk", 80)
    # an action the pack does not cover keeps its own tuned gate
    assert world_anim.gate_for("nosuchaction", 40) == world_anim.POSE_SCRIPTS["idle"]["gate"]


def test_settings_are_registered_with_the_right_types():
    """A new setting that is not in INT_KEYS/BOOL_KEYS silently reads as a string."""
    import world_settings as ws
    assert ws.DEFAULTS["world_sprites_frame_qa"] == "1"
    assert ws.DEFAULTS["world_sprites_qa_strict"] == "40"
    assert "world_sprites_frame_qa" in ws.BOOL_KEYS
    assert "world_sprites_qa_strict" in ws.INT_KEYS


def test_every_rendered_sprite_setting_is_also_saveable():
    """worldSaveSettings() posts an explicit key whitelist, so a control can
    render in the panel and silently never save. Pin the two lists together."""
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "world-actions.js").read_text()
    rendered = set(re.findall(r"(?:chk|num|txt)\('(world_sprites_[a-z_]+)'", js))
    save_block = js.split("async function worldSaveSettings")[1].split("]")[0]
    saved = set(re.findall(r"'(world_sprites_[a-z_]+)'", save_block))
    assert rendered, "no sprite settings found in the panel"
    assert rendered <= saved, f"rendered but never saved: {sorted(rendered - saved)}"
