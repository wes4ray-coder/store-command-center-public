"""AI Assistant agent: tool-schema generation, danger classification, the JSON
tool-call parser, approval gating (+ per-category toggles), and the full loop
(with a scripted fake model — no LM Studio needed)."""
import json

import pytest


# ─── tool catalog generation from the route table ────────────────────────────
def test_catalog_builds_from_route_table(client):
    import assistant_tools
    cat = assistant_tools.build_catalog()
    assert len(cat) > 100, "expected the full /api surface as tools"
    e = next(x for x in cat if x["path"] == "/api/queue" and x["method"] == "GET")
    assert e["name"]
    # a POST endpoint carries its body schema
    gen = next(x for x in cat if x["path"] == "/api/generate" and x["method"] == "POST")
    assert "prompt" in gen["body"]


def test_catalog_search(client):
    import assistant_tools
    hits = assistant_tools.search_catalog("queue")
    assert any(h["path"] == "/api/queue" for h in hits)
    assert assistant_tools.search_catalog("") == []


def test_curated_tools_exist_in_route_table(client):
    """Every curated tool must point at a real route (guards against route renames)."""
    import assistant_tools
    routes = {f"{e['method']} {e['path']}" for e in assistant_tools.build_catalog()}
    for t in assistant_tools.CURATED:
        assert f"{t['method']} {t['path']}" in routes, f"curated tool {t['name']} → missing route"


# ─── danger classification ───────────────────────────────────────────────────
@pytest.mark.parametrize("method,path,cat", [
    ("GET", "/api/money/anything", "read"),
    ("DELETE", "/api/library/links/3", "delete"),
    ("POST", "/api/queue/clear", "delete"),
    ("POST", "/api/jelly/tip", "money"),
    ("POST", "/api/money/missions/run", "money"),
    ("POST", "/api/security/scan", "security"),
    ("POST", "/api/world/ops/prayers/1/approve", "world"),
    ("POST", "/api/models3d/5/publish", "publish"),
    ("POST", "/api/settings", "settings"),
    ("POST", "/api/github/jobs", "swarm"),
    ("POST", "/api/generate", "studio"),
    ("POST", "/api/videos/generate", "studio"),
    ("POST", "/api/tasks", "other"),
])
def test_classify_call(method, path, cat):
    import assistant_tools
    assert assistant_tools.classify_call(method, path) == cat


# ─── tool-call parsing (local-model robustness) ──────────────────────────────
def test_parse_fenced_json():
    import assistant_tools
    out = assistant_tools.parse_tool_call('```json\n{"tool": "queue_status", "args": {}}\n```')
    assert out == {"tool": "queue_status", "args": {}}


def test_parse_json_with_prose():
    import assistant_tools
    out = assistant_tools.parse_tool_call(
        'Let me check.\n{"tool":"api_call","args":{"method":"GET","path":"/api/queue"}}\nDone.')
    assert out["tool"] == "api_call" and out["args"]["path"] == "/api/queue"


def test_parse_openai_style_and_string_args():
    import assistant_tools
    out = assistant_tools.parse_tool_call('{"name": "library_search", "arguments": {"q": "foo"}}')
    assert out == {"tool": "library_search", "args": {"q": "foo"}}
    out = assistant_tools.parse_tool_call('{"tool": "graph_query", "args": "{\\"q\\": \\"x\\"}"}')
    assert out == {"tool": "graph_query", "args": {"q": "x"}}


def test_parse_plain_text_is_final_answer():
    import assistant_tools
    assert assistant_tools.parse_tool_call("The queue is empty. All done!") is None
    assert assistant_tools.parse_tool_call("") is None
    # JSON that isn't a tool call is not treated as one
    assert assistant_tools.parse_tool_call('{"answer": 42}') is None


# ─── approval gate + per-category toggles ────────────────────────────────────
def test_auto_approve_defaults_and_toggle(client):
    import assistant_tools
    assert assistant_tools.auto_approved("read") is True
    assert assistant_tools.auto_approved("studio") is True
    assert assistant_tools.auto_approved("money") is False
    assert assistant_tools.auto_approved("delete") is False
    # every gate ships with a user toggle:
    r = client.post("/api/agent/settings", json={"toggles": {"money": True}})
    assert r.status_code == 200
    assert assistant_tools.auto_approved("money") is True
    client.post("/api/agent/settings", json={"toggles": {"money": False}})
    assert assistant_tools.auto_approved("money") is False
    # settings endpoint reports categories with live state
    d = client.get("/api/agent/settings").json()
    cats = {c["key"]: c for c in d["categories"]}
    assert cats["read"]["locked"] and cats["money"]["auto"] is False


# ─── skills ──────────────────────────────────────────────────────────────────
def test_skills_seeded_and_crud(client):
    d = client.get("/api/agent/skills").json()
    names = [s["name"] for s in d["skills"]]
    assert "Status report" in names and len(d["skills"]) >= 3
    r = client.post("/api/agent/skills", json={"name": "T", "description": "d", "prompt": "say hi"})
    sid = r.json()["id"]
    assert r.status_code == 200 and sid
    r = client.post("/api/agent/skills", json={"id": sid, "name": "T2", "prompt": "say hi again"})
    assert r.status_code == 200
    d = client.get("/api/agent/skills").json()
    assert any(s["id"] == sid and s["name"] == "T2" for s in d["skills"])
    assert client.delete(f"/api/agent/skills/{sid}").status_code == 200


