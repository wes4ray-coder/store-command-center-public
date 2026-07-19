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


# ── per-model settings ────────────────────────────────────────────────────────
# One registry (settings key `llm_model_cfg`, JSON {model_id: {param: value}})
# applied AT THE PROXY, so every consumer — world, swarm, oracles, OpenClaw —
# inherits a model's tuning. Explicit params in a request always win; the
# registry only fills the gaps. `system_prepend` prefixes the system message.
_TUNABLE = ("temperature", "top_p", "max_tokens", "presence_penalty",
            "frequency_penalty", "repeat_penalty", "seed")


def _model_cfg(model):
    try:
        from deps import get_setting
        cfg = json.loads(get_setting("llm_model_cfg", "{}") or "{}")
        return cfg.get(model) or {}
    except Exception:
        return {}


def _apply_model_cfg(body, model):
    cfg = _model_cfg(model)
    if not cfg:
        return body
    for k in _TUNABLE:
        if k in cfg and k not in body and cfg[k] not in (None, ""):
            body[k] = cfg[k]
    sp = cfg.get("system_prepend")
    if sp:
        msgs = body.get("messages") or []
        if msgs and msgs[0].get("role") == "system":
            msgs[0]["content"] = f"{sp}\n{msgs[0].get('content') or ''}"
        else:
            msgs.insert(0, {"role": "system", "content": sp})
        body["messages"] = msgs
    return body


@router.get("/api/llm/models/config")
def get_models_config():
    """Per-model tuning registry (+ which params are honoured)."""
    from deps import get_setting
    try:
        cfg = json.loads(get_setting("llm_model_cfg", "{}") or "{}")
    except Exception:
        cfg = {}
    return {"config": cfg, "tunable": list(_TUNABLE) + ["system_prepend"]}


@router.post("/api/llm/models/config")
async def set_models_config(request: Request):
    """Save tuning for one model: {model, config:{temperature,…}} — empty/null
    config removes the model's overrides."""
    body = await request.json()
    model = (body.get("model") or "").strip()
    if not model:
        return JSONResponse({"error": "model required"}, status_code=400)
    from deps import get_conn, get_setting
    try:
        cfg = json.loads(get_setting("llm_model_cfg", "{}") or "{}")
    except Exception:
        cfg = {}
    newc = body.get("config")
    _LOAD_KEYS = ("context_length", "gpu", "ttl", "parallel", "pin")   # applied by lms load, not the request
    clean = {k: v for k, v in (newc or {}).items()
             if k in _TUNABLE + ("system_prepend",) + _LOAD_KEYS and v not in (None, "")}
    if clean:
        cfg[model] = clean
    else:
        cfg.pop(model, None)
    conn = get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('llm_model_cfg',?)",
                     (json.dumps(cfg),))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "config": cfg}


# resident-model cache (8s) for the parallel fast path
_res_cache = {"t": 0.0, "models": []}


def _resident(model):
    import time as _t
    if _t.time() - _res_cache["t"] > 8:
        try:
            from orchestrator import _loaded_llms
            _res_cache["models"] = _loaded_llms() or []
        except Exception:
            _res_cache["models"] = []
        _res_cache["t"] = _t.time()
    return any(m == model or m.endswith("/" + model) or model.endswith("/" + m)
               for m in _res_cache["models"])


def _box_ssh(cmd, timeout=300):
    import subprocess
    from config import _env
    box = _env("STORE_GPU_HOST", "127.0.0.1")
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                        f"user@{box}",
                        f'export PATH="$HOME/.lmstudio/bin:$PATH"; {cmd}'],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


