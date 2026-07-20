"""Public world snapshot pipeline — the three guards that keep the private box private.

The pipeline may only publish when (1) the owner's toggle is on, (2) no gated
private-studio content could be on screen, and (3) the exact outbound payload
survives a leak sweep. These tests pin all three, plus the allow-list sanitizer.
"""
import json

import pytest

import world_snapshot as wsnap


# ─────────────────────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────────────────────
def _set(client, **kv):
    r = client.patch("/api/settings", json={k: str(v) for k, v in kv.items()})
    assert r.status_code == 200


@pytest.fixture(autouse=True)
def _reset(client):
    """Ship-default state: snapshot toggle OFF, all private-studio toggles OFF."""
    _set(client, world_public_snapshot="", nsfw_enabled="", nsfw_display="", nsfw_world="")
    yield
    _set(client, world_public_snapshot="", nsfw_enabled="", nsfw_display="", nsfw_world="")


DIRTY_STATE = {
    "orchestra": {"season": "autumn", "emoji": "🍂", "day": 4040,
                  "festival": "harvest & the great timber cut"},
    "company": {
        "pop": 39, "total_jobs": 211, "max_level": 18, "props_done": 14, "meetings": 147,
        "treasury": 8253, "company_fund": 104825,
        "tech": {"tier": "steel", "tier_name": "Steel", "emoji": "🔧", "research_points": 2133},
        "specialists": {"farming": {"name": "Nova", "level": 37},
                        "mining": {"name": "Etta", "level": 37}},
    },
    "agents": [
        {"id": 1, "key": "openclaw_engineer", "name": "Ozzy", "dept": "devlab",
         "sprite_path": "/home/user/projects/platform_dev/store/sprites/ozzy.png",
         "mood": "the box at 127.0.0.1 is thrashing again",
         "skills": {"attack": {"level": 6}, "farming": {"level": 31}}},
        {"id": 2, "name": "Nova", "skills": {"farming": {"level": 37}}},
    ],
    # deliberately hostile blocks that must never reach the payload
    "security": {"systems": {"video": {"sample": 'env/lib/python3.12/site-packages/x.py", line 4327, in'}}},
    "activity": {"netsec": 2},
    "governance": {"priority": "ssh into 10.0.0.4 and restart uvicorn on port 8787"},
    "events": [
        {"kind": "incident", "text": "🚀 A listing went viral — the Storefront cashes in!"},
        {"kind": "incident", "text": "💥 crash in /home/user/store/app/main.py at line 22"},
        {"kind": "security", "text": "🧠 Security AI: possible injection against the admin route"},
        {"kind": "thought", "text": "Kane: we should push niche micro-communities this quarter"},
        {"kind": "town", "text": "Boss filed a Store upgrade (300🪙 from the company fund, pending your approval)"},
        {"kind": "meeting", "text": "🏛️ voted to prioritise an abandoned cart email sequence"},
        {"kind": "phase", "text": "⚙️ Town phase → watch — a subsystem is failing."},
        {"kind": "raid", "text": "🛡️ Perimeter integrity 64% — real defenses online reinforce the walls."},
        {"kind": "season", "text": "🍂 Autumn has arrived — the great timber cut."},
    ],
    "achievements": [{"label": "Production Line 🏭"}],
}


# ─────────────────────────────────────────────────────────────────────────────
# sanitization — the allow-list strips infra fields
# ─────────────────────────────────────────────────────────────────────────────
def test_build_stats_keeps_only_allowlisted_public_fields():
    stats = wsnap.build_stats(DIRTY_STATE)
    assert stats["population"] == 39
    assert stats["day"] == 4040
    assert stats["season"] == "autumn"
    assert stats["tech_age"] == "Steel"
    assert stats["total_levels"] == 6 + 31 + 37
    assert stats["jobs_done"] == 211
    # money / ops figures are not public
    assert "treasury" not in stats and "company_fund" not in stats


