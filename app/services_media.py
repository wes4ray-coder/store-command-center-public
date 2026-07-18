"""Video + audio generation on the GPU node — diffusers video (Wan/LTX/CogVideoX),
MusicGen + MMS-TTS + Stable Audio + ACE-Step music/voice, and the video→audio bridge.
Split out of services.py for size; re-exported by it (from services_media import *)."""
import signal
import re as _re
from deps import *


# ─── Video generation infrastructure ─────────────────────────────────────────
# Registry of running gen subprocesses so we can cancel a stuck job, + a mutex so
# two videos never hit the single GPU node at once (they'd fight over VRAM).
_VIDEO_PROCS: dict = {}          # vid_id -> Popen
_VIDEO_PROCS_LOCK = threading.Lock()
_VIDEO_RUN_LOCK = threading.Lock()   # only one video subprocess at a time

# First-run downloads are big; heavy models take far longer than the 1.3B default.
_VIDEO_TIMEOUTS = {
    "Wan-AI/Wan2.1-T2V-14B-Diffusers": 3600,
    "THUDM/CogVideoX-5b":              3600,
    "tencent/HunyuanVideo":            5400,
}
def _video_timeout(model_id: str) -> int:
    try:
        base = int(_env("STORE_VIDEO_TIMEOUT", "0")) if "_env" in globals() else 0
    except Exception:
        base = 0
    return base or _VIDEO_TIMEOUTS.get(model_id or "", 1800)


