"""Prompts routes — view and edit every LLM system prompt from the Settings → Prompts tab."""
from fastapi import APIRouter, HTTPException
from deps import *
from prompts import CATEGORIES

router = APIRouter()


@router.get("/api/prompts")
def api_list_prompts():
    """All registered prompts with their current value, default, category, and whether overridden."""
    return {"prompts": list_prompts(), "categories": CATEGORIES}


@router.patch("/api/prompts/{key}")
def api_set_prompt(key: str, body: dict):
    """Override a prompt. Body: {"value": "..."}. Empty value resets to default."""
    value = (body or {}).get("value")
    if value is None:
        raise HTTPException(400, "value required")
    try:
        if str(value).strip():
            set_prompt(key, str(value))
        else:
            reset_prompt(key)
    except KeyError:
        raise HTTPException(404, f"unknown prompt: {key}")
    return {"ok": True, "value": get_prompt(key)}


@router.post("/api/prompts/{key}/reset")
def api_reset_prompt(key: str):
    """Drop the override and fall back to the built-in default."""
    try:
        reset_prompt(key)
        return {"ok": True, "value": get_prompt(key)}
    except KeyError:
        raise HTTPException(404, f"unknown prompt: {key}")


@router.post("/api/prompts/{key}/test")
def api_test_prompt(key: str, body: dict):
    """Run the prompt's CURRENT value as the system prompt against a sample user input,
    so you can preview an edit before saving. Body: {"input": "..."}. Returns {task_id};
    poll /api/task/{id} → {output}. Uses the orchestrator so it respects the single-VRAM
    LLM queue like every other call."""
    body = body or {}
    sysp = (body.get("system") or "").strip()
    if not sysp:
        try:
            sysp = get_prompt(key)
        except KeyError:
            raise HTTPException(404, f"unknown prompt: {key}")
    inp = body.get("input", "").strip() or "Give me a short example."

    def _work():
        return {"output": _call_lmstudio(sysp, inp, max_tokens=500)}

    tid = orch.submit_llm(_work, desc=f"Test prompt: {key}", priority=0, task=key)   # user waiting
    return {"task_id": tid}
