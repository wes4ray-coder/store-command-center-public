"""The Company's generated soundscape — /api/world/audio/* (world_audio.py)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

# tiny-but-valid RIFF/WAVE blob (headers only, zero samples)
_FAKE_WAV = (b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
             b"\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")


def test_assets_catalog_shape(client):
    r = client.get("/api/world/audio/assets")
    assert r.status_code == 200
    j = r.json()
    keys = {a["key"] for a in j["assets"]}
    # ambient beds for every context + the per-action SFX the frontend plays
    assert {"amb_day_spring", "amb_day_summer", "amb_day_autumn", "amb_day_winter",
            "amb_night", "amb_raid"} <= keys
    assert {"mine", "chop", "build", "bless", "coin", "levelup", "shop"} <= keys
    for a in j["assets"]:
        assert a["kind"] in ("ambient", "sfx")
        assert isinstance(a["ready"], bool)
    assert "job" in j


def test_file_404s(client):
    assert client.get("/api/world/audio/file/nope").status_code == 404       # unknown key
    import world_audio as wau
    wau.asset_path("door").unlink(missing_ok=True)
    assert client.get("/api/world/audio/file/door").status_code == 404       # not generated


def test_generate_caches_and_serves(client, monkeypatch, tmp_path):
    """Generation drives the normal audio-clip pipeline; a finished clip is copied
    into the world_audio cache and served. run_audio_clip is stubbed (no GPU)."""
    import services
    import world_audio as wau
    from deps import get_conn

    def fake_run(cid):
        p = tmp_path / f"clip_{cid}.wav"
        p.write_bytes(_FAKE_WAV)
        conn = get_conn()
        conn.execute("UPDATE audio_clips SET status='done', audio_path=? WHERE id=?",
                     (str(p), cid))
        conn.commit()
        conn.close()

    monkeypatch.setattr(services, "run_audio_clip", fake_run)
    wau.asset_path("coin").unlink(missing_ok=True)

    r = client.post("/api/world/audio/generate",
                    json={"keys": ["coin"], "engine": "musicgen"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and j["queued"] == 1 and j["engine"] == "musicgen"

    deadline = time.time() + 10
    while time.time() < deadline:
        if wau._job["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert wau._job["status"] == "done", wau._job

    r = client.get("/api/world/audio/assets")
    coin = next(a for a in r.json()["assets"] if a["key"] == "coin")
    assert coin["ready"] and coin["url"] == "/api/world/audio/file/coin"
    assert coin["engine"] == "musicgen"

    f = client.get("/api/world/audio/file/coin")
    assert f.status_code == 200
    assert f.headers["content-type"].startswith("audio/")
    assert f.content == _FAKE_WAV

    # already-cached → nothing to do (no force)
    r = client.post("/api/world/audio/generate", json={"keys": ["coin"], "engine": "musicgen"})
    assert r.json()["status"] == "nothing_to_do"