def _video_preflight() -> tuple:
    """Fast checks so a doomed job fails instantly with a clear reason instead of
    burning 30 minutes. Returns (ok: bool, message: str)."""
    if not Path(VIDEO_GEN_SCRIPT).exists():
        return False, (f"Video generator script not found at {VIDEO_GEN_SCRIPT}. "
                       "Set STORE_VIDEO_GEN_SCRIPT in Settings to point at it.")
    host = globals().get("GPU_HOST", "")
    if host and "BOX_SSH" in globals():
        try:
            r = subprocess.run(
                BOX_SSH + ["true"],
                capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return False, (f"GPU node {host} is unreachable over SSH "
                               f"({(r.stderr or '').strip()[:120] or 'no route / auth'}). "
                               "Is the box on and reachable?")
        except subprocess.TimeoutExpired:
            return False, f"GPU node {host} did not respond within 15s (box off or network down?)."
        except Exception as ex:
            return False, f"Could not reach GPU node {host}: {ex}"
    return True, "ok"


import re as _re

def _parse_gen_line(line: str, state: dict, steps: int):
    """Turn a generator output line into (percent, message) for the progress bar, or
    None. Uses the remote script's flushed '[videogen] <phase>' markers to know which
    phase we're in, then maps the denoising step counter (the tqdm bar whose total ==
    num_inference_steps, or an explicit '[progress] X/Y') across the 10–95% band.
    Model-loading / VAE tqdm bars (different totals) are ignored so the bar doesn't
    jump around. `state` carries the 'in generation phase' flag between lines."""
    l = line.strip()
    low = l.lower()
    # Phase markers (authoritative about where we are)
    if "[videogen]" in l:
        if "loading previous" in low:
            return 6, "Loading previous segment…"
        if "loading" in low and "loaded" not in low:
            return 3, "Loading model (first run downloads it)…"
        if l.lower().startswith("[videogen] loaded") or "cpu offload" in low:
            return 8, "Model loaded — preparing GPU…"
        if "generating" in low:
            state["gen"] = True
            return 10, "Generating…"
        if "done:" in low:
            state["gen"] = False
            return 97, "Encoding video…"
        return None
    # Step counters — explicit [progress] (authoritative) or the denoise tqdm bar.
    m = _re.search(r"\[progress\]\s*(\d+)\s*/\s*(\d+)", l)
    if not m:
        m = _re.search(r"(\d+)\s*/\s*(\d+)\s*\[", l)   # tqdm: "9/15 [00:12<..]"
    if m:
        cur, tot = int(m.group(1)), max(1, int(m.group(2)))
        # Only the denoising loop (total == requested steps) drives the bar; ignore
        # loading/VAE bars with other totals. Once generating, allow it.
        if state.get("gen") and steps and tot == int(steps):
            return min(95, 10 + int(85 * min(cur, tot) / tot)), f"Generating — step {cur}/{tot}"
    return None


def _run_gen(cmd: list, timeout: int, vid_id: int, on_progress=None, steps: int = 0):
    """Run a generation subprocess in its own process group so a cancel can kill the
    whole tree (ssh + remote python). Streams output line-by-line to drive a live
    progress bar via on_progress(pct, msg). Registers it under vid_id for cancellation.
    Returns a CompletedProcess-like object with returncode/stdout/stderr."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, start_new_session=True)
    with _VIDEO_PROCS_LOCK:
        _VIDEO_PROCS[vid_id] = proc

    timed_out = {"v": False}
    def _on_timeout():
        timed_out["v"] = True
        _kill_proc(proc)
    timer = threading.Timer(timeout, _on_timeout)
    timer.daemon = True
    timer.start()

    tail = []   # keep the last N lines for error reporting
    pstate = {"gen": False}
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            tail.append(line)
            if len(tail) > 300:
                tail = tail[-300:]
            if on_progress:
                try:
                    pm = _parse_gen_line(line, pstate, steps)
                    if pm:
                        on_progress(pm[0], pm[1])
                except Exception:
                    pass
        proc.wait()
    finally:
        timer.cancel()
        with _VIDEO_PROCS_LOCK:
            _VIDEO_PROCS.pop(vid_id, None)

    if timed_out["v"]:
        raise subprocess.TimeoutExpired(cmd, timeout)

    class _R:
        pass
    r = _R()
    r.returncode = proc.returncode
    r.stdout = "\n".join(tail)
    r.stderr = ""   # merged into stdout
    return r


def _kill_proc(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def cancel_video(vid_id: int) -> bool:
    """Kill a running video subprocess (if any). Returns True if one was killed."""
    with _VIDEO_PROCS_LOCK:
        proc = _VIDEO_PROCS.get(vid_id)
    if proc and proc.poll() is None:
        _kill_proc(proc)
        return True
    return False


def reconcile_stuck_media():
    """On startup, any video/chain left 'generating' or 'queued' is orphaned (the
    process died with the previous server). Mark it failed with a clear reason so the
    gallery doesn't poll forever on a job that will never finish."""
    try:
        conn = get_conn()
        conn.execute(
            "UPDATE videos SET status='failed', error='Interrupted by a server restart — "
            "re-generate to try again.', updated_at=datetime('now') "
            "WHERE status IN ('queued','generating')")
        conn.execute(
            "UPDATE video_chains SET status='failed', "
            "error=COALESCE(error,'Interrupted by a server restart'), updated_at=datetime('now') "
            "WHERE status IN ('pending','generating')")
        conn.execute(
            "UPDATE videos SET audio_status='failed', "
            "audio_error='Interrupted by a server restart' "
            "WHERE audio_status IN ('queued','generating')")
        conn.execute(
            "UPDATE audio_clips SET status='failed', "
            "error='Interrupted by a server restart' WHERE status IN ('queued','generating')")
        conn.commit()
        conn.close()
    except Exception as ex:
        logger.error("reconcile_stuck_media failed: %s", ex)


def _chain_segment_path(chain_id: int, idx: int, ts: int) -> Path:
    return VIDEOS_DIR / f"chain_{chain_id}_seg{idx}_{ts}.mp4"

def _chain_compiled_path(chain_id: int) -> Path:
    return VIDEOS_DIR / f"chain_{chain_id}_compiled.mp4"

def _compile_chain_video(video_paths: list[str], output: str, fps: int = 16) -> str:
    """Concatenate segment videos with xfade transitions using ffmpeg."""
    import subprocess as _sp
    import shutil

    if len(video_paths) == 1:
        shutil.copy2(video_paths[0], output)
        return output

    fade_duration = 0.5

    # Get durations via ffprobe
    durations = []
    for vp in video_paths:
        r = _sp.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", vp],
            capture_output=True, text=True,
        )
        try:
            durations.append(float(r.stdout.strip()))
        except ValueError:
            durations.append(3.0)   # fallback if probe fails

    # Build inputs
    inputs = []
    for vp in video_paths:
        inputs.extend(["-i", vp])

    # Build xfade filter chain
    # offset[i] = sum(durations[0..i-1]) - i * fade_duration
    if len(video_paths) == 2:
        offset = max(0.1, durations[0] - fade_duration)
        fc = f"[0:v][1:v]xfade=transition=fade:duration={fade_duration}:offset={offset:.3f}[v]"
        map_arg = "[v]"
    else:
        parts = []
        prev = "[0:v]"
        for i in range(1, len(video_paths)):
            offset = max(0.1, sum(durations[:i]) - i * fade_duration)
            out = "[v]" if i == len(video_paths) - 1 else f"[v{i}]"
            parts.append(f"{prev}[{i}:v]xfade=transition=fade:duration={fade_duration}:offset={offset:.3f}{out}")
            prev = out
        fc = ";".join(parts)
        map_arg = "[v]"

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", fc,
        "-map", map_arg,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        output
    ]
    _sp.run(cmd, check=True, capture_output=True)
    return output

