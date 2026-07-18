"""Unified queue Pause / Start / Clear controls (dashboard.py + orchestrator pause gate)."""


def test_queue_reports_paused_flag(client):
    q = client.get("/api/queue").json()
    assert "paused" in q and isinstance(q["paused"], bool)


def test_pause_then_resume_flips_flag(client):
    try:
        r = client.post("/api/queue/pause")
        assert r.status_code == 200 and r.json()["paused"] is True
        assert client.get("/api/queue").json()["paused"] is True
    finally:
        r = client.post("/api/queue/resume")
        assert r.status_code == 200 and r.json()["paused"] is False
    assert client.get("/api/queue").json()["paused"] is False


def test_clear_returns_counts_and_leaves_queue_running(client):
    r = client.post("/api/queue/clear")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # every source reports a cleared count / status
    assert set(body["cleared"]) >= {"llm", "videos", "video_chains", "audio_clips", "comfyui"}
    # clearing must not pause the queue
    assert client.get("/api/queue").json()["paused"] is False
