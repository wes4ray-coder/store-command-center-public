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

While the God-Console toggle "Company skilling boosts mining" is on, the Company agents'
woodcutting/mining/fishing queues up boost tickets — they pay out **inside your mined
blocks** (bonus JLY split agent/company). No GPU online → no boosts, ever.
