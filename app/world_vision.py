"""
The Company — the world-builder's eyes.

A vision model inspects each generated sprite so the builder can judge its own work
(and remake/retry the ones that came out poorly). It is deliberately POLITE to the
shared GPU:

  * It NEVER dumps a model on the GPU. Every look goes through the orchestrator queue
    (world_defs.run_llm_job), same as every other LLM call.
  * It PREFERS whatever vision-capable model is already resident — no swap.
  * If only a CODE model is loaded (e.g. a coder is busy / next in the queue), it
    SKIPS the review this round rather than evicting that work — the build still
    completes ("blind"), it just isn't scored until a vision model is around.

Vision-capable models on this box (LM Studio):
  - qwen/qwen3.5-9b            (default; JIT-loads + accepts images)
  - google/gemma-4-12b(-qat)  (Gemma 4 is multimodal)
  - google/gemma-4-26b-a4b    (multimodal)
  - zai-org/glm-4.6v-flash    (GLM-4V; loads via CLI, HTTP-JIT can be flaky)
Code/text-only (never used for vision): *coder* models, ministral, glm-4.7-flash.
"""
import base64, json, re, logging
import httpx

from deps import LMSTUDIO_URL, _llm_headers
from world_defs import run_llm_job
import world_settings as ws
try:
    from orchestrator import _loaded_llms   # real resident-model detection (lms ps)
except Exception:
    _loaded_llms = lambda: []

log = logging.getLogger("store")

# Confirmed / likely vision-capable on this box. Keep conservative — a wrong guess
# just wastes one load, then we degrade to 'blind'. (Gemma-4 GGUFs here lack a
# reliable vision projector, so they're intentionally excluded.)
VISION_HINTS = ("qwen3.5", "qwen2.5-vl", "qwen3-vl", "glm-4.6v", "glm-4.7v",
                "gemma-4", "-vl", "llava", "moondream", "pixtral")   # Gemma 4 is multimodal
CODE_HINTS = ("coder",)

def _is_vision(mid): return any(h in mid.lower() for h in VISION_HINTS)
def _is_code(mid):   return any(h in mid.lower() for h in CODE_HINTS)


def _loaded_models():
    """Models ACTUALLY resident in VRAM (via `lms ps`), not the full download catalog
    that /v1/models returns."""
    try:
        return [m for m in _loaded_llms() if m]
    except Exception:
        return []


def pick_model():
    """(model_id, mode). LM Studio's HTTP API cannot hot-SWAP models (loading B while
    A is resident 400s), so we never force a conflicting load:
      * a resident vision model → use it ('resident', no swap)
      * nothing resident (slot empty) → load our VLM cleanly ('load')
      * a code model resident → leave it for its queued work ('code-busy')
      * any other model resident → skip rather than 400 on a swap ('busy-other')
    (With enhance_model unified on the VLM, the resident model is usually vision-
    capable, so 'resident' is the common path.)"""
    loaded = _loaded_models()
    for m in loaded:
        if _is_vision(m):
            return m, "resident"
    if any(_is_code(m) for m in loaded):
        return None, "code-busy"
    if not loaded:
        return ws.get_all().get("world_vision_model", "google/gemma-4-12b-qat"), "load"
    return None, "busy-other"


def available():
    return ws.b("world_vision_enabled") and pick_model()[0] is not None


def _call_vision(model, image_path, prompt, max_tokens=320):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}],
        "max_tokens": max_tokens, "temperature": 0.1,
    }
    r = httpx.post(f"{LMSTUDIO_URL}/chat/completions", json=body, headers=_llm_headers(), timeout=180)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def evaluate_asset(image_path, label, wait=180):
    """Score a sprite. Returns {score 1-10, issues, ok, blind}. Never raises; a
    failure/absence of a vision model just yields a permissive 'blind' result."""
    if not ws.b("world_vision_enabled"):
        return {"score": None, "issues": "", "ok": True, "blind": True, "reason": "disabled"}
    model, mode = pick_model()
    if not model:
        return {"score": None, "issues": "", "ok": True, "blind": True, "reason": mode}
    prompt = (
        f"Quality-check this tiny game sprite. It should be a clean PIXEL-ART {label} on a "
        f"plain background. Output ONE line of compact JSON and NOTHING else: "
        f'{{"score": <1-10 how clearly it is a clean pixel-art {label}>, '
        f'"issues": "<=8 words", "ok": <true if score>=7>}} /no_think')

    def _job():
        return _call_vision(model, image_path, prompt)
    try:
        # pass model= so the orch loads+verifies the VLM before the job runs
        raw = run_llm_job(_job, f"world:vision:{model.split('/')[-1]}", wait=wait, model=model)
    except Exception as ex:
        log.error("vision eval error: %s", ex)
        raw = None
    return _parse(raw, mode)


def _parse(raw, mode):
    if not raw:
        return {"score": None, "issues": "", "ok": True, "blind": True, "reason": "no-output"}
    # strip any reasoning block a thinking-model may still emit
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S | re.I).strip()
    m = re.search(r'\{[^{}]*"score"[^{}]*\}', raw, re.S) or re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            sc = max(1, min(10, int(round(float(d.get("score", 5))))))
            return {"score": sc, "issues": str(d.get("issues", ""))[:100],
                    "ok": bool(d.get("ok", sc >= 7)), "blind": False, "mode": mode}
        except Exception:
            pass
    n = (re.search(r"([0-9]{1,2})\s*/\s*10", raw) or re.search(r'"?score"?\D{0,4}([0-9]{1,2})', raw, re.I)
         or re.search(r"\brate[sd]?\D{0,8}([0-9]{1,2})", raw, re.I))
    sc = max(1, min(10, int(n.group(1)))) if n else 5
    # verdict: shortest informative sentence that isn't meta-preamble
    sents = [s.strip() for s in re.split(r"[.\n]", raw) if s.strip()
             and "user wants" not in s.lower() and "i need to" not in s.lower()]
    verdict = min(sents, key=len)[:100] if sents else raw[:100]
    return {"score": sc, "issues": verdict, "ok": sc >= 7, "blind": False, "mode": mode}
