#!/usr/bin/env python3
"""JellyMiner — GPU proof-of-work miner for JellyCoin (JLY), the Store's own token.

Built to give OLD graphics cards a second life: the kernel is plain OpenCL 1.1 C
(no CUDA, no tensor cores, no minimum compute capability), so a GTX 660, an old
Radeon, or a brand-new card all work. Cards too old for AI can still mine JLY.

CPU MINING IS INTENTIONALLY UNSUPPORTED. This miner only enumerates OpenCL GPU
devices and exits if none are present — that is a design rule of JellyCoin
(GPU-only issuance), not a missing feature. Please don't "fix" it.

Protocol (must match app/jellycoin.py on the Store):
    GET  {url}/api/jelly/mining/work?miner=&gpu=&hashrate=   (X-Jelly-Token)
         → {work_id, header76 (hex, 76 bytes), target (hex, 32 bytes), height}
    message = header76 + nonce(4 bytes BIG-endian)
    valid   when sha256(sha256(message)) read as a big-endian int < target
    POST {url}/api/jelly/mining/submit  {work_id, nonce, miner}

The Store may answer getwork with HTTP 503 + {"pause": true, "retry_after": n}
instead of a job, meaning "stand down" — the AI queue owns the GPU, or we are
outside the hours the owner set. We sleep and re-poll with a modest backoff
rather than fight LM Studio/ComfyUI for VRAM. Submits are never held, so a nonce
found just before a pause is still banked.

A 200 may also carry {"policy": {"throttle": 90, "batch": 1048576}} — the Store
telling this rig how hard to mine RIGHT NOW. We adopt it between batches, so the
owner can retune intensity from the UI with no restart and no reinstall. The
field is optional in both directions: an older Store never sends it (we keep the
CLI values), and --local-policy pins the CLI values against a Store that does.

Install (any box with a GPU):
    pip install pyopencl numpy requests
    python3 jellyminer.py --url http://<store-host>:8787 --token <X-Jelly-Token> --name rig1
Get the token from the Store UI: Crypto → JellyCoin → Mining.
"""
import argparse
import hashlib
import struct
import sys
import time

try:
    import numpy as np
    import pyopencl as cl
    import requests
except ImportError as e:
    sys.exit(f"missing dependency: {e.name}. Run: pip install pyopencl numpy requests")

KERNEL = r"""
__constant uint K[64] = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};

#define ROTR(x,n) (rotate((uint)(x),(uint)(32-(n))))
#define BS0(x) (ROTR(x,2)^ROTR(x,13)^ROTR(x,22))
#define BS1(x) (ROTR(x,6)^ROTR(x,11)^ROTR(x,25))
#define SS0(x) (ROTR(x,7)^ROTR(x,18)^((x)>>3))
#define SS1(x) (ROTR(x,17)^ROTR(x,19)^((x)>>10))
#define CH(x,y,z)  (((x)&(y))^(~(x)&(z)))
#define MAJ(x,y,z) (((x)&(y))^((x)&(z))^((y)&(z)))

void compress(uint *st, const uint *w16){
  uint W[64];
  for (int i=0;i<16;i++) W[i]=w16[i];
  for (int i=16;i<64;i++) W[i]=SS1(W[i-2])+W[i-7]+SS0(W[i-15])+W[i-16];
  uint a=st[0],b=st[1],c=st[2],d=st[3],e=st[4],f=st[5],g=st[6],h=st[7];
  for (int i=0;i<64;i++){
    uint t1=h+BS1(e)+CH(e,f,g)+K[i]+W[i];
    uint t2=BS0(a)+MAJ(a,b,c);
    h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
  }
  st[0]+=a; st[1]+=b; st[2]+=c; st[3]+=d; st[4]+=e; st[5]+=f; st[6]+=g; st[7]+=h;
}

__kernel void mine(__global const uint *hdr, uint base, ulong target_hi, __global uint *out){
  uint nonce = base + (uint)get_global_id(0);
  uint IV[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  uint st[8], w[16];
  for (int i=0;i<8;i++) st[i]=IV[i];
  for (int i=0;i<16;i++) w[i]=hdr[i];
  compress(st, w);                              /* block 1: header bytes 0..63   */
  w[0]=hdr[16]; w[1]=hdr[17]; w[2]=hdr[18];     /* block 2: bytes 64..75 + nonce */
  w[3]=nonce; w[4]=0x80000000U;
  for (int i=5;i<15;i++) w[i]=0;
  w[15]=640;                                    /* 80 bytes = 640 bits           */
  compress(st, w);
  uint st2[8];                                  /* second sha256 over the digest */
  for (int i=0;i<8;i++) st2[i]=IV[i];
  for (int i=0;i<8;i++) w[i]=st[i];
  w[8]=0x80000000U;
  for (int i=9;i<15;i++) w[i]=0;
  w[15]=256;
  compress(st2, w);
  ulong hi = ((ulong)st2[0]<<32) | (ulong)st2[1];
  if (hi < target_hi){
    if (atomic_cmpxchg((volatile __global uint*)&out[0], 0u, 1u) == 0u)
      out[1] = nonce;
  }
}
"""


