"""Model STORAGE locations — settings-first, env fallback, multi-location aware.

One place answers "where do models of this kind live / get downloaded to?".
Resolution order per kind: the `models_dir_<kind>` setting (live-editable in
Settings → 🧠 Models → 📁 Storage) → the STORE_* env var / config default.

A value may hold SEVERAL paths (one per line, or comma-separated): the FIRST
is the primary — where new downloads land and what HF_HOME points at — and
the rest are additional locations future listers may scan. Paths are on the
GPU node for every kind (they're used inside ssh commands), so no local
existence checks here.

LLM is special: LM Studio owns its own models folder (set on the node in
LM Studio → My Models). The setting is recorded so the store knows the
layout, but changing it here does not move LM Studio's folder.
"""
import config as _cfg


def _env_default(kind):
    return {
        "image": _cfg.COMFY_CKPT,
        "llm":   getattr(_cfg, "NODE_LLM_DIR", "") or "",
        # audio keeps its historical semantics: EMPTY means "use the node's default
        # HF cache" (fresh installs without the SSD stay safe) — no NODE_HF_AUDIO chain
        "audio": __import__("os").environ.get("STORE_AUDIO_MODELS_DIR", "").strip(),
        "video": _cfg.NODE_HF_VIDEO,
        "3d":    _cfg.NODE_HF_3D,
    }.get(kind, "")


KINDS = {
    "image": {"label": "Image checkpoints (ComfyUI)", "env": "STORE_COMFY_CKPT",
              "note": "Where SDXL/Flux checkpoints download to on the GPU node. LoRAs/upscalers "
                      "keep their own ComfyUI subfolders; for a fully relocated ComfyUI models "
                      "tree also use ComfyUI's extra_model_paths.yaml."},
    "llm":   {"label": "LLM models (LM Studio)", "env": "STORE_NODE_LLM_DIR",
              "note": "Informational — LM Studio owns this folder. Change it on the node in "
                      "LM Studio → My Models, then record the same path here."},
    "audio": {"label": "Audio models (HF cache)", "env": "STORE_AUDIO_MODELS_DIR",
              "note": "HF_HOME for MusicGen / MMS / Stable Audio; ACE-Step caches under "
                      "<dir>/ace-step. Empty = the node's default ~/.cache/huggingface."},
    "video": {"label": "Video models (HF cache)", "env": "STORE_HF_VIDEO",
              "note": "HF_HOME for the video pipelines (Wan/LTX etc.)."},
    "3d":    {"label": "3D models (HF cache)", "env": "STORE_HF_3D",
              "note": "HF_HOME for TripoSR and friends."},
}


def dirs(kind):
    """All configured paths for a kind (setting first, env/config fallback).
    Always returns a list; may be [''] when genuinely unset (audio/llm)."""
    from deps import get_setting
    raw = (get_setting(f"models_dir_{kind}", "") or "").strip()
    if not raw:
        raw = _env_default(kind)
    parts = [p.strip().rstrip("/") for chunk in raw.split("\n") for p in chunk.split(",")]
    return [p for p in parts if p] or [""]


def primary(kind):
    """The active path — downloads land here; HF_HOME points here."""
    return dirs(kind)[0]


def snapshot():
    """Everything the Settings UI needs: per kind, the stored setting value,
    the effective primary, extra locations, and the env-default it falls back to."""
    from deps import get_setting
    out = []
    for kind, meta in KINDS.items():
        ds = dirs(kind)
        out.append({"kind": kind, "label": meta["label"], "note": meta["note"],
                    "env": meta["env"], "setting": f"models_dir_{kind}",
                    "value": get_setting(f"models_dir_{kind}", "") or "",
                    "effective": ds[0], "extra": ds[1:], "default": _env_default(kind)})
    return out