def run_chain_generation(chain_id: int):
    """Background task: generate all segments of a video chain sequentially."""
    conn = get_conn()
    chain = conn.execute("SELECT * FROM video_chains WHERE id=?", (chain_id,)).fetchone()
    if not chain:
        conn.close()
        return

    prompts    = json.loads(chain["prompts"])
    model_id   = chain["model_id"] or "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
    width      = chain["width"]  or 832
    height     = chain["height"] or 480
    num_frames = chain["num_frames"] or 49
    steps      = chain["steps"]  or 20
    fps        = chain["fps"]    or 16
    strength   = chain["strength"] if chain["strength"] is not None else 0.7

    conn.close()

    # Preflight once for the whole chain — don't queue N doomed segments.
    ok, msg = _video_preflight()
    if not ok:
        c = get_conn()
        c.execute("UPDATE video_chains SET status='failed',error=?,updated_at=datetime('now') WHERE id=?", (msg[:400], chain_id))
        c.commit(); c.close()
        logger.error("Chain %d preflight failed: %s", chain_id, msg)
        return

    conn = get_conn()
    conn.execute(
        "UPDATE video_chains SET status='generating',error=NULL,updated_at=datetime('now') WHERE id=?",
        (chain_id,)
    )
    conn.commit()
    conn.close()

    tmo = _video_timeout(model_id)
    prev_video_path: str | None = None
    segment_video_ids: list[int] = []

    for idx, prompt in enumerate(prompts):
        orch.video_acquire()   # frees ComfyUI + LLM VRAM; needed because T5-XXL text encoder alone is ~9.5 GB
        conn = get_conn()
        seed = random.randint(1, 2**31 - 1)
        ts   = int(datetime.now().timestamp())
        out_path = _chain_segment_path(chain_id, idx, ts)

        # Insert a video row for this segment
        cur = conn.execute(
            "INSERT INTO videos (prompt,width,height,num_frames,steps,fps,seed,status,model_id,chain_id,chain_index) "
            "VALUES (?,?,?,?,?,?,?,'generating',?,?,?)",
            (prompt, width, height, num_frames, steps, fps, seed, model_id, chain_id, idx),
        )
        vid_id = cur.lastrowid
        conn.commit()
        conn.close()

        try:
            _cb = lambda p, m, _v=vid_id: _set_video_progress(_v, p, m)
            if idx == 0 or prev_video_path is None:
                # Segment 0: standard T2V
                result = _run_gen(
                    [str(VIDEO_GEN_SCRIPT), prompt, str(out_path),
                     str(width), str(height), str(num_frames), str(steps),
                     str(seed), str(fps), model_id],
                    timeout=tmo, vid_id=vid_id, on_progress=_cb, steps=int(steps),
                )
            else:
                # Subsequent segments: V2V continuation from previous segment
                result = _run_gen(
                    [str(VIDEO_CONT_SCRIPT), prompt, prev_video_path, str(out_path),
                     str(width), str(height), str(num_frames), str(steps),
                     str(seed), str(fps), model_id, str(strength)],
                    timeout=tmo, vid_id=vid_id, on_progress=_cb, steps=int(steps),
                )

            if result.returncode == 0 and out_path.exists():
                conn = get_conn()
                conn.execute(
                    "UPDATE videos SET status='done',video_path=?,seed=?,progress=100,progress_msg='Done',updated_at=datetime('now') WHERE id=?",
                    (str(out_path), seed, vid_id)
                )
                conn.execute(
                    "UPDATE video_chains SET completed_segments=completed_segments+1,"
                    "updated_at=datetime('now') WHERE id=?", (chain_id,)
                )
                conn.commit()
                conn.close()
                prev_video_path = str(out_path)
                segment_video_ids.append(vid_id)
                logger.info("Chain %d seg %d done: %s", chain_id, idx, out_path)
            else:
                err = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()[-800:] or "unknown"
                logger.error("Chain %d seg %d failed (rc=%d): %s", chain_id, idx, result.returncode, err)
                conn = get_conn()
                conn.execute("UPDATE videos SET status='failed',error=? WHERE id=?", (err, vid_id))
                conn.execute(
                    "UPDATE video_chains SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",
                    (f"Segment {idx+1} failed: {err[:200]}", chain_id)
                )
                conn.commit()
                conn.close()
                orch.video_release()
                return

        except subprocess.TimeoutExpired:
            logger.error("Chain %d seg %d timed out", chain_id, idx)
            conn = get_conn()
            conn.execute("UPDATE videos SET status='failed',error=? WHERE id=?",
                         (f"Timed out after {tmo//60} min", vid_id))
            conn.execute(
                "UPDATE video_chains SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",
                (f"Segment {idx+1} timed out", chain_id)
            )
            conn.commit()
            conn.close()
            orch.video_release()
            return
        except Exception as ex:
            logger.error("Chain %d seg %d exception: %s", chain_id, idx, ex)
            conn = get_conn()
            conn.execute("UPDATE videos SET status='failed',error=? WHERE id=?", (str(ex)[:800], vid_id))
            conn.execute(
                "UPDATE video_chains SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",
                (str(ex)[:200], chain_id)
            )
            conn.commit()
            conn.close()
            orch.video_release()
            return
        finally:
            orch.video_release()

    # All segments done — mark chain done
    conn = get_conn()
    conn.execute(
        "UPDATE video_chains SET status='done',updated_at=datetime('now') WHERE id=?", (chain_id,)
    )
    conn.commit()
    conn.close()
    logger.info("Chain %d complete — %d segments", chain_id, len(prompts))