@router.post("/api/llm/models/estimate")
async def model_estimate(request: Request):
    """lms --estimate-only: how much GPU memory this model wants (at default ctx)."""
    body = await request.json()
    m = (body.get("model") or "").strip()
    if not m:
        return JSONResponse({"error": "model required"}, status_code=400)
    try:
        _, out = _box_ssh(f"lms load '{m}' --estimate-only 2>&1 | grep -a 'Estimated GPU'", 60)
        import re
        g = re.search(r"([\d.]+)\s*GiB", out)
        return {"model": m, "estimate_gib": float(g.group(1)) if g else None, "raw": out.strip()[:120]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/llm/models/testload")
async def model_testload(request: Request):
    """RETUNE truth-check: load the model with its saved config and report REAL
    placement — lms says 'loaded' even when it silently fell back to CPU, so we
    verify via nvidia-smi (the CPU-fallback lie detector). Unloads after."""
    body = await request.json()
    m = (body.get("model") or "").strip()
    if not m:
        return JSONResponse({"error": "model required"}, status_code=400)
    cfg = _model_cfg(m)
    flags = ""
    if cfg.get("context_length"):
        flags += f" --context-length {int(cfg['context_length'])}"
    if cfg.get("gpu") not in (None, ""):
        flags += f" --gpu {cfg['gpu']}"
    try:
        _, base = _box_ssh("nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits", 30)
        base_mb = int((base.strip().splitlines() or ["0"])[0] or 0)
        _box_ssh("lms unload --all", 60)
        _box_ssh(f"timeout 280 lms load '{m}'{flags} --ttl 120 -y >/dev/null 2>&1", 300)
        _, ps = _box_ssh("lms ps", 30)
        loaded = m in ps
        _, used = _box_ssh("nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits", 30)
        used_mb = int((used.strip().splitlines() or ["0"])[0] or 0)
        _box_ssh("lms unload --all", 60)
        on_gpu = loaded and (used_mb - base_mb) > 800
        return {"model": m, "loaded": loaded, "gpu_real": on_gpu,
                "vram_mb": used_mb, "baseline_mb": base_mb,
                "verdict": ("✅ loads on GPU" if on_gpu else
                            "⚠️ 'loaded' but on CPU — lower context or gpu ratio" if loaded else
                            "❌ failed to load — lower context or gpu ratio")}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/llm/models/download")
async def model_download(request: Request):
    """Download an LLM onto the node via `lms get` (lands in LM Studio's models
    dir, which follows the storage-location settings). Runs in background."""
    body = await request.json()
    m = (body.get("model") or "").strip()
    if not m or any(c in m for c in ";|&$`"):
        return JSONResponse({"error": "valid model id required"}, status_code=400)
    try:
        _box_ssh(f"nohup lms get '{m}' -y > /tmp/lms_get_{abs(hash(m)) % 99999}.log 2>&1 &", 20)
        return {"ok": True, "model": m, "note": "downloading in background — it appears in the model list when done"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/llm/v1/chat/completions")
async def proxy_chat(request: Request):
    """Verbatim chat/completions, gated by the orchestrator queue. Streams if asked."""
    body = await request.json()
    model = _norm_model(body.get("model") or "")
    body["model"] = model                        # normalized id for LM Studio
    body = _apply_model_cfg(body, model)         # per-model tuning fills unset params
    stream = bool(body.get("stream"))

    # ── PARALLEL FAST PATH ── if the model is already resident and no image job
    # is displacing it, stream straight to LM Studio and let its --parallel slots
    # handle concurrency (this is what allows 2+ simultaneous prompts per model
    # and prompts to DIFFERENT resident models at once). The orch queue is only
    # for loads/swaps.
    if _resident(model) and getattr(orch, "_img_state", "idle") in ("idle", None, ""):
        try:
            orch.mark_activity()   # keep the idle-TTL sweep from evicting an in-use model
            if stream:
                def _gen():
                    with httpx.stream("POST", f"{LMSTUDIO_URL}/chat/completions", json=body,
                                      headers=_llm_headers(), timeout=600) as r:
                        for chunk in r.iter_raw():
                            yield chunk
                return StreamingResponse(_gen(), media_type="text/event-stream")
            r = httpx.post(f"{LMSTUDIO_URL}/chat/completions", json=body,
                           headers=_llm_headers(), timeout=600)
            return JSONResponse(r.json(), status_code=r.status_code)
        except Exception:
            pass                                  # residency was stale → fall through to the queue

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
