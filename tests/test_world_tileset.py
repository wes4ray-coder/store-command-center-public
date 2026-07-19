"""Progressive agent-filled terrain tilesets — app/world_tileset.py (GPU stubbed)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def _patch_dir(monkeypatch, tmp_path):
    import world_tileset
    monkeypatch.setattr(world_tileset, "TILESET_DIR", tmp_path)
    return world_tileset


def _green_tile(size=64, noise=40):
    """A lush-green noisy tile that passes the QA + grass style gates."""
    from PIL import Image
    base = Image.effect_noise((size, size), noise).convert("L")
    dim = base.point(lambda p: p // 3)
    return Image.merge("RGB", (dim, base, dim))


def _gray_tile(size=64, noise=40):
    """A concrete-gray tile: textured enough for QA, but styleless (sat ~0)."""
    from PIL import Image
    base = Image.effect_noise((size, size), noise).convert("L")
    return Image.merge("RGB", (base, base, base))


def test_seamless_returns_64px_tile(tmp_path):
    from PIL import Image
    import world_tileset
    src = tmp_path / "t.png"
    Image.effect_noise((300, 200), 64).convert("RGB").save(src)
    out = world_tileset._seamless(src)
    assert out.size == (world_tileset.CELL, world_tileset.CELL)


def test_style_check_rejects_clashing_tile(monkeypatch, tmp_path):
    wt = _patch_dir(monkeypatch, tmp_path)          # no atlas → no harmony set
    # a gray concrete slab can never become 'grass'
    ok, why = wt._style_check("grass", _gray_tile())
    assert not ok and "gray" in why.lower()
    # ...but a lush green tile is fine
    ok, why = wt._style_check("grass", _green_tile())
    assert ok, why
    # harmony: a BRIGHT plaza clashes with an installed dark set
    from PIL import Image
    dark = Image.effect_noise((64, 64), 30).point(lambda p: min(p // 2, 70)).convert("RGB")
    bright = Image.effect_noise((64, 64), 30).point(lambda p: max(120, min(210, p + 120))).convert("RGB")
    ok, why = wt._style_check("plaza", bright, live=[dark, dark, dark])
    assert not ok and "clash" in why.lower()
    # stripe gate: a green tile with a bright band tiles as map-wide stripes
    banded = _green_tile()
    band = _green_tile().point(lambda p: min(255, p + 110)).crop((0, 0, 64, 16))
    banded.paste(band, (0, 0))
    ok, why = wt._style_check("grass", banded)
    assert not ok and "band" in why.lower()


def test_generate_tile_progressive_path(monkeypatch, tmp_path, client):
    """One tile lands independently in the atlas + manifest (GPU stubbed)."""
    wt = _patch_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(wt.orch, "image_acquire", lambda: None)
    monkeypatch.setattr(wt.orch, "image_release", lambda: None)

    def fake_run(cmd, **kw):
        _green_tile(512).save(cmd[2])               # cmd[2] = output path
        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(wt.subprocess, "run", fake_run)

    res = wt.generate_tile("grass")
    assert res["ok"], res
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["tiles"]["grass"]["atlas"] == "gen"
    assert m["tiles"]["path"] is None or m["tiles"]["path"].get("atlas") != "gen"
    assert (tmp_path / wt.ATLAS_FILE).exists()
    assert m["v"] > 0
    v1 = m["v"]

    # a clashing render for 'water' (gray) is DISCARDED — manifest untouched
    def fake_run_gray(cmd, **kw):
        _gray_tile(512).save(cmd[2])
        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(wt.subprocess, "run", fake_run_gray)
    res = wt.generate_tile("water")
    assert not res["ok"] and res["reason"]
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert not (isinstance(m["tiles"].get("water"), dict) and m["tiles"]["water"].get("atlas") == "gen")
    assert m["v"] == v1                              # nothing installed, no re-bust needed...
    # structural tiles refuse outright
    assert not wt.generate_tile("floor")["ok"]
    # status surfaces the per-tile view
    st = client.get("/api/world/tileset").json()
    tl = {t["key"]: t for t in st["tiles"]}
    assert tl["grass"]["generated"] and not tl["water"]["generated"] and tl["floor"]["locked"]


def test_reject_endpoint_reverts_logs_and_teaches(monkeypatch, tmp_path, client):
    import world_taste
    wt = _patch_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(world_taste, "_embed", lambda text: None)
    # install a generated grass tile directly
    wt._install_tile("grass", _green_tile())
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["tiles"]["grass"]["atlas"] == "gen"
    v1 = m["v"]

    r = client.post("/api/world/tileset/reject", json={"key": "grass"})
    assert r.status_code == 200 and r.json()["ok"]
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["tiles"]["grass"] is None               # back to procedural
    assert m["v"] >= v1                              # cache-buster moved
    # rejection is remembered as avoid-context…
    rej = wt._recent_rejects("grass")
    assert rej and rej[-1]["key"] == "grass"
    assert wt._avoid_text("grass")
    # …and fed to the god-taste model as a deny example
    from deps import get_conn
    conn = get_conn()
    try:
        row = conn.execute("SELECT label FROM world_taste WHERE skey LIKE 'tile_reject:grass:%'").fetchone()
        assert row is not None and row["label"] == -1.0
    finally:
        conn.close()
    # unknown key → 400
    assert client.post("/api/world/tileset/reject", json={"key": "nope"}).status_code == 400


def test_tile_endpoint_validates_and_guards(monkeypatch, tmp_path, client):
    wt = _patch_dir(monkeypatch, tmp_path)
    assert client.post("/api/world/tileset/tile", json={"key": "nope"}).status_code == 400
    assert client.post("/api/world/tileset/tile", json={"key": "floor"}).status_code == 400
    wt._lock.acquire()
    try:
        assert client.post("/api/world/tileset/tile", json={"key": "grass"}).status_code == 409
        assert client.post("/api/world/tileset", json={}).status_code == 409
    finally:
        wt._lock.release()


def test_auto_tick_toggle_gated(monkeypatch, tmp_path, client):
    import world_settings as ws
    from deps import get_conn
    from world_defs import mset
    wt = _patch_dir(monkeypatch, tmp_path)
    calls = []
    runner = lambda key, agent: calls.append(key)
    conn = get_conn()
    try:
        # OFF (the default) → never fires
        ws.save({"world_tileset_auto": "0"}, conn)
        assert wt.auto_tick(conn, _run=runner) is None and not calls
        # ON → first observation only arms the cadence
        ws.save({"world_tileset_auto": "1", "world_tileset_auto_min": "15"}, conn)
        mset(conn.cursor(), "tileset_auto_last", "")
        assert wt.auto_tick(conn, _run=runner) is None and not calls
        # cadence elapsed → paints exactly one pending (non-structural) tile
        mset(conn.cursor(), "tileset_auto_last", 1.0)
        key = wt.auto_tick(conn, _run=runner)
        assert key in {"grass", "path", "plaza", "water"} and calls == [key]
    finally:
        ws.save({"world_tileset_auto": "0"}, conn)
        conn.commit()
        conn.close()


def test_manifest_write_preserves_user_entries_and_remove_restores(monkeypatch, tmp_path, client):
    wt = _patch_dir(monkeypatch, tmp_path)
    # a user manifest with their own pack mapped
    (tmp_path / "manifest.json").write_text(json.dumps({
        "atlases": [{"id": "mypack", "src": "pack.png"}],
        "sprites": {"workbench": {"atlas": "mypack", "x": 0, "y": 0, "w": 16, "h": 16}},
        "tiles": {"grass": None, "tree": {"atlas": "mypack", "x": 16, "y": 0, "w": 16, "h": 16}},
    }))
    wt._write_manifest({"grass", "path"})
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert {a["id"] for a in m["atlases"]} == {"mypack", "gen"}
    assert m["tiles"]["grass"]["atlas"] == "gen"
    assert m["tiles"]["path"]["x"] == wt.CELL          # second kind, cell offset
    assert m["tiles"]["tree"]["atlas"] == "mypack"     # user mapping untouched
    assert m["sprites"]["workbench"]["atlas"] == "mypack"
    assert wt._installed() is True
    # progressive: a LATER single-tile write keeps the earlier gen keys live
    wt._write_manifest({"water"})
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert m["tiles"]["grass"]["atlas"] == "gen" and m["tiles"]["water"]["atlas"] == "gen"
    # remove → our entries gone, user's survive, procedural fallback
    (tmp_path / wt.ATLAS_FILE).write_bytes(b"png")
    wt.remove()
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert {a["id"] for a in m["atlases"]} == {"mypack"}
    assert m["tiles"]["grass"] is None
    assert m["tiles"]["tree"]["atlas"] == "mypack"
    assert not (tmp_path / wt.ATLAS_FILE).exists()
    assert wt._installed() is False


def test_status_endpoint_and_double_start_guard(monkeypatch, tmp_path, client):
    wt = _patch_dir(monkeypatch, tmp_path)
    r = client.get("/api/world/tileset")
    assert r.status_code == 200 and "installed" in r.json() and "tiles" in r.json()
    # simulate a running generation → POST must 409
    wt._lock.acquire()
    try:
        assert client.post("/api/world/tileset", json={}).status_code == 409
    finally:
        wt._lock.release()
