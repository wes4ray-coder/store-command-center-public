"""API smoke — hit safe, no-parameter GET endpoints and assert none return a 5xx.

A 4xx (e.g. an integration not configured) is fine; a 500 means an unhandled server bug.
Endpoints that SSH to the node, shell out, or call slow external APIs are skipped to keep
the suite fast and deterministic (listed in SKIP_SUBSTRINGS).
"""
import pytest

# Skip GET routes that reach out to the GPU node (SSH), Docker, gh CLI, or slow 3rd-party APIs.
SKIP_SUBSTRINGS = (
    "/api/mcp", "{",                     # MCP transport + any parameterized route
    "/node", "/store-stats", "/etsy/status", "/etsy/connect",
    "/models", "/video-models", "/audio-models", "/gen-models",
    "/github", "/homelab", "/security/connections", "/system/gpu-status",
    "/system/update-status", "/system/logs", "/system/backups",
    "/world", "/llm/", "/mail",
    # These DRIVE the real headed Chrome (launch it, navigate to a live marketplace).
    # A smoke GET must never do that — /api/resell/browser/inspect used to open
    # facebook.com/marketplace on every test run.
    "/resell/browser",
)


def _safe_get_paths(app):
    # Discover via the OpenAPI schema — FastAPI keeps included routers as sub-routers,
    # so they aren't all flat in app.routes, but they ARE all in the schema.
    spec = app.openapi()
    paths = []
    for path, ops in spec.get("paths", {}).items():
        if "get" not in {m.lower() for m in ops}:
            continue
        if not path.startswith("/api/"):
            continue
        if any(s in path for s in SKIP_SUBSTRINGS):
            continue
        paths.append(path)
    return sorted(paths)


def test_discovered_safe_get_endpoints_no_5xx(client):
    import main
    paths = _safe_get_paths(main.app)
    assert paths, "no safe GET endpoints discovered — route wiring changed?"
    failures = []
    for p in paths:
        try:
            r = client.get(p)
        except Exception as e:  # a hang/exception is a failure too
            failures.append(f"{p} -> EXCEPTION {type(e).__name__}: {e}")
            continue
        if r.status_code >= 500:
            failures.append(f"{p} -> {r.status_code} {r.text[:120]}")
    assert not failures, "5xx / errors on GET endpoints:\n" + "\n".join(failures)


@pytest.mark.parametrize("path", [
    "/api/stats", "/api/queue", "/api/prompts", "/api/settings",
    "/api/proposals", "/api/designs", "/api/product-types",
])
def test_core_endpoints_ok(client, path):
    r = client.get(path)
    assert r.status_code < 500, f"{path} -> {r.status_code} {r.text[:160]}"
    assert r.headers.get("content-type", "").startswith("application/json")


def test_unauthenticated_api_is_rejected():
    """Sanity: a fresh client with no session must NOT reach /api (auth guard works)."""
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app, base_url="https://testserver") as anon:
        r = anon.get("/api/settings")
        assert r.status_code == 401, f"expected 401 for anon, got {r.status_code}"
