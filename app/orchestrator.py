"""
GPU Orchestrator — shared GPU between LM Studio (LLM) and ComfyUI (image/video).
Host / URLs / model come from config.py (STORE_GPU_HOST, STORE_COMFYUI_URL, …).

Unload tools:
  LLM   → SSH to box: lms unload <model>
  Image → POST <comfyui>/free

Flow:
  LLM task  → wait for active images → free ComfyUI VRAM → run → unload LLM immediately after
  Image task → wait for active LLM  → unload LLM → run → release when done
"""
import subprocess, threading, time, httpx, logging
from typing import Callable, Optional

log = logging.getLogger("orch")

try:
    from config import GPU_SSH_USER, GPU_HOST, COMFYUI_URL, ENHANCE_MODEL_DEFAULT, GPU_EXCLUSIVE
    BOX = f"{GPU_SSH_USER}@{GPU_HOST}"
    COMFYUI = COMFYUI_URL
    DEFAULT_MODEL = ENHANCE_MODEL_DEFAULT
except Exception:
    BOX = "user@127.0.0.1"
    COMFYUI = "http://127.0.0.1:8188"
    DEFAULT_MODEL = "google/gemma-4-12b-qat"
    GPU_EXCLUSIVE = True
LMS = "~/.lmstudio/bin/lms"

# Max seconds a queued media job waits for the GPU to free before proceeding anyway.
# Must exceed the longest single job (a 4-min ACE-Step song or a multi-segment video
# chain can run ~10 min) so concurrent video/3D/audio jobs genuinely queue instead of
# timing out and colliding on the single GPU. Override via STORE_GPU_QUEUE_TIMEOUT.
import os as _os
try:
    _QUEUE_WAIT = int(_os.getenv("STORE_GPU_QUEUE_TIMEOUT", "1800"))
except Exception:
    _QUEUE_WAIT = 1800


def _loaded_llms() -> list:
    """Identifiers of LLMs currently loaded in LM Studio (via `lms ps --json`)."""
    import json as _json
    rc, out = _ssh(LMS, "ps", "--json", timeout=10)
    if rc != 0 or not out:
        return []
    try:
        data = _json.loads(out)
        return [m.get("modelKey") or m.get("identifier")
                for m in data if m.get("type") == "llm" and (m.get("modelKey") or m.get("identifier"))]
    except Exception:
        return []


def _active_model(default: str) -> str:
    """The model LM Studio requests are actually sent with (Settings → enhance_model
    overrides the config default). Read straight from the DB so unloads match loads."""
    try:
        from db import get_conn
        conn = get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key='enhance_model'").fetchone()
        conn.close()
        if row and row["value"]:
            return row["value"]
    except Exception:
        pass
    return default


def _idle_ttl() -> int:
    """Seconds a loaded LLM may sit idle before LM Studio auto-unloads it (frees the
    node's VRAM when nothing is using the model). Settings key `model_idle_ttl`,
    default 1800 (30 min). 0 = no TTL (model stays resident until evicted)."""
    try:
        from db import get_conn
        conn = get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key='model_idle_ttl'").fetchone()
        conn.close()
        if row and row["value"] not in (None, ""):
            return max(0, int(row["value"]))
    except Exception:
        pass
    return 1800


def _load_args(model: str) -> list:
    """`lms load` argv with an idle TTL appended so the model auto-unloads when idle."""
    ttl = _idle_ttl()
    return ["load", model] + (["--ttl", str(ttl)] if ttl > 0 else [])


def _ssh(*args, timeout: int = 15) -> tuple[int, str]:
    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout}",
        BOX,
    ] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "ssh timeout"
    except Exception as e:
        return 1, str(e)