def gpu_devices():
    """All OpenCL GPU devices on this box. CPUs are deliberately excluded."""
    devs = []
    try:
        for plat in cl.get_platforms():
            try:
                devs += plat.get_devices(device_type=cl.device_type.GPU)
            except cl.LogicError:
                pass
    except cl.LogicError:
        pass
    return devs


# Intensity bounds — must stay in step with app/routers/jellycoin.py, which
# clamps to the same range before sending a policy.
THROTTLE_MAX = 90
BATCH_MIN, BATCH_MAX = 1 << 16, 1 << 26


def apply_policy(policy, throttle, batch):
    """Adopt a Store-sent intensity policy. Returns (throttle, batch, changed?).

    Defensive on purpose: this arrives over the network, so anything malformed is
    ignored and the current values survive. Missing keys keep their current value
    rather than snapping to a default, so the Store can send `throttle` alone."""
    if not isinstance(policy, dict):
        return throttle, batch, False
    new_t, new_b = throttle, batch
    if policy.get("throttle") is not None:
        try:
            new_t = min(THROTTLE_MAX, max(0, int(policy["throttle"])))
        except (TypeError, ValueError):
            pass
    if policy.get("batch") is not None:
        try:
            new_b = min(BATCH_MAX, max(BATCH_MIN, int(policy["batch"])))
        except (TypeError, ValueError):
            pass
    return new_t, new_b, (new_t != throttle or new_b != batch)


def verify_cpu(header76: bytes, nonce: int, target: int) -> bool:
    """Exact 256-bit check of ONE candidate before submitting (verification, not mining)."""
    msg = header76 + struct.pack(">I", nonce)
    h = hashlib.sha256(hashlib.sha256(msg).digest()).digest()
    return int.from_bytes(h, "big") < target


