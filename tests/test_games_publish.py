"""🎮 Games → shop: listing drafts and the push that must always be a Woo DRAFT.

Nothing here touches a real shop or a real node: `_wc()`/`_mcp()` and the ssh helper
are monkeypatched. The load-bearing guarantees pinned by these tests are:

  * a push creates a WooCommerce product with status="draft" and NEVER "publish"
  * re-pushing UPDATES the same product id instead of creating a duplicate
  * missing Woo credentials explain themselves (400) instead of blowing up (500)
  * generated description copy goes through orch.submit_llm — never a direct LLM call
  * the project's location on disk never reaches the shop payload
"""
import json

import pytest


@pytest.fixture
def gp():
    import routers.games_publish as m
    return m


@pytest.fixture
def no_gate(gp):
    """The confirm gate is a toggle (house rule); most tests drive with it off."""
    import db
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('games_publish_gate','0')")
    conn.commit()
    conn.close()
    yield
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('games_publish_gate','1')")
    conn.commit()
    conn.close()


class FakeWoo:
    """Records every write so tests can assert on the exact payload Woo would get."""

    def __init__(self, next_id=4242):
        self.calls = []
        self.next_id = next_id

    def ensure_category(self, name):
        return 7

    def _req(self, method, path, *, params=None, json=None):
        self.calls.append((method, path, json))
        if method == "POST":
            pid = self.next_id
            self.next_id += 1
        else:
            pid = int(path.rsplit("/", 1)[-1])
        return {"id": pid, "status": (json or {}).get("status"),
                "permalink": f"https://shop.example/?p={pid}"}


def _mk_draft(client, **over):
    body = {"project_path": "~/games/Smoke_Test", "project_name": "Smoke_Test",
            "engine": "unity", "title": "Smoke Test", "price": 9.99,
            "short_desc": "A tiny game.", "long_desc": "<p>Longer copy.</p>",
            "tags": "indie, action"}
    body.update(over)
    r = client.post("/api/games/publish/draft", json=body)
    assert r.status_code == 200, r.text
    return r.json()["draft"]


# ─── draft CRUD ──────────────────────────────────────────────────────────────

def test_create_draft_is_local_only_and_stores_cents(client, gp):
    d = _mk_draft(client)
    assert d["id"] > 0
    assert d["price_cents"] == 999          # money is cents everywhere
    assert d["price"] == 9.99
    assert d["pushed"] is False
    assert d["wp_id"] in (None, 0)
    assert d["slug"] == "smoke-test"
    assert d["status"] == "draft"


def test_create_draft_requires_a_project_path(client):
    r = client.post("/api/games/publish/draft", json={"title": "No path"})
    assert r.status_code == 400
    assert "path" in r.json()["error"].lower()


def test_draft_list_get_patch_delete_roundtrip(client):
    d = _mk_draft(client, title="CRUD Game")
    lid = d["id"]

    listed = client.get("/api/games/publish/drafts").json()
    assert any(x["id"] == lid for x in listed["drafts"])

    got = client.get(f"/api/games/publish/draft/{lid}")
    assert got.status_code == 200
    assert got.json()["draft"]["title"] == "CRUD Game"

    patched = client.patch(f"/api/games/publish/draft/{lid}",
                           json={"title": "CRUD Game II", "price": 14.50,
                                 "short_desc": "Now with sequels."})
    assert patched.status_code == 200
    p = patched.json()["draft"]
    assert p["title"] == "CRUD Game II"
    assert p["price_cents"] == 1450
    assert p["short_desc"] == "Now with sequels."

    assert client.delete(f"/api/games/publish/draft/{lid}").status_code == 200
    assert client.get(f"/api/games/publish/draft/{lid}").status_code == 404


def test_patch_rejects_a_bad_price(client):
    d = _mk_draft(client, title="Price Guard")
    r = client.patch(f"/api/games/publish/draft/{d['id']}", json={"price": "free-ish"})
    assert r.status_code == 400


def test_drafts_scope_to_one_project(client):
    _mk_draft(client, project_path="~/games/Alpha", title="Alpha One")
    _mk_draft(client, project_path="~/games/Beta", title="Beta One")
    r = client.get("/api/games/publish/drafts", params={"project": "~/games/Alpha"}).json()
    assert r["count"] >= 1
    assert all(x["project_path"] == "~/games/Alpha" for x in r["drafts"])


# ─── graceful degradation ────────────────────────────────────────────────────

def test_status_explains_missing_woo_credentials(client, gp, monkeypatch):
    monkeypatch.setattr(gp, "_woo_state", lambda: {
        "products_configured": False, "media_configured": False, "error": "not connected"})
    d = client.get("/api/games/publish/status").json()
    assert d["products_configured"] is False
    assert d["draft_only"] is True
    assert "draft" in d["note"].lower()


