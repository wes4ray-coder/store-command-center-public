# JellyMiner — mine JellyCoin (JLY) with any GPU, especially old ones

JellyCoin is the Store's own token. New JLY exists **only** when a real GPU solves a
proof-of-work block — the server never mines, and there is deliberately **no CPU mining**.
The kernel is plain OpenCL 1.1, so cards far too old for AI (GTX 400/600-era, old Radeons)
work fine alongside modern ones.

## Setup on any LAN box with a GPU

```bash
pip install pyopencl numpy requests
# OpenCL driver, if `python3 jellyminer.py --list` shows nothing:
#   NVIDIA: the proprietary/legacy driver ships OpenCL (even the 390/470 legacy branches)
#   AMD:    mesa's rusticl (`sudo apt install mesa-opencl-icd`) or amdgpu
#   Intel:  `sudo apt install intel-opencl-icd`
# `clinfo` is the debugging tool of choice.

python3 jellyminer.py --list                    # pick your card
python3 jellyminer.py --url http://127.0.0.1:8787 --token <TOKEN> --name rig1
```

Get `<TOKEN>` (and this script itself) from the Store UI: **Crypto → 🪼 JellyCoin → Mining**.
Rewards land in the wallet `miner:<name>`. Difficulty auto-retargets toward one block/min.

## Run as a service (survives reboots)

The GPU node already runs this way (`~/.config/systemd/user/jellyminer.service`, user has
linger enabled). Recipe for any rig:

```ini
# ~/.config/systemd/user/jellyminer.service
[Unit]
Description=JellyMiner — JellyCoin GPU miner
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=%h/jellyminer-venv/bin/python %h/jellyminer.py --url http://127.0.0.1:8787 --token <TOKEN> --name <rig> --throttle 50
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
```

`systemctl --user daemon-reload && systemctl --user enable --now jellyminer` (plus
`loginctl enable-linger` once, so it starts at boot without a login). Stop/start:
`systemctl --user stop|start jellyminer`; logs: `journalctl --user -u jellyminer -f`.

**Modern GPUs** work too, and fast (an RTX 3060 clears 500+ MH/s). If the card is *also*
your AI box (LM Studio / ComfyUI), add `--throttle 50` so mining idles half the time and
fills the gaps instead of fighting your models for the GPU. The GPU node already has a
ready venv: `~/jellyminer-venv/bin/python jellyminer.py …`.

## JLY is also the buddy-share compute coin

If you've paired Store installs (Settings → Peers), JLY meters the shared AI helper:
a buddy's box doing LLM work for us **earns** their `peer:<name>` wallet JLY from the
treasury; a buddy running jobs on our node **spends** theirs (comped if broke — sharing
never breaks over play money). Buddies check their balance via `/api/peers/rpc/wallet`.
Toggle + price: **Crypto → 🪼 JellyCoin → Buddy compute**.

While the God-Console toggle "Company skilling boosts mining" is on, the Company agents'
woodcutting/mining/fishing queues up boost tickets — they pay out **inside your mined
blocks** (bonus JLY split agent/company). No GPU online → no boosts, ever.
