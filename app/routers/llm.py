"""
Unified LM Studio proxy — the single front door to the GPU's LLM.

Both the store AND OpenClaw talk to LM Studio. Because the GPU holds one model at a
time, two callers racing a model swap produce the "Failed to load model" 400s we kept
hitting. Fix: funnel EVERY LM Studio request through the store's orchestrator queue so
there is one arbiter for the whole box.

Point OpenClaw at this proxy (one line in openclaw.json):
    models.providers.lmstudio.baseUrl = "http://127.0.0.1:8787/api/llm/v1"

Design (from the investigation in this session):
  * chat/completions runs INSIDE orch.submit_llm → serialized with store LLM tasks and
    preempted by image/video jobs, exactly like everything else.
  * The request body is forwarded VERBATIM (tools, JSON-mode, temperature, stop,
    multi-turn, streaming) — only the `model` field is normalized (strip 'lmstudio/').
  * It RESPECTS the requested model (borrow if resident, else unload+load) rather than
    blindly borrowing the loaded one.
  * embeddings are a NO-orch passthrough (tiny, must not trigger a model swap or memory
    search would thrash).
  * localhost callers skip store auth (main.py guard), so no creds needed.
"""
import queue, logging, json, time
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from deps import LMSTUDIO_URL, _llm_headers
from orchestrator import orch

router = APIRouter()
log = logging.getLogger("store")


def _norm_model(model: str) -> str:
    """OpenClaw sends 'lmstudio/<id>'; `lms` and LM Studio want the bare id."""
    if not model:
        return ""
    return model.split("lmstudio/", 1)[-1]


@router.get("/api/llm/v1/models")
def proxy_models():
    """OpenAI-style model list (passthrough)."""
    try:
        r = httpx.get(f"{LMSTUDIO_URL}/models", headers=_llm_headers(), timeout=15)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/llm/v1/embeddings")
async def proxy_embeddings(request: Request):
    """Passthrough — NO orch, NO model swap (embeddings coexist with the chat model;
    forcing an unload would thrash OpenClaw's memory search)."""
    body = await request.body()
    try:
        r = httpx.post(f"{LMSTUDIO_URL}/embeddings", content=body,
                       headers={**_llm_headers(), "Content-Type": "application/json"}, timeout=120)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/llm/v1/chat/completions")
async def proxy_chat(request: Request):
    """Verbatim chat/completions, gated by the orchestrator queue. Streams if asked."""
    body = await request.json()
    model = _norm_model(body.get("model") or "")
    body["model"] = model                        # normalized id for LM Studio
    stream = bool(body.get("stream"))
    q: "queue.Queue" = queue.Queue(maxsize=256)

    def work():
        # By the time this runs, the orchestrator has already loaded + VERIFIED `model`
        # as the resident LLM (submit_llm(model=...)). No lms poking here — no race.
        try:
            with httpx.stream("POST", f"{LMSTUDIO_URL}/chat/completions", json=body,
                              headers=_llm_headers(), timeout=600) as r:
                if r.status_code != 200:
                    q.put(("status", r.status_code)); q.put(("chunk", r.read())); q.put(None); return "err"
                for chunk in r.iter_raw():
                    q.put(("chunk", chunk))
        except Exception as e:                    # surface transport errors to the caller
            q.put(("chunk", json.dumps({"error": str(e)}).encode())); q.put(("status", 502))
        q.put(None)
        return "ok"

    tid = orch.submit_llm(work, desc=f"proxy:{model or '?'}", model=model or None)

    def _next(timeout=1.0):
        """Get the next queue item, but never block forever: if the orch task
        errored/was cancelled before work() could sentinel the queue (e.g. a model
        load failed), synthesize an error item so callers don't hang."""
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            p = orch.poll(tid)
            if p["status"] in ("error", "cancelled", "not_found"):
                return ("fail", (p.get("error") or "model unavailable").encode())
            return "wait"

    if stream:
        def gen():
            while True:
                item = _next()
                if item == "wait":
                    continue
                if item is None:
                    break
                if item[0] == "fail":
                    yield b"data: " + json.dumps({"error": item[1].decode()}).encode() + b"\n\n"
                    break
                if item[0] == "chunk":
                    yield item[1]
        return StreamingResponse(gen(), media_type="text/event-stream")

    # non-streaming: drain the whole body, then return it
    status, parts, deadline = 200, [], time.time() + 300
    while True:
        item = _next()
        if item == "wait":
            if time.time() > deadline:
                return JSONResponse({"error": "queue timeout"}, status_code=504)
            continue
        if item is None:
            break
        if item[0] == "fail":
            return JSONResponse({"error": item[1].decode()}, status_code=503)
        if item[0] == "status":
            status = item[1]
        else:
            parts.append(item[1])
    raw = b"".join(parts)
    try:
        return JSONResponse(json.loads(raw.decode() or "{}"), status_code=status)
    except Exception:
        return JSONResponse({"error": "bad upstream response", "raw": raw.decode(errors="replace")[:400]},
                            status_code=status if status != 200 else 502)
