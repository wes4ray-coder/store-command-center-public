"""Generated terrain tilesets — app/world_tileset.py (pure parts; no GPU)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def _patch_dir(monkeypatch, tmp_path):
    import world_tileset
    monkeypatch.setattr(world_tileset, "TILESET_DIR", tmp_path)
    return world_tileset


def test_seamless_returns_64px_tile(tmp_path):
    from PIL import Image
    import world_tileset
    src = tmp_path / "t.png"
    Image.effect_noise((300, 200), 64).convert("RGB").save(src)
    out = world_tileset._seamless(src)
    assert out.size == (world_tileset.CELL, world_tileset.CELL)


def test_manifest_write_preserves_user_entries_and_remove_restores(monkeypatch, tmp_path, client):
    wt = _patch_dir(monkeypatch, tmp_path)
    # a user manifest with their own pack mapped
    (tmp_path / "manifest.json").write_text(json.dumps({
        "atlases": [{"id": "mypack", "src": "pack.png"}],
        "sprites": {"workbench": {"atlas": "mypack", "x": 0, "y": 0, "w": 16, "h": 16}},
        "tiles": {"grass": None, "tree": {"atlas": "mypack", "x": 16, "y": 0, "w": 16, "h": 16}},
    }))
    wt._write_manifest("neo", {"grass", "path"})
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert {a["id"] for a in m["atlases"]} == {"mypack", "gen"}
    assert m["tiles"]["grass"]["atlas"] == "gen"
    assert m["tiles"]["path"]["x"] == wt.CELL          # second kind, cell offset
    assert m["tiles"]["tree"]["atlas"] == "mypack"     # user mapping untouched
    assert m["sprites"]["workbench"]["atlas"] == "mypack"
    assert wt._installed() is True
    # remove → our entries gone, user's survive, procedural fallback
    (tmp_path / "gen_neo.png").write_bytes(b"png")
    wt.remove()
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert {a["id"] for a in m["atlases"]} == {"mypack"}
    assert m["tiles"]["grass"] is None
    assert m["tiles"]["tree"]["atlas"] == "mypack"
    assert not (tmp_path / "gen_neo.png").exists()
    assert wt._installed() is False


def test_status_endpoint_and_double_start_guard(monkeypatch, tmp_path, client):
    wt = _patch_dir(monkeypatch, tmp_path)
    r = client.get("/api/world/tileset")
    assert r.status_code == 200 and "installed" in r.json()
    # simulate a running generation → POST must 409
    wt._lock.acquire()
    try:
        assert client.post("/api/world/tileset", json={}).status_code == 409
    finally:
        wt._lock.release()