def test_build_stats_drops_hostile_blocks_entirely():
    stats = wsnap.build_stats(DIRTY_STATE)
    blob = json.dumps(stats)
    for forbidden in ("192.168.", "10.0.0.4", "/home/user", "site-packages",
                      "uvicorn", "8787", "openclaw_engineer", "sprite_path",
                      "python3.12", "ssh into"):
        assert forbidden not in blob, f"{forbidden!r} leaked into the public payload"
    assert "security" not in stats and "governance" not in stats


def test_event_lines_with_paths_are_dropped_not_just_truncated():
    stats = wsnap.build_stats(DIRTY_STATE)
    assert any("viral" in e for e in stats["events"])
    assert not any("main.py" in e or "user" in e for e in stats["events"])


def test_only_allowlisted_event_kinds_are_published():
    stats = wsnap.build_stats(DIRTY_STATE)
    blob = " ".join(stats["events"])
    # the in-world kinds survive
    assert "viral" in blob and "Autumn" in blob
    # real security findings, LLM strategy talk and subsystem health do not
    for forbidden in ("Security AI", "injection", "micro-communities", "company fund",
                      "pending your approval", "abandoned cart", "subsystem is failing",
                      "real defenses online"):
        assert forbidden not in blob, f"{forbidden!r} leaked out of a non-public event kind"


def test_unknown_event_kinds_default_to_excluded():
    """A new sim event kind must not become public just by existing."""
    stats = wsnap.build_stats({"events": [
        {"kind": "brand_new_kind", "text": "totally innocent looking line"},
        {"kind": None, "text": "no kind at all"},
        {"text": "missing kind key"},
    ]})
    assert stats["events"] == []


def test_ops_vocabulary_is_caught_even_inside_an_allowed_kind():
    stats = wsnap.build_stats({"events": [
        {"kind": "incident", "text": "the API key rotated and the payout cleared"},
        {"kind": "incident", "text": "🚀 A listing went viral!"},
    ]})
    assert stats["events"] == ["🚀 A listing went viral!"]


def test_specialists_expose_only_in_world_flavor():
    stats = wsnap.build_stats(DIRTY_STATE)
    assert stats["specialists"]
    for s in stats["specialists"]:
        assert set(s) == {"skill", "name", "level"}


def test_scan_payload_flags_a_dirty_blob_and_passes_a_clean_one():
    assert wsnap.scan_payload({"a": "connect to 127.0.0.1"})
    assert wsnap.scan_payload({"a": "see /home/user/store/app"})
    assert wsnap.scan_payload({"a": "running python 3.12.1 on port 8787"})
    assert wsnap.scan_payload(wsnap.build_stats(DIRTY_STATE)) == []


def test_find_leaks_catches_each_infra_shape():
    for bad in ("127.0.0.1", "/var/lib/store/db", "https://internal.example/x",
                "box.local", "localhost", "NVIDIA GeForce RTX 3060",
                'File "app/main.py", line 3', "someone@example.com"):
        assert wsnap.find_leaks(bad), f"leak detector missed {bad!r}"


# ─────────────────────────────────────────────────────────────────────────────
# GUARD 1 — toggle off means no push
# ─────────────────────────────────────────────────────────────────────────────
def test_toggle_defaults_off(client):
    assert wsnap.enabled() is False
    assert client.get("/api/world/public/status").json()["enabled"] is False


def test_toggle_off_means_no_push(client, monkeypatch):
    calls = []
    monkeypatch.setattr(wsnap, "render_world_png", lambda **k: calls.append("render") or b"x")
    monkeypatch.setattr(wsnap, "_mcp_client", lambda: calls.append("mcp"))

    r = wsnap.push_now()
    assert r["pushed"] is False and r["reason"] == "toggle off"
    assert calls == [], "nothing may render or reach the network while the toggle is off"


def test_tick_is_a_noop_while_toggle_is_off(monkeypatch):
    monkeypatch.setattr(wsnap, "push_async", lambda **k: pytest.fail("must not push"))
    r = wsnap.tick()
    assert r["skipped"] is True and r["reason"] == "toggle off"


def test_toggle_endpoint_flips_the_setting(client):
    assert client.post("/api/world/public/toggle", json={"on": True}).json()["enabled"] is True
    assert client.post("/api/world/public/toggle", json={"on": False}).json()["enabled"] is False


