"""The resell automation browser must never RESTORE stale tabs (app/browser.py).

Regression for the "a Facebook Marketplace tab keeps popping up on a schedule" bug: a
half-finished FB login/post left in the profile's saved session was being restored on
every relaunch. _clear_session() wipes that state so each launch starts clean.
"""
import json


def test_clear_session_wipes_restore_state():
    import browser
    prof = browser.PROFILE_DIR / "Default"
    (prof / "Sessions").mkdir(parents=True, exist_ok=True)
    (prof / "Sessions" / "Tabs_123").write_text("...https://www.facebook.com/marketplace/inbox/...")
    (prof / "Current Session").write_text("x")
    (prof / "Last Tabs").write_text("x")
    (prof / "Preferences").write_text(json.dumps(
        {"profile": {"exit_type": "Crashed"}, "session": {"restore_on_startup": 1}}))

    browser.browser._clear_session()

    # all saved tab/session state is gone → nothing to restore
    assert not (prof / "Sessions").exists()
    assert not (prof / "Current Session").exists()
    assert not (prof / "Last Tabs").exists()
    # preferences flipped to "start clean, don't restore, no crash prompt"
    p = json.loads((prof / "Preferences").read_text())
    assert p["session"]["restore_on_startup"] == 5      # 5 = new tab page
    assert p["profile"]["exit_type"] == "Normal"
    assert p["profile"]["exited_cleanly"] is True


def test_clear_session_safe_when_nothing_exists():
    import browser, shutil
    shutil.rmtree(browser.PROFILE_DIR, ignore_errors=True)
    browser.browser._clear_session()   # must not raise on a fresh/absent profile
