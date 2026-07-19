# Store GPU Node — deploy

Provisions / health-checks the **GPU node** (the machine that runs the models the
Store talks to over SSH): image (ComfyUI), video (diffusers), 3D (TripoSR),
audio/music (MusicGen), the LLM (LM Studio), and the systemd services that autostart
them. Everything is idempotent — re-run any time; it installs only what's missing and
never upgrades already-working packages.

## The node must be Ubuntu

Ubuntu 24.04 (or another Debian/Ubuntu derivative) **with an NVIDIA GPU + driver** is
required. Windows/macOS can't headlessly autostart the CUDA services the way the node
needs. If you point the Store at a non-Ubuntu box, the "GPU Node" panel in
**Settings** will detect it and tell you to switch to Ubuntu — deploy is blocked.

## Two ways to run it

**From the Store UI (recommended):** Settings → **GPU Node** → *Deploy / Update Node*.
The Store pushes this bundle to the node over SSH (uses `STORE_GPU_HOST` /
`STORE_GPU_SSH_USER`), runs it in the background, and streams the log live. Tick
*include audio/music* to also set up MusicGen (large download).

**On the node directly:**
```bash
scp -r deploy/node user@gpu-box:~/store-node-setup
ssh user@gpu-box
cd ~/store-node-setup
./node-setup.sh check                 # report only, change nothing
./node-setup.sh deploy                # install/repair everything (no audio)
./node-setup.sh deploy --with-audio   # + MusicGen audio stack
```

## What it sets up

| Component | What | Autostart service |
|-----------|------|-------------------|
| image     | ComfyUI + venv (SDXL) on :8188 | `comfyui.service` |
| video     | diffusers/torch stack + `store_videogen.py` | (on-demand) |
| 3d        | TripoSR (image → mesh) | (on-demand) |
| audio     | MusicGen + MMS-TTS (transformers, in the ComfyUI venv) + `store_audiogen.py`; ACE-Step songs install to their own `~/ace-venv` | (on-demand) |
| llm       | LM Studio headless server on :1234 (bound `0.0.0.0`) | `lmstudio.service` |
| guard     | `gpu-guard.sh` — heartbeats the Store; pauses the unified AI queue while a Steam game / heavy GPU app runs, unloads models to free VRAM, and starts/stops the miner around AI work | `gpu-guard.service` |
| miner     | JellyMiner (JellyCoin OpenCL miner, `~/jellyminer-venv`) | `jellyminer.service` |

The guard + miner read `~/.config/store-node.env` (`STORE_URL=`, `JELLY_TOKEN=`).
Deploying from the Store UI fills it automatically (the Store passes its LAN URL and
the JellyCoin miner token over SSH). Running `node-setup.sh` by hand without those env
vars installs the guard but skips the miner unit until you add `JELLY_TOKEN=` (get it
from the Store UI: Crypto → JellyCoin → Mining) and re-run deploy. An existing
`jellyminer.service` is never overwritten.

Log: `~/store-node-deploy.log` on the node.

## Notes

- **System packages** (ffmpeg, build tools, …) need `sudo`. Over SSH the deploy only
  uses passwordless sudo — if it isn't set up it prints the exact `apt-get` line to run
  on the node instead of hanging. Most nodes already have these.
- **Models aren't bundled** (they're large): SDXL checkpoints go in
  `~/ComfyUI/models/checkpoints`; video/3D/audio models download from HuggingFace on
  first use.
- **LM Studio** is a GUI app and can't be auto-installed headlessly — install it once
  from <https://lmstudio.ai>, enable the `lms` CLI, then deploy wires up the headless
  autostart service (which fixes the "error dialog on boot" by starting after the
  graphical session with the right display env and binding to the LAN).
- `comfyui.service` is enabled to autostart. Prefer ComfyUI on-demand instead?
  `systemctl --user disable comfyui.service`.
