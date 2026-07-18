# Unified GPU Job Queue — design blueprint

Turn every GPU-touching call (store LLM, vision, ComfyUI image/video, and — via a
proxy — every OpenClaw request) into a typed **Job**, put them all in ONE sorted
queue, and let a single scheduler run the correct model with checks between jobs and
lifecycle hooks when the queue goes empty or gains its first job. This supersedes the
ad-hoc `orchestrator.py` handshakes and ends the model-swap 400s caused by OpenClaw
and the store fighting over LM Studio's single VRAM slot.

## The Job object

```python
@dataclass
class Job:
    id: int
    kind: str            # 'llm' | 'vision' | 'image' | 'video'
    model: str | None    # model the job REQUIRES ('*' = borrow whatever's loaded)
    payload: dict         # messages / prompt / ComfyUI workflow
    priority: int         # 0 user-facing > 1 autobuild/vision > 2 background cognition
    origin: str          # 'store' | 'openclaw' | 'world'
    enqueued_at: float
    event: threading.Event   # caller waits on this
    result: any = None
    error: str | None = None
    status: str = 'pending'  # pending|running|done|error|cancelled
```

Every current entry point becomes `scheduler.submit(Job(...))` → returns immediately;
caller `await`/blocks on `job.event`. `_call_lmstudio`, `world_vision.evaluate_asset`,
`services.run_generation`, and `services_media.*` all collapse to building a Job.

## One sorted queue (priority + model affinity)

The scheduler does NOT run strict FIFO. Each pick:

1. Take the highest-priority pending job.
2. **Affinity boost**: if other pending jobs need the *same* model, pull them forward
   so they run back-to-back on one load (pay the swap once).
3. **Anti-starvation (aging)**: a job's effective priority rises with wait time, so
   affinity batching can never defer a higher-priority job past a cap (e.g. +1 tier
   per 60s waited). This is the one subtlety to get right — pure affinity starves a
   lone urgent job behind a big same-model batch.

## Model resolution — the "checks in between"

Before each job runs, resolve the cheapest legal GPU move (reuses today's primitives):

| Situation | Action | Existing primitive |
|---|---|---|
| job.kind image/video | free the LLM, then ComfyUI | `image_acquire` / `video_acquire` |
| required model already resident (`lms ps`) | **borrow**, no swap | `_loaded_llms()`, `_pick_llm_model()` |
| VRAM slot empty | **load** cleanly | request model → LM Studio JIT-loads |
| wrong model resident | **unload → load** (the only swap; affinity makes it rare) | `_free_llm_for_media()` does the `lms unload` |
| model `'*'` (borrow-any) | use resident, else default | `_pick_llm_model()` |

Key rule learned the hard way: **LM Studio's HTTP API cannot hot-swap** — requesting
model B while A is resident 400s. So a swap MUST be explicit `unload(A)` then `load(B)`.
The scheduler owns this; callers never request a model that isn't going to be loaded.

## Lifecycle hooks — "before and after / empty or new"

- **on_first_job (queue was empty → new job arrives)**: warm hook. Resolve+load the
  target model up front, set GPU busy, so the first job doesn't pay a cold check.
- **on_drain (last job finished → queue empty)**: cool hook. Keep-warm policy — keep
  the general VLM (`enhance_model`, unified on `qwen/qwen3.5-9b`) resident so the next
  thought/vision is instant; unload only under memory pressure or a configurable idle
  TTL. Mirrors `_restore_if_needed()` but centralized.
- **between jobs**: re-check `lms ps` (state can drift if anything external slipped in)
  before committing the next model move.

## Folding in OpenClaw (the whole point)

OpenClaw currently calls LM Studio directly and bypasses the queue. Fix: the store
exposes an OpenAI-compatible proxy that enqueues Jobs, and OpenClaw points at it.

- Store endpoints: `POST /api/llm/v1/chat/completions`, `GET /api/llm/v1/models`
  (localhost `/api/*` already bypasses the store auth guard — no creds needed).
  Each request → `Job(kind='llm', model=body.model, origin='openclaw', priority=…)`
  → scheduler → forward to LM Studio → return (stream passthrough for SSE requests).
- OpenClaw config: repoint its LM Studio provider `baseUrl` from
  `http://127.0.0.1:1234/v1` to the store proxy. After that, **nothing talks to
  LM Studio except the scheduler** — the "OpenClaw loaded a coder behind our back"
  race is structurally impossible. (Provider-URL location + streaming needs are being
  confirmed by a separate investigation.)

## Migration (incremental, non-breaking)

1. Add `scheduler.py` wrapping today's `Orchestrator` state (`_llm_state`, `_img_state`,
   `_active_images`, the worker thread) but with the typed queue + affinity sort.
2. Route store LLM/vision/image/video through `scheduler.submit`; keep `orch.*` shims
   delegating to it so nothing else breaks.
3. Add the `/api/llm/v1/*` proxy (store traffic first, validate).
4. Repoint OpenClaw last, with a fallback: if the proxy is down/restarting, OpenClaw
   should degrade (direct URL) rather than hang — keep a health check + timeout.

## Risks
- Extra hop latency for OpenClaw (small vs model-load cost).
- Proxy must preserve tool/function-calling + JSON-mode + streaming or OpenClaw agents
  regress — passthrough the body verbatim, don't reshape.
- Single point of failure: the store now gates all inference. Mitigate with the health
  check + direct-URL fallback above.
