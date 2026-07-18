#!/usr/bin/env python3
"""
store_audiogen.py — music + voice on the GPU node via HuggingFace transformers.
Invoked on-demand (like store_videogen.py); prints [audiogen] progress markers the
store parses. Runs in ~/ComfyUI/venv (transformers + torch + scipy already present).

Usage: python3 store_audiogen.py <args_json_file>
Args JSON keys:
  mode      : "music" (default) | "voice"
  prompt    : text prompt (music description) or the words to speak (voice)
  output    : path to write (.wav)
  duration  : seconds of music (music mode, default 8)
  model_id  : music -> facebook/musicgen-small|-medium ; voice -> suno/bark-small|suno/bark
  voice     : Bark voice preset for voice mode (default v2/en_speaker_6)
  seed      : optional int
"""
import sys, json, os, time


def _write_wav(path, rate, data):
    import numpy as np
    from scipy.io.wavfile import write
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    arr = np.asarray(data).squeeze()
    if arr.dtype.kind == "f":
        arr = np.clip(arr, -1.0, 1.0)
        arr = (arr * 32767.0).astype("int16")
    write(path, int(rate), arr)


def gen_music(args):
    import torch
    from transformers import MusicgenForConditionalGeneration, AutoProcessor
    model_id = args.get("model_id", "facebook/musicgen-small")
    prompt   = args["prompt"]
    output   = args["output"]
    duration = float(args.get("duration", 8))

    print(f"[audiogen] Loading music model {model_id}…", flush=True)
    t0 = time.time()
    proc  = AutoProcessor.from_pretrained(model_id)
    model = MusicgenForConditionalGeneration.from_pretrained(model_id)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev)
    print(f"[audiogen] Loaded in {time.time()-t0:.1f}s", flush=True)

    if args.get("seed"):
        torch.manual_seed(int(args["seed"]))
    # MusicGen produces ~50 audio tokens per second.
    max_new = max(64, int(duration * 51.2))
    inputs = proc(text=[prompt], padding=True, return_tensors="pt").to(dev)
    print(f"[audiogen] Generating {duration:.0f}s of music…", flush=True)
    with torch.no_grad():
        audio = model.generate(**inputs, do_sample=True, guidance_scale=3.0, max_new_tokens=max_new)
    rate = model.config.audio_encoder.sampling_rate
    _write_wav(output, rate, audio[0, 0].cpu().numpy())
    print(f"[audiogen] DONE: {output} ({time.time()-t0:.1f}s total)", flush=True)


def gen_voice(args):
    # MMS-TTS (VITS): single safetensors model, no speaker embedding, works on torch 2.5.
    import torch
    from transformers import VitsModel, AutoTokenizer
    model_id = args.get("model_id", "facebook/mms-tts-eng")
    prompt   = args["prompt"]
    output   = args["output"]

    print(f"[audiogen] Loading voice model {model_id}…", flush=True)
    t0 = time.time()
    tok   = AutoTokenizer.from_pretrained(model_id)
    model = VitsModel.from_pretrained(model_id)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev)
    print(f"[audiogen] Loaded in {time.time()-t0:.1f}s", flush=True)

    if args.get("seed"):
        torch.manual_seed(int(args["seed"]))
    inputs = tok(prompt, return_tensors="pt").to(dev)
    print("[audiogen] Generating voice…", flush=True)
    with torch.no_grad():
        out = model(**inputs).waveform
    rate = model.config.sampling_rate
    _write_wav(output, rate, out[0].cpu().numpy())
    print(f"[audiogen] DONE: {output} ({time.time()-t0:.1f}s total)", flush=True)


def gen_stable_audio(args):
    """Stable Audio Open (hi-fi instrumental) via diffusers StableAudioPipeline.
    The model is gated on HF — needs a token with the license accepted (HF_TOKEN)."""
    import torch
    from diffusers import StableAudioPipeline
    model_id = args.get("model_id", "stabilityai/stable-audio-open-1.0")
    prompt   = args["prompt"]
    output   = args["output"]
    duration = float(args.get("duration", 8))

    print(f"[audiogen] Loading {model_id}…", flush=True)
    t0 = time.time()
    pipe = StableAudioPipeline.from_pretrained(model_id, torch_dtype=torch.float16)
    pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[audiogen] Loaded in {time.time()-t0:.1f}s", flush=True)
    gen = None
    if args.get("seed"):
        gen = torch.Generator("cuda").manual_seed(int(args["seed"]))
    print(f"[audiogen] Generating {duration:.0f}s (Stable Audio)…", flush=True)
    audio = pipe(prompt, negative_prompt="low quality", num_inference_steps=100,
                 audio_end_in_s=duration, num_waveforms_per_prompt=1, generator=gen).audios
    rate = pipe.vae.sampling_rate
    _write_wav(output, rate, audio[0].T.float().cpu().numpy())
    print(f"[audiogen] DONE: {output} ({time.time()-t0:.1f}s total)", flush=True)


def gen_acestep(args):
    """ACE-Step — full songs with vocals + lyrics. Run with cwd=~/ACE-Step in its own
    venv. 'prompt' = style/genre tags; 'lyrics' (optional) = words to sing ([inst]=none).
    Checkpoints auto-download to persistent_storage_path on first run (~8 GB)."""
    # The acestep editable install doesn't resolve when running this script by path
    # (sys.path[0] is the script dir, not ~/ACE-Step) — add the repo dir explicitly.
    ace_repo = os.environ.get("STORE_ACE_REPO") or os.path.expanduser("~/ACE-Step")
    if ace_repo not in sys.path:
        sys.path.insert(0, ace_repo)
    from acestep.pipeline_ace_step import ACEStepPipeline
    output   = args["output"]
    tags     = args["prompt"]
    lyrics   = args.get("lyrics", "") or "[inst]"
    duration = float(args.get("duration", 30))

    print("[audiogen] Loading ACE-Step (first run downloads the model, ~8 GB)…", flush=True)
    t0 = time.time()
    # Store checkpoints under ~/.cache/ace-step (symlinked to the SSD on this node);
    # override with STORE_ACE_STORAGE. checkpoint_dir becomes <storage>/checkpoints.
    storage = os.environ.get("STORE_ACE_STORAGE") or os.path.expanduser("~/.cache/ace-step")
    pipe = ACEStepPipeline(checkpoint_dir=None, dtype="bfloat16", torch_compile=False,
                           cpu_offload=True, persistent_storage_path=storage)
    print(f"[audiogen] Loaded in {time.time()-t0:.1f}s", flush=True)
    print(f"[audiogen] Generating {duration:.0f}s (ACE-Step, vocals+lyrics)…", flush=True)
    seeds = [int(args["seed"])] if args.get("seed") else None
    pipe(format="wav", audio_duration=duration, prompt=tags, lyrics=lyrics,
         infer_step=int(args.get("infer_step", 27)), guidance_scale=15.0,
         manual_seeds=seeds, save_path=output)
    print(f"[audiogen] DONE: {output} ({time.time()-t0:.1f}s total)", flush=True)


def main():
    if len(sys.argv) < 2:
        print("Usage: store_audiogen.py <args_json_file>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        args = json.load(f)
    engine = args.get("engine", "")
    if args.get("mode") == "voice" or engine == "mms_tts":
        gen_voice(args)
    elif engine == "stable_audio":
        gen_stable_audio(args)
    elif engine == "acestep":
        gen_acestep(args)
    else:
        gen_music(args)


if __name__ == "__main__":
    main()