def _set_video_progress(vid_id: int, pct: int, msg: str):
    try:
        conn = get_conn()
        conn.execute("UPDATE videos SET progress=?,progress_msg=? WHERE id=?",
                     (max(0, min(100, int(pct))), msg[:120], vid_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _fail_video(vid_id: int, reason: str):
    try:
        conn = get_conn()
        conn.execute("UPDATE videos SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",
                     (reason[:800], vid_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def run_video_generation(vid_id: int):
    """Generate a video on the GPU node via SSH. One video at a time (GPU mutex),
    with a preflight check and the failure reason surfaced to the UI."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM videos WHERE id=?", (vid_id,)).fetchone()
    if not row:
        conn.close()
        return
    row = dict(row)
    conn.close()
    model_id = row["model_id"] or "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"

    # Preflight before touching VRAM — fail fast with a clear reason.
    ok, msg = _video_preflight()
    if not ok:
        logger.error("Video %d preflight failed: %s", vid_id, msg)
        _fail_video(vid_id, msg)
        return

    # Serialize: only one video subprocess against the single GPU node at a time.
    with _VIDEO_RUN_LOCK:
        # Cancelled/deleted while we waited for the lock?
        c0 = get_conn()
        cur = c0.execute("SELECT status FROM videos WHERE id=?", (vid_id,)).fetchone()
        c0.close()
        if not cur or cur["status"] not in ("queued", "generating"):
            return

        orch.video_acquire()   # frees ComfyUI + LLM VRAM; T5-XXL text encoder alone needs ~9.5 GB
        conn = get_conn()
        conn.execute("UPDATE videos SET status='generating',error=NULL,progress=1,progress_msg='Starting…',updated_at=datetime('now') WHERE id=?", (vid_id,))
        conn.commit()

        seed = row["seed"] if row["seed"] else random.randint(1, 2**31 - 1)
        out_path = VIDEOS_DIR / f"vid_{vid_id}_{int(datetime.now().timestamp())}.mp4"
        try:
            result = _run_gen(
                [str(VIDEO_GEN_SCRIPT), row["prompt"], str(out_path),
                 str(row["width"] or 832), str(row["height"] or 480),
                 str(row["num_frames"] or 49), str(row["steps"] or 20),
                 str(seed), str(row["fps"] or 16), model_id],
                timeout=_video_timeout(model_id), vid_id=vid_id,
                on_progress=lambda p, m: _set_video_progress(vid_id, p, m),
                steps=int(row["steps"] or 20),
            )
            if result.returncode == 0 and out_path.exists():
                conn.execute(
                    "UPDATE videos SET status='done',video_path=?,seed=?,error=NULL,progress=100,progress_msg='Done',updated_at=datetime('now') WHERE id=?",
                    (str(out_path), seed, vid_id),
                )
                logger.info("Video %d done: %s", vid_id, out_path)
            else:
                err = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()[-800:] or "unknown error"
                logger.error("Video %d failed (rc=%d): %s", vid_id, result.returncode, err)
                conn.execute("UPDATE videos SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",
                             (err, vid_id))
        except subprocess.TimeoutExpired:
            logger.error("Video %d timed out", vid_id)
            conn.execute("UPDATE videos SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",
                         (f"Timed out after {_video_timeout(model_id)//60} min — try fewer frames/steps or a lighter model.", vid_id))
        except Exception as ex:
            logger.error("Video %d exception: %s", vid_id, ex)
            conn.execute("UPDATE videos SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",
                         (str(ex)[:800], vid_id))
        finally:
            conn.commit()
            conn.close()
            orch.video_release()

# ─── Audio (music + voice) on the node + video→audio bridge ──────────────────
_SCP = ["scp", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def audio_models_dir() -> str:
    """Node-side directory the audio models live in. The live `models_dir_audio`
    setting (Settings → 🧠 Models → 📁 Storage) wins; falls back to the
    STORE_AUDIO_MODELS_DIR / STORE_HF_AUDIO env values. Empty = the node's default
    HF cache. Sets HF_HOME so MusicGen/MMS/Stable-Audio cache there; ACE-Step
    uses <dir>/ace-step."""
    try:
        import model_paths
        return model_paths.primary("audio")
    except Exception:
        return (os.environ.get("STORE_AUDIO_MODELS_DIR") or "").strip().rstrip("/")


def _audio_env(engine: str = "") -> str:
    parts = ["HF_HUB_OFFLINE=0", "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"]
    d = audio_models_dir()
    if d:
        parts.append(f"HF_HOME={d}")
        if engine == "acestep":
            parts.append(f"STORE_ACE_STORAGE={d}/ace-step")
    return " ".join(parts)


def _node_audio(mode: str, prompt: str, out_wav_local: str, duration: int = 8,
                model_id: str = "", seed: int = 0, engine: str = "", lyrics: str = "",
                timeout: int = 1200):
    """Run store_audiogen.py on the GPU node (music|voice) and copy the wav back.
    Caller must hold the GPU (orch.video_acquire) — audio needs the VRAM the LLM uses."""
    tgt = f"{GPU_SSH_USER}@{GPU_HOST}"
    ts = int(datetime.now().timestamp())
    r_args = f"/tmp/store_aud_args_{ts}.json"
    r_wav  = f"/tmp/store_aud_out_{ts}.wav"
    args = {"mode": mode, "prompt": prompt, "output": r_wav}
    if mode == "music":
        args["duration"] = duration
    if model_id:
        args["model_id"] = model_id
    if engine:
        args["engine"] = engine
    if lyrics:
        args["lyrics"] = lyrics
    if seed:
        args["seed"] = seed
    l_args = Path(VIDEOS_DIR) / f".aud_args_{ts}.json"
    l_args.write_text(json.dumps(args))
    try:
        subprocess.run(_SCP + [str(l_args), f"{tgt}:{r_args}"], check=True, capture_output=True, timeout=30)
        # ACE-Step runs in its own venv from its repo dir (import needs cwd=~/ACE-Step);
        # everything else uses the ComfyUI venv. Models cache under STORE_AUDIO_MODELS_DIR.
        env = _audio_env(engine)
        if engine == "acestep":
            cmd = f"cd ~/ACE-Step && {env} ~/ace-venv/venv/bin/python3 ~/store_audiogen.py {r_args}"
        else:
            cmd = f"{env} ~/ComfyUI/venv/bin/python3 ~/store_audiogen.py {r_args}"
        r = subprocess.run(BOX_SSH + [cmd], capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "audio generation failed").strip()[-500:])
        cp = subprocess.run(_SCP + [f"{tgt}:{r_wav}", str(out_wav_local)], capture_output=True, text=True, timeout=90)
        if cp.returncode != 0 or not Path(out_wav_local).exists():
            raise RuntimeError("generated audio but couldn't copy it back from the node")
    finally:
        try: l_args.unlink(missing_ok=True)
        except Exception: pass
        subprocess.run(BOX_SSH + [f"rm -f {r_args} {r_wav}"], capture_output=True, timeout=15)
    return out_wav_local


def _video_duration(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=20)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _mux_audio(video: str, music: str, voice: str, out: str):
    """Mux background music (looped/trimmed, quiet) + optional voice (front, full) onto
    a silent video with ffmpeg. Output length = the video's length."""
    dur = _video_duration(video) or 5.0
    inputs = ["-i", video, "-stream_loop", "-1", "-i", music]
    if voice:
        inputs += ["-i", voice]
        fc = ("[1:a]volume=0.28[bg];[2:a]volume=1.0[vo];"
              "[bg][vo]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        fc = "[1:a]volume=0.6[a]"
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", fc, "-map", "0:v", "-map", "[a]",
            "-t", f"{dur:.2f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out])
    subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    return out


def add_video_audio(vid_id: int, music_prompt: str, narration: str = ""):
    """Background task: generate music (+ optional narration voice) for a video and mux
    it on. Sets videos.audio_path / audio_status / audio_error."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM videos WHERE id=?", (vid_id,)).fetchone()
    conn.close()
    if not row or not row["video_path"] or not Path(row["video_path"]).exists():
        _set_audio(vid_id, "failed", err="Video file not found")
        return
    video = row["video_path"]
    _set_audio(vid_id, "generating")
    ok, msg = _video_preflight()
    if not ok:
        _set_audio(vid_id, "failed", err=msg)
        return
    ts = int(datetime.now().timestamp())
    music_wav = str(VIDEOS_DIR / f"aud_{vid_id}_music_{ts}.wav")
    voice_wav = ""
    with _VIDEO_RUN_LOCK:
        orch.video_acquire()
        try:
            dur = max(4, int(_video_duration(video)) + 1)
            _set_video_progress(vid_id, 15, "Composing music…")
            _node_audio("music", music_prompt or (row["prompt"] or "gentle background music"),
                        music_wav, duration=dur)
            if narration.strip():
                voice_wav = str(VIDEOS_DIR / f"aud_{vid_id}_voice_{ts}.wav")
                _set_video_progress(vid_id, 55, "Recording narration…")
                _node_audio("voice", narration.strip(), voice_wav)
            _set_video_progress(vid_id, 85, "Mixing audio into video…")
            out = str(VIDEOS_DIR / f"vid_{vid_id}_sound_{ts}.mp4")
            _mux_audio(video, music_wav, voice_wav, out)
            _set_audio(vid_id, "done", path=out)
            _set_video_progress(vid_id, 100, "Done")
            logger.info("Video %d sounded: %s", vid_id, out)
        except subprocess.TimeoutExpired:
            _set_audio(vid_id, "failed", err="Audio generation timed out")
        except Exception as ex:
            logger.error("Video %d add-audio failed: %s", vid_id, ex)
            _set_audio(vid_id, "failed", err=str(ex)[:500])
        finally:
            for w in (music_wav, voice_wav):
                try:
                    if w: Path(w).unlink(missing_ok=True)
                except Exception:
                    pass
            orch.video_release()


# Standalone audio engines exposed in the Music/Audio tab. (mode, default model)
AUDIO_ENGINES = {
    "musicgen":     {"kind": "music", "model": "facebook/musicgen-small",  "label": "MusicGen (instrumental, fast)"},
    "musicgen_med": {"kind": "music", "model": "facebook/musicgen-medium", "label": "MusicGen Medium (richer)"},
    "acestep":      {"kind": "music", "model": "ACE-Step/ACE-Step-v1-3.5B", "label": "ACE-Step (songs w/ vocals+lyrics)"},
    "stable_audio": {"kind": "music", "model": "stabilityai/stable-audio-open-1.0", "label": "Stable Audio Open (hi-fi)"},
    "mms_tts":      {"kind": "voice", "model": "facebook/mms-tts-eng",      "label": "Voice narration (MMS-TTS)"},
}


def run_audio_clip(clip_id: int):
    """Background task: generate a standalone music/voice clip on the node."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM audio_clips WHERE id=?", (clip_id,)).fetchone()
    conn.close()
    if not row:
        return
    row = dict(row)
    eng = AUDIO_ENGINES.get(row["engine"] or "musicgen", AUDIO_ENGINES["musicgen"])
    mode = "voice" if eng["kind"] == "voice" else "music"
    model_id = row["model_id"] or eng["model"]

    ok, msg = _video_preflight()
    if not ok:
        _set_clip(clip_id, "failed", err=msg)
        return
    _set_clip(clip_id, "generating", pmsg="Loading model…")
    ts = int(datetime.now().timestamp())
    out = str(VIDEOS_DIR / f"clip_{clip_id}_{ts}.wav")
    with _VIDEO_RUN_LOCK:
        orch.video_acquire()
        try:
            _node_audio(mode, row["prompt"], out, duration=int(row["duration"] or 8),
                        model_id=model_id, engine=row["engine"],
                        lyrics=(row["lyrics"] if "lyrics" in row.keys() else "") or "")
            _set_clip(clip_id, "done", path=out, pmsg="Done")
            logger.info("Audio clip %d done: %s", clip_id, out)
        except subprocess.TimeoutExpired:
            _set_clip(clip_id, "failed", err="Generation timed out")
        except Exception as ex:
            logger.error("Audio clip %d failed: %s", clip_id, ex)
            _set_clip(clip_id, "failed", err=str(ex)[:500])
        finally:
            orch.video_release()


def _set_clip(clip_id: int, status: str, path: str = None, err: str = None, pmsg: str = None):
    try:
        conn = get_conn()
        conn.execute("UPDATE audio_clips SET status=?, audio_path=COALESCE(?,audio_path), "
                     "error=?, progress_msg=COALESCE(?,progress_msg), updated_at=datetime('now') WHERE id=?",
                     (status, path, err, pmsg, clip_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _set_audio(vid_id: int, status: str, path: str = None, err: str = None):
    try:
        conn = get_conn()
        conn.execute("UPDATE videos SET audio_status=?, audio_path=COALESCE(?,audio_path), "
                     "audio_error=?, updated_at=datetime('now') WHERE id=?",
                     (status, path, err, vid_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


# Export everything (incl. single-underscore helpers used across modules).
__all__ = [n for n in dir() if not n.startswith('__')]
