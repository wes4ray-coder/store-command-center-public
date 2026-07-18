"""world_build.rework_prop — reject → tweak loop for world creations (prompt amend)."""
import world_build
import db


def _prop(prompt):
    conn = db.get_conn()
    cur = conn.execute("INSERT INTO world_props (kind,label,prompt,status) VALUES ('decor','lamp',?, 'done')", (prompt,))
    pid = cur.lastrowid
    conn.commit(); conn.close()
    return pid


def _read(pid):
    conn = db.get_conn()
    row = conn.execute("SELECT prompt,status FROM world_props WHERE id=?", (pid,)).fetchone()
    conn.close()
    return row


def test_rework_amends_prompt_and_queues(monkeypatch):
    monkeypatch.setattr(world_build, "generate_world_prop", lambda pid: None)  # no GPU in tests
    pid = _prop("a cool lamp, pixels")
    world_build.rework_prop(pid, "make it brighter")
    row = _read(pid)
    assert "[note: make it brighter]" in row["prompt"] and row["status"] == "queued"


def test_rework_strips_prior_note(monkeypatch):
    monkeypatch.setattr(world_build, "generate_world_prop", lambda pid: None)
    pid = _prop("a lamp  [note: old feedback]")
    world_build.rework_prop(pid, "new feedback")
    p = _read(pid)["prompt"]
    assert "old feedback" not in p and "[note: new feedback]" in p


def test_rework_without_reason_still_notes(monkeypatch):
    monkeypatch.setattr(world_build, "generate_world_prop", lambda pid: None)
    pid = _prop("a lamp")
    world_build.rework_prop(pid, "")
    assert "[note:" in _read(pid)["prompt"]