class Orchestrator:
    """Mutual-exclusion GPU scheduler for LLM and image generation tasks."""

    def __init__(self, llm_model: str = DEFAULT_MODEL):
        self.llm_model = llm_model
        self._current_llm_model = llm_model   # model _call_lmstudio should target right now
        self._restore_model = None            # model we unloaded for image/video, to reload after
        self._lock = threading.RLock()
        self._img_prepare_lock = threading.Lock()  # serialise image_acquire calls

        # ── GPU states ────────────────────────────────────────────────────────
        self._llm_state = "idle"   # idle | loading | busy | unloading
        self._img_state = "idle"   # idle | loading | busy | unloading
        self._active_images = 0    # number of ComfyUI jobs in flight

        # ── LLM task queue ────────────────────────────────────────────────────
        self._tasks: dict[int, dict] = {}
        self._order: list[int] = []   # insertion order
        self._counter = 0

        # ── Pause gate ────────────────────────────────────────────────────────
        # SET = running, CLEARED = paused. Blocks the LLM worker and every media
        # *_acquire() so NO new GPU job starts while paused; in-flight jobs finish.
        self._pause_gate = threading.Event()
        self._pause_gate.set()

        # ── Worker thread ─────────────────────────────────────────────────────
        self._work_event = threading.Event()
        threading.Thread(
            target=self._worker_loop, daemon=True, name="orch-worker"
        ).start()

    # ─── Public status ────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            llm   = self._llm_state
            img   = self._img_state
            active = self._active_images
            queue = [
                {"id": tid, "type": d["type"], "desc": d["desc"], "status": d["status"],
                 # model this job runs on: its explicit pick, else the currently-resident LLM
                 # it will borrow (so the unified queue shows what's actually loading/running)
                 "model": d.get("model") or (self._current_llm_model if d["type"] == "llm" else None)}
                for tid in self._order
                if (d := self._tasks.get(tid)) and d["status"] in ("pending", "running")
            ]
        return {
            "llm":          llm,
            "image":        img,
            "active_images": active,
            "queue":        queue,
            "message":      self._build_message(llm, img, active, queue),
        }

    # ─── Pause / resume / clear ───────────────────────────────────────────────

    def pause(self):
        """Stop dispatching NEW GPU jobs (LLM + image/video). In-flight jobs finish."""
        self._pause_gate.clear()

    def resume(self):
        """Resume dispatching queued jobs."""
        self._pause_gate.set()
        self._work_event.set()

    def is_paused(self) -> bool:
        return not self._pause_gate.is_set()

    def clear_pending(self) -> int:
        """Cancel every PENDING (not-yet-running) LLM task. Returns how many were cleared."""
        n = 0
        with self._lock:
            for tid in self._order:
                t = self._tasks.get(tid)
                if t and t["status"] == "pending":
                    t["status"] = "cancelled"
                    t["event"].set()
                    n += 1
        return n

    def _build_message(self, llm, img, active, queue) -> str:
        if self.is_paused():
            return "⏸ Queue paused"
        if llm == "loading":    return "⏳ Loading LLM model…"
        if llm == "busy":       return "🤖 LLM running…"
        if llm == "unloading":  return "🔄 Unloading LLM…"
        if img == "loading":    return "⏳ Loading image model…"
        if img == "busy":       return f"🎨 Generating {active} image(s)…"
        if img == "unloading":  return "🔄 Freeing image VRAM…"
        pending = sum(1 for t in queue if t["status"] == "pending")
        if pending and active:
            return f"⏸ LLM queued — waiting for {active} image job(s) to finish"
        if queue:
            return f"⏳ {len(queue)} task(s) in queue"
        return ""

    # ─── LLM task API ─────────────────────────────────────────────────────────

    def submit_llm(
        self,
        func: Callable,
        desc: str,
        retry_meta: Optional[dict] = None,
        model: Optional[str] = None,
        priority: int = 1,
    ) -> int:
        """Submit an LLM task. Returns task_id immediately (non-blocking).

        `model` — if given, the worker guarantees THAT specific model is the sole
        resident LLM (verified via `lms ps`) before running `func`; the orchestrator
        is the single authority for model loading, so nothing races `lms` in parallel.
        If omitted, the worker borrows whatever model is already loaded (legacy path)."""
        with self._lock:
            tid = self._counter
            self._counter += 1
            self._tasks[tid] = {
                "id":         tid,
                "type":       "llm",
                "func":       func,
                "desc":       desc,
                "status":     "pending",
                "result":     None,
                "error":      None,
                "retry_meta": retry_meta,
                "model":      model,
                "priority":   priority,          # 0 user-facing > 1 default > 2 background
                "enqueued_at": time.time(),
                "event":      threading.Event(),
            }
            self._order.append(tid)
            self._prune()
        self._work_event.set()
        return tid

    def poll(self, task_id: int) -> dict:
        with self._lock:
            t = self._tasks.get(task_id)
        if not t:
            return {"id": task_id, "status": "not_found"}
        return {
            "id":         task_id,
            "status":     t["status"],
            "result":     t["result"],
            "error":      t["error"],
            "retry_meta": t.get("retry_meta"),
        }

    def cancel(self, task_id: int) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            if t and t["status"] == "pending":
                t["status"] = "cancelled"
                t["event"].set()
                return True
        return False

    def _prune(self):
        """Keep only the last 50 completed tasks (called under lock)."""
        done_ids = [
            tid for tid in self._order
            if self._tasks.get(tid, {}).get("status") not in ("pending", "running")
        ]
        for old in done_ids[:-50]:
            self._tasks.pop(old, None)
            self._order.remove(old)

    # ─── Image task hooks ─────────────────────────────────────────────────────

    def image_acquire(self):
        """
        Call BEFORE submitting work to ComfyUI.
        Blocks until any active LLM task finishes, then unloads LLM from VRAM.
        Serialised so multiple concurrent generations don't race.
        """
        self._pause_gate.wait()   # hold new image jobs while the queue is paused
        with self._img_prepare_lock:
            # Wait for LLM to go idle
            waited = 0
            while True:
                with self._lock:
                    state = self._llm_state
                if state == "idle":
                    break
                if waited == 0:
                    log.info("[orch] image_acquire: waiting for LLM (%s)…", state)
                time.sleep(1)
                waited += 1
                if waited > 120:
                    log.warning("[orch] image_acquire: LLM wait timed out")
                    break

            # Wait for any currently-running image jobs to finish first.
            # image_acquire releases _img_prepare_lock before ComfyUI finishes,
            # so without this check two variations would run concurrently and
            # produce near-identical output.
            waited_img = 0
            while True:
                with self._lock:
                    active = self._active_images
                if active == 0:
                    break
                if waited_img == 0:
                    log.info("[orch] image_acquire: waiting for %d active image job(s) to finish…", active)
                time.sleep(1)
                waited_img += 1
                if waited_img > _QUEUE_WAIT:
                    log.warning("[orch] image_acquire: active-image wait timed out")
                    break

            # Unload LLM to free VRAM for the image model (exclusive GPU only)
            self._free_llm_for_media()

            with self._lock:
                self._active_images += 1
                self._img_state = "busy"

    def image_release(self):
        """Call when a ComfyUI job finishes (success or failure)."""
        with self._lock:
            self._active_images = max(0, self._active_images - 1)
            done = self._active_images == 0
            if done:
                self._img_state = "idle"
        # Wake worker — a queued LLM task may now proceed
        self._work_event.set()
        if done:
            self._restore_if_needed()

    def _free_llm_for_media(self, force: bool = False):
        """Unload the LLM to free VRAM for image/video gen. Skipped when the GPU has
        room for both (STORE_GPU_EXCLUSIVE=0) unless forced (video is very heavy).
        Remembers what was loaded so it can be restored afterwards."""
        if not force and not GPU_EXCLUSIVE:
            return
        try:
            loaded = _loaded_llms()
            self._restore_model = loaded[0] if loaded else None
        except Exception:
            self._restore_model = None
        self._set(llm="unloading")
        self._unload_llm()
        self._set(llm="idle")
        time.sleep(3)   # let VRAM settle

    def _restore_if_needed(self):
        """After media gen, reload the model we evicted — but only if no LLM task is
        queued (a queued task would load its own model / borrow anyway)."""
        with self._lock:
            model = self._restore_model
            self._restore_model = None
            pending = any(self._tasks.get(t, {}).get("status") == "pending" for t in self._order)
        if not model or pending:
            return

        def _do_restore():
            # Hold the SAME prepare-lock the media *_acquire() paths use, so a restore
            # and a media job can never both be arranging the GPU at once. Re-check under
            # it: a new media job (image/video/3D/audio all bump _active_images) may have
            # grabbed the GPU while this thread was starting — reloading now would OOM it.
            with self._img_prepare_lock:
                with self._lock:
                    busy = self._active_images > 0 or self._img_state != "idle"
                if busy:
                    log.info("[orch] skip LLM restore — a media job is using the GPU")
                    return
                log.info("[orch] restoring previously-loaded model: %s", model)
                _ssh(LMS, *_load_args(model), timeout=180)
        threading.Thread(target=_do_restore, daemon=True, name="orch-restore").start()

    def video_acquire(self):
        """
        Call BEFORE submitting work to Wan2.1 / any video gen pipeline.
        Like image_acquire(), but ALSO frees ComfyUI VRAM first.

        Why needed: Wan2.1's T5-XXL text encoder needs ~9.5 GB VRAM even with
        CPU offloading.  If ComfyUI has SDXL cached (~6.7 GB) + T5 = 16+ GB > 12 GB.
        We must free ComfyUI *and* LM Studio before any video generation starts.
        """
        self._pause_gate.wait()   # hold new video jobs while the queue is paused
        with self._img_prepare_lock:
            # Wait for LLM to go idle
            waited = 0
            while True:
                with self._lock:
                    state = self._llm_state
                if state == "idle":
                    break
                if waited == 0:
                    log.info("[orch] video_acquire: waiting for LLM (%s)\u2026", state)
                time.sleep(1)
                waited += 1
                if waited > 120:
                    log.warning("[orch] video_acquire: LLM wait timed out")
                    break

            # Wait for active image/video jobs to finish
            waited_img = 0
            while True:
                with self._lock:
                    active = self._active_images
                if active == 0:
                    break
                if waited_img == 0:
                    log.info("[orch] video_acquire: waiting for %d active job(s)\u2026", active)
                time.sleep(1)
                waited_img += 1
                if waited_img > _QUEUE_WAIT:
                    log.warning("[orch] video_acquire: active-job wait timed out")
                    break

            # Free ComfyUI VRAM (SDXL ~6.7 GB) + unload LM Studio before video gen.
            # Video is heavy (T5-XXL ~9.5 GB), so free the LLM even on a big GPU.
            log.info("[orch] video_acquire: freeing ComfyUI + LLM VRAM for video gen\u2026")
            self._set(img="unloading")
            self._free_comfyui()
            self._set(img="idle")
            self._free_llm_for_media(force=True)

            with self._lock:
                self._active_images += 1
                self._img_state = "busy"

    def video_release(self):
        """Call when a video generation job finishes (success or failure)."""
        self.image_release()   # same release mechanism

    # ─── Worker loop ──────────────────────────────────────────────────────────

    def _worker_loop(self):
        while True:
            self._work_event.wait()
            self._work_event.clear()
            self._drain()

    def _drain(self):
        """Process pending LLM tasks, one at a time, in scheduler order."""
        while True:
            self._pause_gate.wait()   # hold here while the queue is paused
            with self._lock:
                task = self._pick_pending()
            if not task:
                break
            self._run_llm_task(task)

    def _pick_pending(self):
        """Choose the next pending LLM task (called under self._lock). Uses the unified
        scheduler (priority → model-affinity batching → anti-starvation aging); falls back
        to FIFO on ANY issue so a scheduler bug can never wedge the worker."""
        pending = [tid for tid in self._order
                   if (t := self._tasks.get(tid)) and t["status"] == "pending"]
        if not pending:
            return None
        try:
            import gpu_scheduler as _sched
            jobs = [_sched.Job(
                        id=tid,
                        kind="llm",
                        model=self._tasks[tid].get("model"),
                        priority=int(self._tasks[tid].get("priority", 1)),
                        enqueued_at=float(self._tasks[tid].get("enqueued_at", 0.0)))
                    for tid in pending]
            nxt = _sched.pick_next(jobs, resident_model=self._current_llm_model, now=time.time())
            if nxt is not None:
                return self._tasks[nxt.id]
        except Exception as e:
            log.warning("[orch] scheduler pick failed — FIFO fallback: %s", e)
        return self._tasks[pending[0]]   # FIFO fallback (current-loaded behavior)

    def _run_llm_task(self, task: dict):
        try:
            # ── Step 1: wait for image gen(s) to finish ───────────────────────
            waited = 0
            while True:
                with self._lock:
                    active = self._active_images
                if active == 0:
                    break
                if waited == 0:
                    log.info("[orch] LLM task queued — waiting for %d image job(s)…", active)
                time.sleep(2)
                waited += 2

            # Bail if cancelled while waiting
            with self._lock:
                if task["status"] == "cancelled":
                    return

            # ── Step 2: free ComfyUI VRAM (only when the GPU can't hold both) ──
            if GPU_EXCLUSIVE:
                self._set(img="unloading")
                self._free_comfyui()
                self._set(img="idle")
            self._set(llm="loading")

            # Final cancelled check before running
            with self._lock:
                if task["status"] == "cancelled":
                    self._set(llm="idle")
                    return
                task["status"] = "running"

            # ── Step 3: get the model ready. If the task REQUIRES a specific model,
            # load+verify it (single authority, no race); else borrow the loaded one. ──
            required = task.get("model")
            if required:
                if not self._ensure_loaded(required):
                    raise RuntimeError(
                        f"LM Studio could not load required model '{required}' "
                        f"(loaded={_loaded_llms()})")
            else:
                self._current_llm_model = self._pick_llm_model()
            self._set(llm="busy")
            result = task["func"]()

            with self._lock:
                task["result"] = result
                task["status"] = "done"

        except Exception as e:
            log.error("[orch] task %d error: %s", task["id"], e)
            with self._lock:
                task["error"] = str(e)
                task["status"] = "error"
        finally:
            task["event"].set()
            # ── Step 4: keep the LLM loaded for reuse (no thrash). It is only
            # unloaded when image/video gen actually needs the VRAM. ──
            self._set(llm="idle")

    def _ensure_loaded(self, model: str) -> bool:
        """Make `model` the sole resident LLM and VERIFY it via `lms ps` before we
        dispatch. This is the fix for the proxy's 'Model is unloaded' race: model
        loading happens ONLY here, in the single worker, and is confirmed resident
        before the request runs. Returns True on success, False if the load never
        takes (caller turns that into a clean task error)."""
        model = (model or "").split("lmstudio/", 1)[-1].strip()
        if not model:
            return False
        def _match():
            try:
                loaded = _loaded_llms()
            except Exception:
                loaded = []
            return any(m == model or m.endswith("/" + model) or model.endswith("/" + m)
                       for m in loaded), loaded
        ok, loaded = _match()
        if ok:
            self._current_llm_model = model
            return True
        # `lms load` is SYNCHRONOUS (blocks until the model is ready) and evicting the
        # resident model first avoids the HTTP hot-swap that 400s. Try up to twice.
        for attempt in range(2):
            _, loaded = _match()
            for m in loaded:                   # GPU_EXCLUSIVE → evict first
                _ssh(LMS, "unload", m, timeout=20)
            log.info("[orch] ensure_loaded: loading '%s' (attempt %d)", model, attempt + 1)
            _ssh(LMS, *_load_args(model), timeout=240)
            time.sleep(3)                      # let it settle past any 'loading' state
            ok, now = _match()
            if ok:
                self._current_llm_model = model
                log.info("[orch] ensure_loaded: '%s' resident", model)
                return True
            log.warning("[orch] ensure_loaded: '%s' not resident after load (saw %s)", model, now)
        return False

    def _pick_llm_model(self) -> str:
        """Borrow an already-loaded LLM if present (avoids evicting OpenClaw's model
        and avoids failed loads); otherwise fall back to the configured/Settings model."""
        try:
            loaded = _loaded_llms()
            if loaded:
                log.info("[orch] borrowing loaded model: %s", loaded[0])
                return loaded[0]
        except Exception:
            pass
        return _active_model(self.llm_model)

    # ─── GPU operations ───────────────────────────────────────────────────────

    def _set(self, llm: str = None, img: str = None):
        with self._lock:
            if llm is not None:
                self._llm_state = llm
            if img is not None:
                self._img_state = img

    def _free_comfyui(self):
        """POST /free to ComfyUI — unloads model weights, keeps process alive."""
        try:
            r = httpx.post(
                f"{COMFYUI}/free",
                json={"unload_models": True, "free_memory": True},
                timeout=10,
            )
            time.sleep(2)   # give VRAM time to settle
            log.info("[orch] ComfyUI /free → %s", r.status_code)
        except Exception as e:
            log.info("[orch] ComfyUI /free skipped: %s", e)

    def _unload_llm(self):
        """SSH to box and run: lms unload <model> (the model actually in use)."""
        model = _active_model(self.llm_model)
        rc, out = _ssh(LMS, "unload", model, timeout=15)
        if rc == 0:
            log.info("[orch] lms unload OK: %s", out[:80])
        else:
            # Might fail if already unloaded — not an error
            log.info("[orch] lms unload rc=%d: %s", rc, out[:80])


# ── Singleton ─────────────────────────────────────────────────────────────────
orch = Orchestrator()
