"""GPU-node SSH / model-load helpers for the orchestrator.

Split out of orchestrator.py VERBATIM (SSH transport + LM Studio model-load/VRAM
helpers). Re-exported from orchestrator so its public surface is unchanged. Kept
self-contained (derives BOX/LMS from config independently) so there is no import
cycle with orchestrator.
"""
import subprocess

try:
    from config import GPU_SSH_USER, GPU_HOST
    BOX = f"{GPU_SSH_USER}@{GPU_HOST}"
except Exception:
    BOX = "user@127.0.0.1"
LMS = "~/.lmstudio/bin/lms"


def _loaded_llms() -> list:
    """Identifiers of LLMs currently loaded in LM Studio (via `lms ps --json`)."""
    import json as _json
    rc, out = _ssh(LMS, "ps", "--json", timeout=10)
    if rc != 0 or not out:
        return []
    try:
        data = _json.loads(out)
        # identifier FIRST — aliases like `model@cpu` are addressed by identifier,
        # and chat routing must match what the API actually serves under.
        return [m.get("identifier") or m.get("modelKey")
                for m in data if m.get("type") == "llm" and (m.get("identifier") or m.get("modelKey"))]
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


def _model_cfg_of(model: str) -> dict:
    try:
        import json as _json
        from deps import get_setting
        return (_json.loads(get_setting("llm_model_cfg", "{}") or "{}")).get(model) or {}
    except Exception:
        return {}


def _load_args(model: str) -> list:
    """`lms load` argv: idle TTL + per-model LOAD-TIME settings from the
    llm_model_cfg registry — context_length, gpu ratio, parallel prompt slots,
    and a per-model ttl. MULTI-MODEL: an id ending in `@cpu` loads the SAME
    underlying model as a second CPU-placed instance under that alias
    (`--identifier` — the supported version of the copy-and-rename trick), so a
    full-speed GPU model and CPU side-models can serve at the same time."""
    ttl = _idle_ttl()
    alias = None
    real = model
    if model.endswith("@cpu"):
        alias, real = model, model[:-4]
    args = ["load", real]
    cfg = _model_cfg_of(model)
    if alias:
        args += ["--identifier", alias, "--gpu", "off"]
    elif cfg.get("gpu") not in (None, ""):
        args += ["--gpu", str(cfg["gpu"])]
    if cfg.get("context_length"):
        args += ["--context-length", str(int(cfg["context_length"]))]
    if cfg.get("parallel"):
        args += ["--parallel", str(int(cfg["parallel"]))]
    if cfg.get("ttl"):
        ttl = int(cfg["ttl"])
    return args + (["--ttl", str(ttl)] if ttl > 0 else [])


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
