"""Board design-image URLs resolve to the file's CURRENT folder (pending→approved/rejected)."""
from config import DESIGNS_PENDING, DESIGNS_APPROVED
from routers import world_ops as wo


def test_designs_url_follows_folder_move():
    DESIGNS_PENDING.mkdir(parents=True, exist_ok=True)
    DESIGNS_APPROVED.mkdir(parents=True, exist_ok=True)
    (DESIGNS_APPROVED / "gen_move.png").write_bytes(b"x")
    # generations row still has the ORIGINAL pending path; resolver finds it in approved
    assert wo._designs_url("/data/designs/pending/gen_move.png") == "/store/designs/approved/gen_move.png"


def test_designs_url_none_when_file_gone():
    assert wo._designs_url("/data/designs/pending/nope_zzz.png") is None
    assert wo._designs_url("") is None