def main():
    ap = argparse.ArgumentParser(description="JellyCoin GPU miner (OpenCL; old cards welcome)")
    ap.add_argument("--url", default="http://127.0.0.1:8787", help="Store base URL")
    ap.add_argument("--token", default="", help="X-Jelly-Token (Crypto → JellyCoin → Mining)")
    ap.add_argument("--name", default="rig", help="rig name — reward wallet becomes miner:<name>")
    ap.add_argument("--device", type=int, default=0, help="GPU index (see --list)")
    ap.add_argument("--list", action="store_true", help="list OpenCL GPU devices and exit")
    ap.add_argument("--batch", type=int, default=1 << 22, help="nonces per kernel launch")
    ap.add_argument("--refresh", type=float, default=20.0, help="seconds between getwork refreshes")
    ap.add_argument("--throttle", type=int, default=0, metavar="PCT",
                    help="percent of time to idle between batches (0-90). Use ~50 on a "
                         "modern card that's ALSO running AI (LM Studio etc.) so mining "
                         "fills the gaps instead of fighting for the GPU. ~90 with a small "
                         "--batch is the 'barely there' setting for a box doing other work")
    ap.add_argument("--local-policy", action="store_true",
                    help="ignore the intensity the Store sends and keep these CLI values")
    args = ap.parse_args()

    devs = gpu_devices()
    if args.list:
        for i, d in enumerate(devs):
            print(f"[{i}] {d.name.strip()}  ({d.platform.name.strip()})")
        return 0 if devs else 2
    if not devs:
        print("No OpenCL GPU found. JellyCoin is GPU-mined ONLY — there is no CPU fallback\n"
              "and none will be added. Install your GPU's OpenCL driver (old NVIDIA: legacy\n"
              "driver; old AMD: mesa/rusticl or amdgpu) and retry. `clinfo` helps debug.")
        return 2
    # Live-tunable intensity. These start at the CLI values and are replaced
    # whenever the Store sends a different policy (unless --local-policy).
    throttle = min(THROTTLE_MAX, max(0, args.throttle))
    batch = min(BATCH_MAX, max(BATCH_MIN, args.batch))
    dev = devs[min(args.device, len(devs) - 1)]
    gpu_name = dev.name.strip()
    print(f"⛏️  JellyMiner on: {gpu_name}  (OpenCL, batch {batch}"
          + (f", throttle {throttle}%" if throttle else "")
          + (", local policy" if args.local_policy else "") + ")")

    ctx = cl.Context([dev])
    queue = cl.CommandQueue(ctx)
    prog = cl.Program(ctx, KERNEL).build()
    kern = cl.Kernel(prog, "mine")      # retrieve once — avoids per-launch rebuild cost
    mf = cl.mem_flags
    out_np = np.zeros(2, dtype=np.uint32)
    out_buf = cl.Buffer(ctx, mf.READ_WRITE | mf.COPY_HOST_PTR, hostbuf=out_np)

    sess = requests.Session()
    if args.token:
        sess.headers["X-Jelly-Token"] = args.token
    hashrate = 0.0
    holds = 0                       # consecutive "AI queue owns the GPU" answers

    while True:
        try:
            r = sess.get(f"{args.url}/api/jelly/mining/work", timeout=10,
                         params={"miner": args.name, "gpu": gpu_name, "hashrate": hashrate})
            # The Store holds mining while its AI queue is working. Accept the
            # hold from a 503 body OR a 200 body (a proxy could rewrite either),
            # and stay perfectly happy on an older Store that never sends one.
            hold = {}
            if r.status_code in (503, 200):
                try:
                    body = r.json()
                    hold = body if isinstance(body, dict) and body.get("pause") else {}
                except ValueError:
                    hold = {}
            if hold:
                holds += 1
                base = float(hold.get("retry_after") or 15)
                wait = min(60.0, max(2.0, base) * (1.5 ** min(holds - 1, 4)))
                if holds == 1 or holds % 4 == 0:
                    print(f"⏸️  mining paused — {hold.get('reason', 'GPU in use by the AI queue')}"
                          f"; re-checking in {wait:.0f}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            work = r.json()
        except Exception as e:
            print(f"getwork failed ({e}); retrying in 10s")
            time.sleep(10)
            continue
        if holds:
            print("▶️  mining resumed")
            holds = 0

        # Live intensity. Adopted BEFORE this round's grind, so a change the owner
        # (or the Company, or the chain-defence ramp) made takes effect on the very
        # next batch — no restart, no reinstall. An older Store sends no policy and
        # this is a no-op.
        if not args.local_policy:
            throttle, batch, changed = apply_policy(work.get("policy"), throttle, batch)
            if changed:
                src = (work.get("policy") or {}).get("source") or "the Store"
                print(f"🎚️  intensity now throttle {throttle}%, batch {batch} (set by {src})")

        header76 = bytes.fromhex(work["header76"])
        target = int(work["target"], 16)
        # Pool mode: the Store advertises a SHARE target (easier than the block
        # target) only when pooling is ON. Grind to whichever we were given —
        # same sha256d kernel, only the compare threshold + submit cadence change.
        share_hex = work.get("share_target")
        pool = share_hex is not None
        cmp_target = int(share_hex, 16) if pool else target
        cmp_hi = cmp_target >> 192                       # top 64 bits for the fast GPU compare
        hdr_words = np.frombuffer(header76, dtype=">u4").astype(np.uint32)
        hdr_buf = cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=hdr_words)

        def submit(nonce):
            try:
                r = sess.post(f"{args.url}/api/jelly/mining/submit", timeout=10,
                              json={"work_id": work["work_id"], "nonce": nonce, "miner": args.name})
                res = r.json()
                if res.get("block"):
                    print(f"✅ block {res['height']} accepted → split "
                          f"+{res.get('reward', 0)} JLY across the pool")
                elif res.get("ok") and res.get("share"):
                    pass                                 # share accepted (quiet in pool mode)
                elif res.get("ok"):
                    print(f"✅ block {res['height']} accepted → +{res['reward']} JLY "
                          f"(boosts paid: {res.get('boost_paid', 0)} JLY) → {res['wallet']}")
                else:
                    print(f"❌ rejected: {res.get('reason')}")
            except Exception as e:
                print(f"submit failed: {e}")

        base, hashes, t0, found = 0, 0, time.time(), None
        while time.time() - t0 < args.refresh and base < 0xFFFFFFFF:
            tb = time.time()
            out_np[:] = 0
            cl.enqueue_copy(queue, out_buf, out_np)
            kern(queue, (batch,), None, hdr_buf,
                 np.uint32(base), np.uint64(max(1, cmp_hi)), out_buf)
            cl.enqueue_copy(queue, out_np, out_buf)
            queue.finish()
            hashes += batch
            base += batch
            if throttle:    # politeness for modern cards that also run AI workloads
                time.sleep((time.time() - tb) * throttle / (100 - throttle))
            if out_np[0]:
                cand = int(out_np[1])
                if verify_cpu(header76, cand, cmp_target):  # exact check (GPU compares 64 bits)
                    if pool:
                        submit(cand)                     # stream each share, keep grinding
                    else:
                        found = cand
                        break
        hashrate = hashes / max(0.001, time.time() - t0)
        print(f"height {work['height']}  diff {work.get('difficulty', 0):.2f}  "
              f"{hashrate/1e6:.1f} MH/s" + (" ⛏️ pool" if pool else "")
              + ("  🎉 nonce found!" if found is not None else ""))

        if found is not None:
            submit(found)


if __name__ == "__main__":
    sys.exit(main() or 0)