# ─── the full agent loop, with a scripted model ──────────────────────────────
def _script_model(monkeypatch, outputs):
    """Replace the LM Studio call with a scripted sequence, and make loop
    submission synchronous so no orchestrator/model is involved."""
    from routers import agent as agent_mod
    from routers.agent import chat as agent_chat   # _chat_raw/_submit_run/_run_loop live here now
    seq = list(outputs)
    monkeypatch.setattr(agent_chat, "_chat_raw", lambda msgs, max_tokens=1400: seq.pop(0))
    monkeypatch.setattr(agent_chat, "_submit_run", lambda cid: agent_chat._run_loop(cid))
    return agent_mod


def test_loop_harmless_tool_then_answer(client, monkeypatch):
    _script_model(monkeypatch, [
        '{"tool": "queue_status", "args": {}}',
        'The queue looks fine.',
    ])
    r = client.post("/api/agent/chat", json={"message": "how is the queue?"})
    assert r.status_code == 200
    cid = r.json()["conversation_id"]
    ev = client.get(f"/api/agent/events?conversation_id={cid}&after=0").json()
    kinds = [m["kind"] for m in ev["messages"]]
    assert ev["status"] == "idle"
    assert "tool_call" in kinds and "tool_result" in kinds
    tr = next(m for m in ev["messages"] if m["kind"] == "tool_result")
    assert tr["meta"]["status"] == 200          # /api/queue really executed in-process
    assert ev["messages"][-1]["kind"] == "assistant"
    assert "queue looks fine" in ev["messages"][-1]["content"]


def test_loop_dangerous_call_gates_then_deny_resumes(client, monkeypatch):
    _script_model(monkeypatch, [
        '{"tool": "api_call", "args": {"method": "POST", "path": "/api/jelly/tip", "body": {"to": "x", "amount": 5}}}',
        'Understood — I will not send the tip.',
    ])
    r = client.post("/api/agent/chat", json={"message": "tip 5 JLY to x"})
    cid = r.json()["conversation_id"]
    ev = client.get(f"/api/agent/events?conversation_id={cid}&after=0").json()
    assert ev["status"] == "awaiting_approval"
    ap = next(m for m in ev["messages"] if m["kind"] == "approval_request")
    assert ap["meta"]["category"] == "money"
    ap_id = ap["meta"]["approval_id"]
    # no tool executed yet
    assert not any(m["kind"] == "tool_result" for m in ev["messages"])
    # deny → denial recorded, loop resumes and finishes without executing
    r = client.post("/api/agent/approve", json={"approval_id": ap_id, "approve": False})
    assert r.status_code == 200
    ev = client.get(f"/api/agent/events?conversation_id={cid}&after=0").json()
    kinds = [m["kind"] for m in ev["messages"]]
    assert "approval_result" in kinds and "tool_result" not in kinds
    assert ev["status"] == "idle"
    assert "will not send" in ev["messages"][-1]["content"]
    # double-answering the same approval 404s
    assert client.post("/api/agent/approve", json={"approval_id": ap_id, "approve": True}).status_code == 404


def test_loop_approve_executes_and_remember_flips_toggle(client, monkeypatch):
    import assistant_tools
    _script_model(monkeypatch, [
        '{"tool": "api_call", "args": {"method": "POST", "path": "/api/world/ops/board", "body": {}}}',
        'Posted.',
        'Done.',
    ])
    r = client.post("/api/agent/chat", json={"message": "post to the world board"})
    cid = r.json()["conversation_id"]
    ev = client.get(f"/api/agent/events?conversation_id={cid}&after=0").json()
    ap = next(m for m in ev["messages"] if m["kind"] == "approval_request")
    assert ap["meta"]["category"] == "world"
    r = client.post("/api/agent/approve",
                    json={"approval_id": ap["meta"]["approval_id"], "approve": True, "remember": True})
    assert r.status_code == 200
    ev = client.get(f"/api/agent/events?conversation_id={cid}&after=0").json()
    assert any(m["kind"] == "tool_result" for m in ev["messages"])   # executed after approval
    assert assistant_tools.auto_approved("world") is True            # "always allow" toggle flipped
    client.post("/api/agent/settings", json={"toggles": {"world": False}})   # reset


def test_conversation_persistence_and_delete(client, monkeypatch):
    _script_model(monkeypatch, ['hello there'])
    cid = client.post("/api/agent/chat", json={"message": "hi"}).json()["conversation_id"]
    convs = client.get("/api/agent/conversations").json()["conversations"]
    assert any(c["id"] == cid for c in convs)
    d = client.get(f"/api/agent/conversations/{cid}").json()
    assert [m["kind"] for m in d["messages"]][:2] == ["user", "assistant"]
    assert client.delete(f"/api/agent/conversations/{cid}").status_code == 200
    assert client.get(f"/api/agent/conversations/{cid}").status_code == 404


def test_unknown_tool_becomes_tool_error_and_loop_continues(client, monkeypatch):
    _script_model(monkeypatch, [
        '{"tool": "not_a_tool", "args": {}}',
        'Sorry, I used a bad tool name.',
    ])
    cid = client.post("/api/agent/chat", json={"message": "x"}).json()["conversation_id"]
    ev = client.get(f"/api/agent/events?conversation_id={cid}&after=0").json()
    kinds = [m["kind"] for m in ev["messages"]]
    assert "tool_error" in kinds and ev["status"] == "idle"
    assert ev["messages"][-1]["kind"] == "assistant"