def test_push_without_woo_creds_explains_instead_of_erroring(client, gp, monkeypatch, no_gate):
    d = _mk_draft(client, title="Unconnected")
    monkeypatch.setattr(gp, "_woo_state", lambda: {
        "products_configured": False, "media_configured": False,
        "error": "WooCommerce isn't connected yet"})
    r = client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True})
    assert r.status_code == 400                       # explained, not a 500
    assert "connect" in r.json()["error"].lower()


def test_screenshots_with_node_down_is_an_empty_list_not_an_error(client, gp, monkeypatch):
    import routers.games as g
    monkeypatch.setattr(g, "_ssh", lambda cmd, timeout=30: (-1, "ssh: connect timed out"))
    r = client.get("/api/games/publish/screenshots", params={"path": "~/games/Smoke_Test"})
    assert r.status_code == 200
    d = r.json()
    assert d["shots"] == []
    assert d["reachable"] is False


def test_screenshots_finds_art_and_skips_engine_noise(client, gp, monkeypatch):
    import routers.games as g
    monkeypatch.setattr(g, "_ssh", lambda cmd, timeout=30: (0, "\n".join([
        "/home/u/games/G/Library/atlas.png|1200",          # engine cache → skipped
        "/home/u/games/G/Assets/ui_button.png|900",
        "/home/u/games/G/Screenshots/cover.png|40000",     # art hint → sorted first
    ])))
    d = client.get("/api/games/publish/screenshots",
                   params={"path": "~/games/G"}).json()
    names = [s["name"] for s in d["shots"]]
    assert "atlas.png" not in names                    # Library/ noise dropped
    assert names[0] == "cover.png"                     # likely_art floats to the top
    assert d["shots"][0]["likely_art"] is True


# ─── images ──────────────────────────────────────────────────────────────────

_PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


def test_upload_attaches_an_image_and_serves_it_back(client):
    d = _mk_draft(client, title="With Art")
    r = client.post(f"/api/games/publish/draft/{d['id']}/upload",
                    files={"file": ("shot.png", _PNG, "image/png")})
    assert r.status_code == 200, r.text
    draft = r.json()["draft"]
    assert len(draft["images"]) == 1
    img = draft["images"][0]
    assert img["kind"] == "upload"
    assert client.get(img["url"]).status_code == 200

    rm = client.delete(f"/api/games/publish/draft/{d['id']}/image/{img['file']}")
    assert rm.json()["draft"]["images"] == []


