"""Performance work: static Cache-Control, on-demand thumbnails, and the TTL cache."""
import io

import cache as _cache
from config import DATA_DIR


def _make_design(sub="pending", name="perftest.png", size=(1200, 1200)):
    """Write a real PNG into the temp data dir's designs/<sub>/ and return its name."""
    from PIL import Image
    d = DATA_DIR / "designs" / sub
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (123, 200, 88)).save(d / name)
    return name


# ── Cache-Control on static assets ───────────────────────────────────────────

def test_static_assets_send_cache_control(client):
    r = client.get("/static/js/app-core.js")   # app-main.js was split into app-core/nav/queue/studio
    assert r.status_code == 200
    assert "max-age" in r.headers.get("cache-control", ""), r.headers.get("cache-control")


# ── Thumbnails ───────────────────────────────────────────────────────────────

def test_thumbnail_generates_webp_and_is_cached(client):
    name = _make_design(size=(1500, 1000))
    r = client.get(f"/thumb/pending/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert "immutable" in r.headers.get("cache-control", "")
    # it's a real, smaller WebP whose longest edge is clamped to 400
    from PIL import Image
    im = Image.open(io.BytesIO(r.content))
    assert im.format == "WEBP"
    assert max(im.size) <= 400
    # cached to disk for next time
    assert (DATA_DIR / "designs" / "pending" / "thumbs" / "perftest.webp").exists()


def test_thumbnail_rejects_traversal_and_missing(client):
    assert client.get("/thumb/pending/../../store.db").status_code in (404, 400)
    assert client.get("/thumb/bogus/x.png").status_code == 404
    assert client.get("/thumb/pending/does-not-exist.png").status_code == 404


# ── TTL cache util ───────────────────────────────────────────────────────────

def test_ttl_cache_serves_within_ttl_and_invalidates():
    _cache.invalidate()
    calls = {"n": 0}

    def produce():
        calls["n"] += 1
        return calls["n"]

    assert _cache.cached("k", 60, produce) == 1
    assert _cache.cached("k", 60, produce) == 1   # cached — producer not called again
    assert calls["n"] == 1
    _cache.invalidate("k")
    assert _cache.cached("k", 60, produce) == 2   # re-produced after invalidate


def test_ttl_cache_prefix_invalidation():
    _cache.invalidate()
    _cache.cached("portal:wp-products:50", 60, lambda: "a")
    _cache.cached("portal:wp-products:10", 60, lambda: "b")
    _cache.cached("other:key", 60, lambda: "c")
    _cache.invalidate_prefix("portal:wp-products:")
    hits = {"n": 0}

    def rebuild():
        hits["n"] += 1
        return "new"

    assert _cache.cached("portal:wp-products:50", 60, rebuild) == "new"   # busted → rebuilt
    assert _cache.cached("other:key", 60, lambda: "z") == "c"             # untouched
    assert hits["n"] == 1
