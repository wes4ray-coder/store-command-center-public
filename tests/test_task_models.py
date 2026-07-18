"""Per-task LLM models + Oracle analyst management."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))


def test_for_task_blank_then_set_then_cleared(client):
    import model_registry as mr
    assert mr.for_task("image_research") == ""                    # unset = no override
    client.patch("/api/settings", json={"task_model_image_research": "qwen/qwen3.5-9b"})
    assert mr.for_task("image_research") == "qwen/qwen3.5-9b"
    client.patch("/api/settings", json={"task_model_image_research": ""})
    assert mr.for_task("image_research") == ""


def test_submit_llm_resolves_task_model(client):
    from deps import orch
    client.patch("/api/settings", json={"task_model_video_chain": "zai-org/glm-4.7-flash"})
    tid = orch.submit_llm(lambda: "ok", desc="task-model test", task="video_chain")
    # the model is resolved + recorded synchronously at submit time
    assert orch._tasks[tid]["model"] == "zai-org/glm-4.7-flash"
    # no override → model stays None (default behavior untouched)
    client.patch("/api/settings", json={"task_model_video_chain": ""})
    tid2 = orch.submit_llm(lambda: "ok", desc="task-model test 2", task="video_chain")
    assert orch._tasks[tid2]["model"] is None
    # explicit model always wins over the task setting
    client.patch("/api/settings", json={"task_model_video_chain": "qwen/qwen3.5-9b"})
    tid3 = orch.submit_llm(lambda: "ok", desc="task-model test 3",
                           model="explicit-model", task="video_chain")
    assert orch._tasks[tid3]["model"] == "explicit-model"
    client.patch("/api/settings", json={"task_model_video_chain": ""})


def test_oracle_agent_crud(client):
    r = client.post("/api/oracle/agents", json={"name": "TestSeer", "model": "qwen/qwen3.5-9b"})
    assert r.status_code == 200
    aid = r.json()["id"]
    # duplicate name blocked
    assert client.post("/api/oracle/agents", json={"name": "TestSeer", "model": "x"}).status_code == 400
    # change model
    assert client.post(f"/api/oracle/agents/{aid}", json={"model": "zai-org/glm-4.7-flash"}).status_code == 200
    agents = {a["id"]: a for a in client.get("/api/oracle/agents").json()["agents"]}
    assert agents[aid]["model"] == "zai-org/glm-4.7-flash" and agents[aid]["name"] == "TestSeer"
    # retire
    assert client.delete(f"/api/oracle/agents/{aid}").status_code == 200
    assert aid not in {a["id"] for a in client.get("/api/oracle/agents").json()["agents"]}
    assert client.delete(f"/api/oracle/agents/{aid}").status_code == 404
    # missing fields rejected
    assert client.post("/api/oracle/agents", json={"name": "", "model": ""}).status_code == 400