def test_upload_rejects_non_images(client):
    d = _mk_draft(client, title="Bad Upload")
    r = client.post(f"/api/games/publish/draft/{d['id']}/upload",
                    files={"file": ("game.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400


def test_screenshot_pull_copies_files_off_the_node(client, gp, monkeypatch):
    import base64
    import routers.games as g
    monkeypatch.setattr(g, "_ssh",
                        lambda cmd, timeout=30: (0, base64.b64encode(_PNG).decode()))
    d = _mk_draft(client, title="Pulled")
    r = client.post(f"/api/games/publish/draft/{d['id']}/screenshots",
                    json={"paths": ["/home/u/games/G/Screenshots/cover.png"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"]
    assert body["draft"]["images"][0]["kind"] == "screenshot"


def test_push_uploads_images_to_wp_media_and_attaches_them(client, gp, monkeypatch, no_gate):
    d = _mk_draft(client, title="Art Push")
    client.post(f"/api/games/publish/draft/{d['id']}/upload",
                files={"file": ("cover.png", _PNG, "image/png")})

    uploads = []

    class FakeMcp:
        def upload_media_base64(self, filename, data, title="", alt_text=""):
            uploads.append(filename)
            return {"id": 55, "source_url": f"https://shop.example/wp/{filename}"}

    woo = FakeWoo()
    monkeypatch.setattr(gp, "_wc", lambda: woo)
    monkeypatch.setattr(gp, "_mcp", lambda: FakeMcp())
    monkeypatch.setattr(gp, "_woo_state", lambda: {
        "products_configured": True, "media_configured": True, "error": ""})

    r = client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert uploads == ["cover.png"]
    payload = woo.calls[0][2]
    assert payload["images"] == [{"src": "https://shop.example/wp/cover.png"}]


def test_push_survives_a_broken_media_library(client, gp, monkeypatch, no_gate):
    """No WP media creds must not block the product — it just goes up without art."""
    d = _mk_draft(client, title="No Media")
    client.post(f"/api/games/publish/draft/{d['id']}/upload",
                files={"file": ("cover.png", _PNG, "image/png")})
    woo = FakeWoo()
    monkeypatch.setattr(gp, "_wc", lambda: woo)
    monkeypatch.setattr(gp, "_mcp", lambda: (_ for _ in ()).throw(RuntimeError("no mcp creds")))
    monkeypatch.setattr(gp, "_woo_state", lambda: {
        "products_configured": True, "media_configured": False, "error": ""})
    r = client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True})
    assert r.status_code == 200
    assert r.json()["image_errors"]
    assert woo.calls[0][2]["status"] == "draft"


# ─── the push itself ─────────────────────────────────────────────────────────

def _wire_woo(gp, monkeypatch, woo):
    monkeypatch.setattr(gp, "_wc", lambda: woo)
    monkeypatch.setattr(gp, "_mcp", lambda: (_ for _ in ()).throw(RuntimeError("no media")))
    monkeypatch.setattr(gp, "_woo_state", lambda: {
        "products_configured": True, "media_configured": False, "error": ""})


def test_push_creates_a_woo_draft_never_publish(client, gp, monkeypatch, no_gate):
    woo = FakeWoo(next_id=101)
    _wire_woo(gp, monkeypatch, woo)
    d = _mk_draft(client, title="Draft Only")

    r = client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wp_id"] == 101
    assert body["wp_status"] == "draft"
    assert body["admin_url"] == "" or "post.php" in body["admin_url"]

    method, path, payload = woo.calls[0]
    assert (method, path) == ("POST", "/products")
    assert payload["status"] == "draft"
    assert payload["status"] != "publish"
    assert "publish" not in json.dumps(payload)      # nothing anywhere says publish
    assert payload["catalog_visibility"] == "hidden"
    assert payload["regular_price"] == "9.99"        # cents → Woo's dollar string


def test_repush_updates_the_same_product_instead_of_duplicating(client, gp, monkeypatch, no_gate):
    woo = FakeWoo(next_id=202)
    _wire_woo(gp, monkeypatch, woo)
    d = _mk_draft(client, title="Idempotent")

    first = client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True}).json()
    assert first["action"] == "created"

    client.patch(f"/api/games/publish/draft/{d['id']}", json={"title": "Idempotent v2"})
    second = client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True}).json()

    assert second["action"] == "updated"
    assert second["wp_id"] == first["wp_id"]         # same product, not a duplicate
    assert len([c for c in woo.calls if c[0] == "POST" and c[1] == "/products"]) == 1
    put = [c for c in woo.calls if c[0] == "PUT"][0]
    assert put[1] == f"/products/{first['wp_id']}"
    assert put[2]["status"] == "draft"               # updates stay drafts too
    assert put[2]["name"] == "Idempotent v2"


def test_push_gate_requires_confirmation_and_is_toggleable(client, gp, monkeypatch):
    woo = FakeWoo(next_id=303)
    _wire_woo(gp, monkeypatch, woo)
    d = _mk_draft(client, title="Gated")

    client.post("/api/games/publish/gate", json={"on": True})
    blocked = client.post(f"/api/games/publish/{d['id']}/push", json={})
    assert blocked.status_code == 400
    assert blocked.json()["needs_confirm"] is True
    assert not woo.calls                              # nothing left the box

    assert client.post(f"/api/games/publish/{d['id']}/push",
                       json={"confirm": True}).status_code == 200

    off = client.post("/api/games/publish/gate", json={"on": False}).json()
    assert off["gate"] is False
    assert client.get("/api/games/publish/drafts").json()["gate"] is False
    client.post("/api/games/publish/gate", json={"on": True})


def test_push_payload_never_leaks_where_the_project_lives(client, gp, monkeypatch, no_gate):
    woo = FakeWoo(next_id=404)
    _wire_woo(gp, monkeypatch, woo)
    d = _mk_draft(
        client, project_path="~/games/Secret_Project", title="Leaky",
        long_desc="<p>Built in /home/someone/games/Secret_Project on 127.0.0.1.</p>")
    client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True})
    sent = json.dumps(woo.calls[0][2])
    assert "/home/someone" not in sent
    assert "127.0.0.1" not in sent
    assert "~/games" not in sent


def test_push_404_from_woo_recreates_the_product(client, gp, monkeypatch, no_gate):
    """A product deleted by hand in WP admin must not wedge the listing forever."""
    woo = FakeWoo(next_id=505)
    _wire_woo(gp, monkeypatch, woo)
    d = _mk_draft(client, title="Deleted Upstream")
    first = client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True}).json()

    real_req = woo._req

    def flaky(method, path, *, params=None, json=None):
        if method == "PUT":
            raise RuntimeError("HTTP 404 product not found")
        return real_req(method, path, params=params, json=json)

    monkeypatch.setattr(woo, "_req", flaky)
    again = client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True}).json()
    assert again["action"] == "created"
    assert again["wp_id"] != first["wp_id"]
    assert again["wp_status"] == "draft"


