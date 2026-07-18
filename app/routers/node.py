"""GPU node deploy + health. Drives deploy/node/node-setup.sh over SSH so the user
can provision / check the whole node (image, video, 3d, audio, LM Studio, services)
from the Store UI — with a live log and an OS gate that requires Ubuntu."""
from fastapi import APIRouter, HTTPException
from deps import *
import subprocess, re as _re, json as _json

router = APIRouter()

_BUNDLE   = BASE / "deploy" / "node"
_REMOTE   = ".store-node-deploy"
_LOGFILE  = "store-node-deploy.log"
_ANSI     = _re.compile(r"\x1b\[[0-9;]*m")


def _target():
    return f"{GPU_SSH_USER}@{GPU_HOST}"


def _ssh(cmd: str, timeout: int = 25):
    """Run a single shell command string on the node (via the configured BOX_SSH)."""
    return subprocess.run(BOX_SSH + [cmd], capture_output=True, text=True, timeout=timeout)


def _scp(sources: list, dest: str, timeout: int = 60):
    base = ["scp", "-r", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15"]
    return subprocess.run(base + sources + [f"{_target()}:{dest}"],
                          capture_output=True, text=True, timeout=timeout)


_STATUS_SNIPPET = r'''
OS_ID=""; [ -r /etc/os-release ] && . /etc/os-release && OS_ID="${ID:-}"
OSP="${PRETTY_NAME:-$(uname -s)}"
case "$OS_ID" in ubuntu|debian|pop|linuxmint|neon) OK=true;; *) OK=false;; esac
gpu=missing;  command -v nvidia-smi >/dev/null 2>&1 && gpu=ok
comfy=missing; [ -f "$HOME/ComfyUI/main.py" ] && [ -x "$HOME/ComfyUI/venv/bin/python3" ] && comfy=ok
video=missing; [ -f "$HOME/store_videogen.py" ] && "$HOME/ComfyUI/venv/bin/python3" -c "import diffusers" >/dev/null 2>&1 && video=ok
d3=missing;   [ -f "$HOME/TripoSR/run.py" ] && d3=ok
audio=missing; [ -f "$HOME/store_audiogen.py" ] && "$HOME/ComfyUI/venv/bin/python3" -c "from transformers import MusicgenForConditionalGeneration, VitsModel; import scipy" >/dev/null 2>&1 && audio=ok
lms=missing;  [ -x "$HOME/.lmstudio/bin/lms" ] && lms=ok
svc=missing;  systemctl --user is-enabled lmstudio.service >/dev/null 2>&1 && svc=ok
llm=down; curl -s -m3 http://localhost:1234/v1/models >/dev/null 2>&1 && llm=up
comfyup=down; curl -s -m3 http://localhost:8188/system_stats >/dev/null 2>&1 && comfyup=up
echo "[NODE-STATUS] {\"os\":\"$OSP\",\"os_id\":\"$OS_ID\",\"os_ok\":$OK,\"gpu\":\"$gpu\",\"comfyui\":\"$comfy\",\"video\":\"$video\",\"model3d\":\"$d3\",\"audio\":\"$audio\",\"lmstudio\":\"$lms\",\"services\":\"$svc\",\"llm_server\":\"$llm\",\"comfy_server\":\"$comfyup\"}"
'''


@router.get("/api/node/status")
def node_status():
    """Detect the node OS and each component. Handles unreachable + non-Ubuntu
    (e.g. a Windows box) with a clear os_ok=false so the UI can prompt for Ubuntu."""
    host = GPU_HOST
    # First: is it even Linux? (Windows SSH has no `uname`/bash → caught here.)
    try:
        u = _ssh("uname -s", timeout=15)
    except subprocess.TimeoutExpired:
        return {"reachable": False, "os_ok": False, "gpu_host": host,
                "error": f"GPU node {host} did not respond within 15s (box off / network down?)."}
    except Exception as e:
        return {"reachable": False, "os_ok": False, "gpu_host": host, "error": str(e)}
    if u.returncode != 0 or "Linux" not in (u.stdout or ""):
        # reachable but not Linux (or no shell) — almost certainly Windows/macOS
        guess = (u.stdout or u.stderr or "").strip()[:60] or "not Linux"
        return {"reachable": True, "os_ok": False, "gpu_host": host, "os": guess,
                "needs_ubuntu": True,
                "note": ("This GPU node is not running Linux. The Store node must be "
                         "Ubuntu (24.04 recommended) — Windows/macOS can't autostart the "
                         "CUDA services (ComfyUI, diffusers, LM Studio headless) the node needs.")}
    # Linux — gather the component status (bash reads the snippet from stdin)
    try:
        r = subprocess.run(BOX_SSH + ["bash -s"], input=_STATUS_SNIPPET,
                           capture_output=True, text=True, timeout=30)
    except Exception as e:
        return {"reachable": True, "os_ok": True, "gpu_host": host,
                "error": f"status check failed: {e}"}
    m = _re.search(r"\[NODE-STATUS\]\s*(\{.*\})", r.stdout or "")
    if not m:
        return {"reachable": True, "os_ok": True, "gpu_host": host,
                "error": "could not read node status", "raw": (r.stdout or r.stderr)[:400]}
    data = _json.loads(m.group(1))
    data["reachable"] = True
    data["gpu_host"] = host
    if not data.get("os_ok"):
        data["needs_ubuntu"] = True
    return data


@router.post("/api/node/deploy")
def node_deploy(body: dict = None):
    """Push the deploy bundle and run node-setup.sh on the node (background).
    Gates on OS: refuses (needs_ubuntu) if the node isn't Ubuntu-like."""
    with_audio = bool((body or {}).get("with_audio"))
    st = node_status()
    if not st.get("reachable"):
        raise HTTPException(502, st.get("error") or "GPU node unreachable over SSH")
    if not st.get("os_ok"):
        return {"needs_ubuntu": True, "os": st.get("os"), "note": st.get("note")}
    if not _BUNDLE.exists():
        raise HTTPException(500, f"deploy bundle missing at {_BUNDLE}")
    # stage the bundle
    _ssh(f"rm -rf ~/{_REMOTE} && mkdir -p ~/{_REMOTE}/services", timeout=20)
    files = [str(_BUNDLE / "node-setup.sh"), str(_BUNDLE / "store_videogen.py"),
             str(_BUNDLE / "store_audiogen.py")]
    up = _scp(files, f"~/{_REMOTE}/")
    if up.returncode != 0:
        raise HTTPException(502, f"failed to copy deploy files: {(up.stderr or '')[:200]}")
    _scp([str(p) for p in (_BUNDLE / "services").glob("*.service")], f"~/{_REMOTE}/services/")
    # 3D model helper scripts + the TripoSR CPU-mesh patch (setup_3d installs these).
    if (_BUNDLE / "model3d").exists():
        _scp([str(_BUNDLE / "model3d")], f"~/{_REMOTE}/")
    # launch in the background on the node; ssh returns immediately
    flag = "--with-audio" if with_audio else ""
    launch = (f"cd ~/{_REMOTE} && chmod +x node-setup.sh && "
              f": > ~/{_LOGFILE} && "
              f"nohup bash node-setup.sh deploy {flag} > ~/{_LOGFILE} 2>&1 </dev/null & echo LAUNCHED")
    r = _ssh(launch, timeout=30)
    if "LAUNCHED" not in (r.stdout or ""):
        raise HTTPException(502, f"could not start deploy: {(r.stderr or r.stdout or '')[:200]}")
    return {"ok": True, "started": True, "with_audio": with_audio}


@router.get("/api/node/deploy-log")
def node_deploy_log():
    """Tail the deploy log + whether it's still running."""
    try:
        # '[n]ode-setup' bracket trick stops pgrep from matching its own command line.
        r = _ssh(f"tail -c 40000 ~/{_LOGFILE} 2>/dev/null; echo; "
                 f"pgrep -f '[n]ode-setup.sh deploy' >/dev/null && echo __RUNNING__ || echo __IDLE__",
                 timeout=20)
    except Exception as e:
        return {"log": "", "running": False, "done": False, "error": str(e)}
    out = _ANSI.sub("", r.stdout or "")
    running = out.rstrip().endswith("__RUNNING__")
    log = out.replace("__RUNNING__", "").replace("__IDLE__", "").rstrip()
    result = None
    mr = _re.search(r"\[DEPLOY-RESULT\]\s*(\{.*\})", log)
    if mr:
        try:
            result = _json.loads(mr.group(1))
        except Exception:
            pass
    return {"log": log, "running": running, "done": (not running and result is not None),
            "result": result}
