"""A fresh clone must boot — no runtime dir, no crash.

designs/ and videos/ are runtime media dirs: gitignored (or dropped by the retail
scrub), so a fresh clone of the public release has neither. They are mounted with
StaticFiles at IMPORT time, which raises "Directory does not exist" and kills the
app before it serves anything — while startup()/setup.sh, which create them, run
too late or not at all. Regression guard: importing main must create what it mounts.
"""
import importlib
import shutil

from config import BASE


def test_mounted_runtime_dirs_exist_after_import():
    import main  # noqa: F401
    for d in ("designs", "videos"):
        assert (BASE / d).is_dir(), f"{d}/ must exist — it is mounted at import"


def test_import_recreates_a_missing_media_dir(tmp_path):
    """Delete the dir a fresh clone wouldn't have, re-import, and it comes back."""
    victim = BASE / "videos"
    backup = tmp_path / "videos-backup"
    if victim.exists():
        shutil.move(str(victim), str(backup))
    assert not victim.exists()
    try:
        import main
        importlib.reload(main)          # the import-time mount must not explode
        assert victim.is_dir(), "re-import must recreate the mounted media dir"
    finally:
        if backup.exists():
            if victim.exists():
                shutil.rmtree(victim)
            shutil.move(str(backup), str(victim))
