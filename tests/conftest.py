"""Test fixtures — everything runs against a THROWAWAY data dir, never the live store.db.

`STORE_DATA_DIR` is set to a temp dir BEFORE any app module is imported, so config.DB_PATH
(and all designs/backups paths) resolve there. Background sim/monitor threads are stubbed
out so the TestClient startup stays light and deterministic.
"""
import os
import sys
import tempfile
from pathlib import Path

# 1) Redirect ALL data to a throwaway dir before importing the app.
_TMP = Path(tempfile.mkdtemp(prefix="storetest_"))
os.environ["STORE_DATA_DIR"] = str(_TMP)
# Mount at root so the session cookie's path is "/" (live it's /store, set via
# STORE_BASE_PATH). Otherwise the cookie is scoped to /store and never sent to the
# un-prefixed /api/... routes the TestClient hits, 401-ing every authenticated call.
os.environ["STORE_BASE_PATH"] = ""

# 2) The app runs with cwd=app/ and imports its modules as top-level (from deps import ...).
APP_DIR = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

import pytest  # noqa: E402

# 3) Neutralize background threads (world sim, autopilot, security monitor) so app startup
#    doesn't spawn writers that contend for the temp DB during tests.
import world_ticker  # noqa: E402
import world_auto     # noqa: E402
import scheduler      # noqa: E402
world_ticker.start = lambda *a, **k: None
world_auto.start = lambda *a, **k: None
scheduler.start = lambda *a, **k: None

import db as _db  # noqa: E402

# Hard guard: the whole suite MUST run against the temp dir, never the live store.db.
assert str(_db.DB_PATH).startswith(str(_TMP)), (
    f"UNSAFE: DB_PATH={_db.DB_PATH} is not under the temp dir {_TMP}. Aborting so tests "
    f"can't touch live data."
)
_db.init_db()


@pytest.fixture(scope="session")
def client():
    """An authenticated TestClient. Uses an https base_url so the Secure session cookie
    is sent back; logs in with the first-run default password ("store")."""
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app, base_url="https://testserver") as c:
        r = c.post("/login", data={"password": "store"}, follow_redirects=False)
        assert r.status_code in (200, 302, 303), f"login failed: {r.status_code} {r.text[:200]}"
        yield c
