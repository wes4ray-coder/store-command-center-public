"""Central model registry — one place that names every model-using feature, its
description, and which model it's set to.

Powers Settings → 🧠 Models (pick a model per feature) and lets the unified queue
show which model each job runs. Every text/LLM feature ultimately funnels through
the orchestrator queue (the single GPU authority — see orchestrator.py), including
OpenClaw via the /api/llm proxy, so setting a model here is what the queue loads.

`kind` drives which option list the picker shows:
  llm    → text models on the node's LM Studio      (/api/settings/llm-models)
  vision → same list (a multimodal model)           (/api/settings/llm-models)
  image  → ComfyUI checkpoints                       (/api/models)
  lora   → free text  "file.safetensors:strength"   (no reliable listing)
A blank value means "use my fallback slot" (e.g. security → the global text LLM).
"""
from deps import get_setting, get_conn

REGISTRY = [
    {"key": "enhance_model", "name": "Text LLM — global", "kind": "llm",
     "default": "google/gemma-4-12b-qat",
     "desc": "The default model for every text task — prompt-enhance, listing copy, "
             "haggling, the AI assistant, world cognition — and the fallback for any "
             "feature below that has no model of its own. OpenClaw's local agents also "
             "run through the queue on whatever each job asks for."},
    {"key": "world_vision_model", "name": "Vision — sprite reviewer", "kind": "vision",
     "default": "google/gemma-4-12b-qat",
     "desc": "Multimodal model that looks at generated pixel-art sprites and scores "
             "them (The Company). A resident vision model is preferred; this is the "
             "load-if-needed pick."},
    {"key": "security_model", "name": "Security analyst", "kind": "llm",
     "default": "", "fallback": "enhance_model",
     "desc": "Model the security AI hunt and the world SOC review use to analyse "
             "anomalies (DNS/security events). Blank = use the global Text LLM."},
    {"key": "default_model", "name": "Image — default checkpoint", "kind": "image",
     "default": "dreamshaperXL_lightningDPMSDE.safetensors",
     "desc": "Default ComfyUI checkpoint for image generation. Overridable per "
             "generation from the Studio."},
    {"key": "world_prop_model", "name": "Image — world sprites", "kind": "image",
     "default": "", "fallback": "default_model",
     "desc": "Checkpoint the pixel-art world sprite builder renders with. "
             "Blank = the default image checkpoint above."},
    {"key": "world_prop_lora", "name": "LoRA — world sprites", "kind": "lora",
     "default": "pixel-art-xl.safetensors:0.9",
     "desc": "LoRA applied to sprite generation, format file.safetensors:strength. "
             "Blank = no LoRA."},
]

_BY_KEY = {s["key"]: s for s in REGISTRY}


def effective(slot: dict) -> str:
    """The value a slot resolves to, honouring its fallback slot when blank."""
    val = get_setting(slot["key"], slot.get("default", ""))
    if not val and slot.get("fallback"):
        val = get_setting(slot["fallback"], _BY_KEY.get(slot["fallback"], {}).get("default", ""))
    return val or ""


def resolve(key: str) -> str:
    """The model a feature should actually use for `key` (honours fallback)."""
    s = _BY_KEY.get(key)
    return effective(s) if s else (get_setting(key, "") or "")


def slots() -> list:
    """Registry rows with their effective + raw values, for the Settings UI."""
    out = []
    for s in REGISTRY:
        out.append({**s, "value": effective(s), "raw": get_setting(s["key"], "") or ""})
    return out


def set_model(key: str, value: str):
    """Persist a slot's model. Only known keys are writable."""
    if key not in _BY_KEY:
        raise KeyError(key)
    conn = get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value or "")))
        conn.commit()
    finally:
        conn.close()
