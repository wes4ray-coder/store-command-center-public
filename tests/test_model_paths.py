"""Model storage locations — app/model_paths.py + /api/models/storage."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def _set(key, val, client):
    r = client.patch("/api/settings", json={key: val})
    assert r.status_code == 200


def test_setting_wins_over_env_default_and_clears_back(client):
    import model_paths as mp
    import config
    assert mp.primary("video") == config.NODE_HF_VIDEO          # unset → env default
    _set("models_dir_video", "/mnt/big/models_video", client)
    assert mp.primary("video") == "/mnt/big/models_video"       # setting wins
    _set("models_dir_video", "", client)
    assert mp.primary("video") == config.NODE_HF_VIDEO          # cleared → fallback


def test_multi_location_first_is_primary(client):
    import model_paths as mp
    _set("models_dir_3d", "/mnt/a/models_3d\n/mnt/b/models_3d, /mnt/c/models_3d/", client)
    assert mp.primary("3d") == "/mnt/a/models_3d"
    assert mp.dirs("3d") == ["/mnt/a/models_3d", "/mnt/b/models_3d", "/mnt/c/models_3d"]
    _set("models_dir_3d", "", client)


def test_audio_empty_means_default_cache(client):
    import model_paths as mp
    _set("models_dir_audio", "", client)
    import os
    if not os.environ.get("STORE_AUDIO_MODELS_DIR"):
        assert mp.primary("audio") == ""                        # '' = node default HF cache
    from services_media import audio_models_dir
    _set("models_dir_audio", "/mnt/ssd/models_audio", client)
    assert audio_models_dir() == "/mnt/ssd/models_audio"        # helper follows the setting
    _set("models_dir_audio", "", client)


def test_storage_endpoint_snapshot(client):
    r = client.get("/api/models/storage")
    assert r.status_code == 200
    kinds = {k["kind"]: k for k in r.json()["kinds"]}
    assert set(kinds) == {"image", "llm", "audio", "video", "3d"}
    for k in kinds.values():
        assert k["setting"].startswith("models_dir_") and "effective" in k and "default" in k


def test_image_download_dest_follows_storage_setting(client):
    import routers.models as rm
    import config
    _set("models_dir_image", "/mnt/nvme/checkpoints", client)
    assert rm._dest_dir({"dest_dir": config.COMFY_CKPT}) == "/mnt/nvme/checkpoints"
    assert rm._dest_dir({}) == "/mnt/nvme/checkpoints"
    # entries with their OWN dir (loras etc.) are untouched
    assert rm._dest_dir({"dest_dir": "~/ComfyUI/models/loras"}) == "~/ComfyUI/models/loras"
    _set("models_dir_image", "", client)