def test_deleting_a_local_draft_never_touches_the_shop(client, gp, monkeypatch, no_gate):
    woo = FakeWoo(next_id=606)
    _wire_woo(gp, monkeypatch, woo)
    d = _mk_draft(client, title="Local Delete")
    client.post(f"/api/games/publish/{d['id']}/push", json={"confirm": True})
    before = len(woo.calls)
    r = client.delete(f"/api/games/publish/draft/{d['id']}")
    assert r.status_code == 200
    assert len(woo.calls) == before               # no DELETE reached WooCommerce


# ─── LLM description helper rides the queue ──────────────────────────────────

def test_generated_description_goes_through_the_orchestrator_queue(client, gp, monkeypatch):
    """The LLM call must be SUBMITTED to orch, never dialled directly."""
    from orchestrator import orch

    submitted = {}

    def fake_submit(func, desc="", retry_meta=None, model=None, priority=1,
                    task=None, source=None):
        submitted["desc"] = desc
        submitted["source"] = source
        submitted["func"] = func
        return 9911

    monkeypatch.setattr(orch, "submit_llm", fake_submit)
    monkeypatch.setattr(gp.orch, "submit_llm", fake_submit)

    d = _mk_draft(client, title="Copy Me")
    r = client.post(f"/api/games/publish/draft/{d['id']}/describe")
    assert r.status_code == 200
    assert r.json()["task_id"] == 9911
    assert submitted["source"] == "games"
    assert "Copy Me" in submitted["desc"]

    # …and the work the queue would run is the LLM call itself.
    calls = []
    import deps
    monkeypatch.setattr(deps, "_call_lmstudio",
                        lambda system, user, max_tokens=0, **kw: calls.append(user)
                        or '{"short":"Punchy.","long":"<p>Words.</p>","tags":"indie"}')
    submitted["func"]()
    assert calls and "TITLE: Copy Me" in calls[0]

    got = client.get("/api/games/publish/describe/9911").json()
    assert got["status"] == "done"
    assert got["short"] == "Punchy."
    assert got["tags"] == "indie"

    # Suggestions are NEVER written to the draft — the owner edits and saves them.
    still = client.get(f"/api/games/publish/draft/{d['id']}").json()["draft"]
    assert still["short_desc"] == "A tiny game."


def test_generated_description_is_scrubbed_of_infrastructure(client, gp, monkeypatch):
    from orchestrator import orch
    holder = {}
    monkeypatch.setattr(gp.orch, "submit_llm",
                        lambda func, **kw: (holder.setdefault("f", func), 9912)[1])
    d = _mk_draft(client, title="Scrub Me")
    client.post(f"/api/games/publish/draft/{d['id']}/describe")
    import deps
    monkeypatch.setattr(
        deps, "_call_lmstudio",
        lambda system, user, max_tokens=0, **kw:
            '{"short":"Made at /home/dev/games/Scrub.","long":"<p>Runs on 10.0.0.5.</p>"}')
    holder["f"]()
    got = client.get("/api/games/publish/describe/9912").json()
    assert "/home/dev" not in got["short"]
    assert "10.0.0.5" not in got["long"]


def test_cover_generation_uses_the_studio_pipeline(client, gp, monkeypatch):
    """Cover art rides services.run_generation → orch.image_acquire (the shared GPU
    queue); nothing here talks to ComfyUI directly."""
    import services
    ran = []
    monkeypatch.setattr(services, "run_generation", lambda gid: ran.append(gid))
    d = _mk_draft(client, title="Cover Me")
    r = client.post(f"/api/games/publish/draft/{d['id']}/cover", json={})
    assert r.status_code == 200, r.text
    gid = r.json()["generation_id"]
    import db
    conn = db.get_conn()
    row = conn.execute("SELECT prompt,source FROM generations WHERE id=?", (gid,)).fetchone()
    conn.close()
    assert row["source"] == "games"
    assert "Cover Me" in row["prompt"]

    st = client.get(f"/api/games/publish/draft/{d['id']}/cover/{gid}").json()
    assert st["status"] in ("pending", "generating", "queued", "done", "unknown", "failed")

    # Tidy up: an un-run generations row would otherwise read as "GPU busy" to the
    # miner gate (/api/gpu/guard/state) for the rest of the session.
    conn = db.get_conn()
    conn.execute("DELETE FROM generations WHERE id=?", (gid,))
    conn.commit()
    conn.close()