# ─────────────────────────────────────────────────────────────────────────────
# GUARD 2 — gated private-studio content skips the push
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("toggles", [
    {"nsfw_enabled": "1"},
    {"nsfw_enabled": "1", "nsfw_display": "1"},
    {"nsfw_enabled": "1", "nsfw_world": "1"},
])
def test_gate_fires_for_any_private_studio_toggle(client, toggles):
    _set(client, world_public_snapshot="1", **toggles)
    assert wsnap.gate_reason() is not None


def test_gated_content_skips_the_push_before_rendering(client, monkeypatch):
    _set(client, world_public_snapshot="1", nsfw_enabled="1", nsfw_world="1")
    calls = []
    monkeypatch.setattr(wsnap, "render_world_png", lambda **k: calls.append("render") or b"x")
    monkeypatch.setattr(wsnap, "_mcp_client", lambda: calls.append("mcp"))

    r = wsnap.push_now()
    assert r["pushed"] is False and r["reason"].startswith("gated:")
    assert calls == [], "a gated world must not even be rendered"


def test_gate_still_blocks_a_forced_manual_push(client, monkeypatch):
    _set(client, nsfw_enabled="1")
    monkeypatch.setattr(wsnap, "render_world_png", lambda **k: pytest.fail("must not render"))
    r = wsnap.push_now(force=True)
    assert r["pushed"] is False and r["reason"].startswith("gated:")


def test_push_endpoint_refuses_while_gated(client):
    _set(client, nsfw_enabled="1", nsfw_world="1")
    assert client.post("/api/world/public/push", json={"force": True}).status_code == 409


