"""Video-chain pipeline: generate multi-segment video chains sequentially (T2V for
segment 0, V2V continuation after), resume a partially-done chain, and xfade-compile
the segments. Split out of services_media.py for size; re-exported by it
(from services_media_chain import *)."""
from deps import *


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

def chain_resume_point(chain_id: int) -> tuple[int, str | None]:
    """Where a partially-completed chain should pick back up: (start_idx, prev_path).
    start_idx is the first segment NOT done; prev_path is the last done segment's
    video for V2V continuity (None when resuming from segment 0)."""
    conn = get_conn()
    last = conn.execute(
        "SELECT chain_index, video_path FROM videos "
        "WHERE chain_id=? AND status='done' AND video_path IS NOT NULL "
        "ORDER BY chain_index DESC LIMIT 1", (chain_id,)).fetchone()
    conn.close()
    if not last:
        return 0, None
    return int(last["chain_index"]) + 1, last["video_path"]


def resume_chain_generation(chain_id: int):
    """Continue a failed/interrupted chain from its last completed segment instead
    of starting over (used by the gpu-guard after a game/heavy-app pause killed the
    in-flight segment). Done segments are kept; the killed segment's row is removed
    so the redo doesn't leave a dangling 'failed' card in the gallery."""
    start_idx, prev_path = chain_resume_point(chain_id)
    conn = get_conn()
    conn.execute("DELETE FROM videos WHERE chain_id=? AND status IN ('failed','generating')",
                 (chain_id,))
    # completed_segments tracks reality (rows may have been pruned/failed oddly)
    conn.execute("UPDATE video_chains SET completed_segments=?,updated_at=datetime('now') "
                 "WHERE id=?", (start_idx, chain_id))
    conn.commit()
    conn.close()
    logger.info("Chain %d resuming at segment %d (prev=%s)", chain_id, start_idx, prev_path)
    run_chain_generation(chain_id, _start_idx=start_idx, _prev_video_path=prev_path)


def run_chain_generation(chain_id: int, _start_idx: int = 0,
                         _prev_video_path: str | None = None):
    """Background task: generate all segments of a video chain sequentially.
    `_start_idx`/`_prev_video_path` are for resume_chain_generation — segments
    below _start_idx are skipped and the first generated one continues (V2V)
    from _prev_video_path instead of a fresh T2V."""
    # Video-infra helpers live in services_media; import lazily to avoid an import cycle.
    from services_media import _video_preflight, _video_timeout, _run_gen, _set_video_progress
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
    prev_video_path: str | None = _prev_video_path
    segment_video_ids: list[int] = []

    for idx, prompt in enumerate(prompts):
        if idx < _start_idx:
            continue   # resume: this segment already completed before the interrupt
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


# Export everything (incl. single-underscore helpers used across modules).
__all__ = [n for n in dir() if not n.startswith('__')]
