"""Persistent unified-queue completion history: queue_history table written by the
orchestrator at terminal transitions (done/error/cancelled), source attribution,
retention cap, and the GET /api/queue/history endpoint (filters + summary +
media-table union)."""
import threading
import time


def _row(client_conn_label):
    from db import get_conn
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM queue_history WHERE label LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{client_conn_label}%",)).fetchone()
    finally:
        conn.close()


def _patched_orch(monkeypatch):
    """Neutralise the GPU/SSH side of the orchestrator so tasks run locally."""
    import orchestrator as om
    monkeypatch.setattr(om.orch, "_free_comfyui", lambda: None)
    monkeypatch.setattr(om.orch, "_pick_llm_model", lambda: "test-model")
    monkeypatch.setattr(om.orch, "_ensure_loaded", lambda m: True)
    return om.orch


def test_history_row_on_done(client, monkeypatch):
    orch = _patched_orch(monkeypatch)
    tid = orch.submit_llm(lambda: {"ok": True}, desc="world:think qh-done", task=None)
    assert orch._tasks[tid]["event"].wait(20), "task never finished"
    r = _row("qh-done")
    assert r is not None
    assert r["status"] == "done" and r["kind"] == "llm"
    assert r["source"] == "world"                 # desc prefix "world:" → world
    assert r["model"] == "test-model"             # borrowed resident model recorded
    assert r["enqueued_at"] and r["started_at"] and r["finished_at"]
    assert r["duration_s"] is not None and r["duration_s"] >= 0
    assert r["error"] is None


def test_history_row_on_error(client, monkeypatch):
    orch = _patched_orch(monkeypatch)

    def _boom():
        raise RuntimeError("boom qh-error-detail")
    tid = orch.submit_llm(_boom, desc="proxy:some-model qh-err")
    assert orch._tasks[tid]["event"].wait(20)
    r = _row("qh-err")
    assert r is not None
    assert r["status"] == "error"
    assert "boom qh-error-detail" in (r["error"] or "")
    assert r["source"] == "proxy"                 # desc prefix "proxy:" → proxy


def test_history_row_on_cancel(client):
    import orchestrator as om
    om.orch.pause()
    try:
        tid = om.orch.submit_llm(lambda: "never runs", desc="jelly:mission-draft qh-cancel")
        assert om.orch.cancel(tid)
    finally:
        om.orch.resume()
    r = _row("qh-cancel")
    assert r is not None
    assert r["status"] == "cancelled"
    assert r["source"] == "jellycoin"
    assert r["started_at"] is None and r["duration_s"] is None  # never ran


def test_source_attribution_map():
    from queue_history import derive_source
    # explicit kwarg wins over everything
    assert derive_source("world:think", "image_enhance", "custom") == "custom"
    # task key (prompt registry) beats desc
    assert derive_source("Research: cats", "image_research") == "studio"
    assert derive_source("x", "threed_listing") == "3d"
    assert derive_source("x", "mail_quote") == "mail"
    assert derive_source("x", "money_lead_hunt") == "money"
    assert derive_source("x", "library_rip") == "library"
    # desc prefixes
    assert derive_source("proxy:qwen-3") == "proxy"
    assert derive_source("world:vision:gemma") == "world"
    assert derive_source("jelly:mission-draft") == "jellycoin"
    assert derive_source("research: deep_dig") == "research"
    # desc keywords
    assert derive_source("swarm turn") == "dev-swarm"
    assert derive_source("peer review for buddy: fix tests") == "peers"
    assert derive_source("Private studio: bootstrap prompts") == "private"
    assert derive_source("Assistant agent loop") == "assistant"
    assert derive_source("Trend scan analysis") == "trends"
    assert derive_source("Stocks daily brief") == "crypto"
    assert derive_source("Enhance: neon fox tee") == "studio"
    # fallback: first token of desc
    assert derive_source("Somethingweird happened") == "somethingweird"
    assert derive_source("", None) == "other"


def test_retention_cap_pruned_on_insert(client, monkeypatch):
    import queue_history as qh
    monkeypatch.setattr(qh, "HISTORY_MAX", 5)
    for i in range(8):
        qh.record(kind="llm", label=f"retention row {i}", status="done")
    from db import get_conn
    conn = get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM queue_history").fetchone()[0]
        newest = conn.execute(
            "SELECT label FROM queue_history ORDER BY id DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    assert n == 5                       # capped — oldest pruned on insert
    assert newest == "retention row 7"  # newest kept


def test_history_endpoint_filters_and_summary(client):
    import queue_history as qh
    qh.record(kind="llm", label="ep row A", status="done", task="image_enhance",
              model="m-a", enqueued_at=time.time() - 5, started_at=time.time() - 4)
    qh.record(kind="llm", label="ep row B", status="error", source="world",
              error="x" * 900)
    r = client.get("/api/queue/history")
    assert r.status_code == 200
    body = r.json()
    assert {"items", "summary"} <= set(body)
    labels = [i["label"] for i in body["items"]]
    assert "ep row A" in labels and "ep row B" in labels
    b = next(i for i in body["items"] if i["label"] == "ep row B")
    assert len(b["error"]) <= 500       # error text truncated at write
    # filters
    r2 = client.get("/api/queue/history?status=error&source=world").json()
    assert r2["items"]
    assert all(i["status"] == "error" and i["source"] == "world" for i in r2["items"])
    r3 = client.get("/api/queue/history?kind=llm&limit=3").json()
    assert len(r3["items"]) <= 3 and all(i["kind"] == "llm" for i in r3["items"])
    # summary counts by source/status over 24h
    s = body["summary"]
    assert s["window_h"] == 24
    assert s["by_source"].get("studio", 0) >= 1   # ep row A attributed via task key
    assert s["by_source"].get("world", 0) >= 1
    assert s["by_status"].get("done", 0) >= 1 and s["by_status"].get("error", 0) >= 1


def test_history_endpoint_unions_media_tables(client):
    from db import get_conn
    conn = get_conn()
    conn.execute("INSERT INTO generations (prompt, status) VALUES ('media union test qh', 'done')")
    conn.execute(
        "INSERT INTO audio_clips (prompt, status, error) VALUES ('audio union test qh', 'failed', 'gpu oom')")
    conn.commit()
    conn.close()
    body = client.get("/api/queue/history?limit=200").json()
    img = next((i for i in body["items"] if i["label"] == "media union test qh"), None)
    assert img is not None and img["kind"] == "image" and img["status"] == "done"
    assert img["source"] == "studio"    # media rows are labelled, not re-written
    aud = next((i for i in body["items"] if i["label"] == "audio union test qh"), None)
    assert aud is not None and aud["kind"] == "audio" and aud["status"] == "error"
    assert aud["error"] == "gpu oom"