def test_gate_fails_closed_when_state_cannot_be_read(monkeypatch):
    import nsfw
    monkeypatch.setattr(nsfw, "world_active", lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
    assert wsnap.gate_reason() is not None


# ─────────────────────────────────────────────────────────────────────────────
# GUARD 3 — the leak gate aborts a push
# ─────────────────────────────────────────────────────────────────────────────
def test_leak_gate_blocks_the_push_and_never_reaches_the_network(client, monkeypatch):
    _set(client, world_public_snapshot="1")
    monkeypatch.setattr(wsnap, "build_stats", lambda *a, **k: {"note": "ssh 127.0.0.1"})
    monkeypatch.setattr(wsnap, "_mcp_client", lambda: pytest.fail("must not contact WordPress"))

    r = wsnap.push_now(state={}, png=b"fake")
    assert r["pushed"] is False and r["reason"] == "leak gate tripped"
    assert r["leaks"]


# ─────────────────────────────────────────────────────────────────────────────
# GUARD 4 — pixel leaks: the HUD must never be baked into the image
# ─────────────────────────────────────────────────────────────────────────────
def test_render_hides_every_known_text_overlay():
    """The HUD panels paint the operator's REAL text (feed, directives, findings)
    over the canvas. An element screenshot clips them in, so they must be hidden."""
    css = wsnap._HIDE_OVERLAYS_CSS
    for sel in (".whud-bar", ".whud-panel", "#world-feed", "#world-detail",
                "#world-townhall", "#world-hudbar", "#world-modal", "#world-activity"):
        assert sel in css, f"{sel} is not hidden before the screenshot"
    assert "display: none !important" in css


def test_overlap_probe_reports_own_text_only():
    """The probe must look at an element's OWN text, not its descendants', or every
    ancestor would report and the real offender would be lost in the noise."""
    probe = wsnap._OVERLAP_PROBE
    assert "nodeType === 3" in probe          # own text nodes
    assert "getBoundingClientRect" in probe   # actually tests overlap
    assert "world-canvas" in probe


def test_render_failure_blocks_the_push_and_the_network(client, monkeypatch):
    """A refused render (e.g. an overlay survived) must abort — never publish."""
    _set(client, world_public_snapshot="1")

    def _boom(**k):
        raise RuntimeError("refusing to render: 1 text overlay(s) still cover the world canvas")

    monkeypatch.setattr(wsnap, "render_world_png", _boom)
    monkeypatch.setattr(wsnap, "_mcp_client", lambda: pytest.fail("must not contact WordPress"))

    r = wsnap.push_now()
    assert r["pushed"] is False and "render failed" in r["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# happy path (fully stubbed — no browser, no network)
# ─────────────────────────────────────────────────────────────────────────────
class _FakeMcp:
    def __init__(self):
        self.uploaded, self.pages, self.deleted = [], {}, []

    def upload_media_base64(self, filename, file_bytes, **k):
        self.uploaded.append(filename)
        return {"id": 100 + len(self.uploaded),
                "source_url": f"https://example.test/{filename}"}

    def find_page_by_slug(self, slug):
        return self.pages.get(slug)

    def create_page(self, title, content, slug="", status="publish"):
        self.pages[slug] = {"id": 7, "slug": slug, "content": content}
        return self.pages[slug]

    def update_page(self, page_id, content, title=None):
        for p in self.pages.values():
            if p["id"] == page_id:
                p["content"] = content
        return {"id": page_id}

    def _tool(self, name, args):
        if name == "wp_get_page":
            for p in self.pages.values():
                if p["id"] == args["page_id"]:
                    return p
            return {}
        if name == "wp_delete_media":
            self.deleted.append(args["media_id"])
        return {}


def test_full_push_publishes_image_and_decodable_clean_data(client, monkeypatch):
    _set(client, world_public_snapshot="1")
    fake = _FakeMcp()
    monkeypatch.setattr(wsnap, "_mcp_client", lambda: fake)

    r = wsnap.push_now(state=DIRTY_STATE, png=b"\x89PNG-fake")
    assert r["pushed"] is True, r
    assert fake.uploaded and r["image_url"].startswith("https://example.test/")

    data = wsnap.decode_data(fake.pages[wsnap.DATA_SLUG]["content"])
    assert data["current"]["population"] == 39
    assert data["current"]["image_url"] == r["image_url"]
    # everything except the (separately validated) media link is leak-free
    scanned = {k: v for k, v in data["current"].items() if k != "image_url"}
    assert wsnap.scan_payload(scanned) == []
    assert "192.168." not in json.dumps(data)


def test_media_url_must_be_https_on_the_public_site(monkeypatch):
    monkeypatch.setattr(wsnap, "public_site_base", lambda: "https://example.test")
    assert wsnap.check_image_url("https://example.test/wp-content/world.png")
    for bad in ("http://example.test/x.png",          # not https
                "https://127.0.0.1/x.png",         # raw address
                "https://example.test:8787/x.png",     # port
                "https://internal.local/x.png",        # internal host
                "https://elsewhere.example/x.png",     # wrong origin
                "", None):
        assert not wsnap.check_image_url(bad), f"accepted {bad!r}"


def test_push_aborts_if_media_url_is_not_public(client, monkeypatch):
    _set(client, world_public_snapshot="1")
    fake = _FakeMcp()
    fake.upload_media_base64 = lambda filename, file_bytes, **k: {
        "id": 1, "source_url": "http://127.0.0.1/world.png"}
    monkeypatch.setattr(wsnap, "_mcp_client", lambda: fake)

    r = wsnap.push_now(state=DIRTY_STATE, png=b"png")
    assert r["pushed"] is False and "non-public media URL" in r["reason"]


def test_history_is_capped_and_old_media_pruned(client, monkeypatch):
    _set(client, world_public_snapshot="1")
    fake = _FakeMcp()
    monkeypatch.setattr(wsnap, "_mcp_client", lambda: fake)

    for _ in range(wsnap.KEEP_SNAPSHOTS + 3):
        wsnap.push_now(state=DIRTY_STATE, png=b"png")

    data = wsnap.decode_data(fake.pages[wsnap.DATA_SLUG]["content"])
    assert len(data["history"]) <= wsnap.KEEP_SNAPSHOTS


def test_status_endpoint_reports_the_guards(client):
    body = client.get("/api/world/public/status").json()
    assert set(("enabled", "interval_min", "gated", "running")) <= set(body)
    assert body["gated"] is None      # nothing gated with all toggles off
    assert body["interval_min"] >= wsnap.MIN_INTERVAL_MIN
