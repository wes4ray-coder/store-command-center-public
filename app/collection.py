"""ControlNet product-line collections.

Take one design and generate a COHERENT SET that shares its composition/pose via
ControlNet Union (Canny edges). Each variant is its own prompt but the same layout, so
a whole merch collection looks like a family. Runs through the orchestrator (unified
GPU queue) and lands each variant as a `designs` row (source='collection').

Needs: controlnet-union-sdxl-promax in models/controlnet/ (checked; graceful error if
missing). Workflow: LoadImage(source) → Canny → ControlNetLoader + SetUnionControlNetType
+ ControlNetApplyAdvanced → KSampler(variant prompt) → VAEDecode → SaveImage.
"""
import json
import logging
import time
from datetime import datetime

import httpx

from config import COMFYUI_URL, DESIGNS_PENDING
from deps import DEFAULT_IMAGE_MODEL
from db import get_conn
import orchestrator as _orch_mod

logger = logging.getLogger("store")

CONTROLNET_UNION = "controlnet-union-sdxl-promax.safetensors"
_NEG = "text, watermark, blurry, ugly, low quality, extra limbs"


def controlnet_installed():
    try:
        r = httpx.get(f"{COMFYUI_URL}/object_info/ControlNetLoader", timeout=6)
        spec = r.json()["ControlNetLoader"]["input"]["required"]["control_net_name"]
        opts = spec[1].get("options", []) if isinstance(spec[0], str) else spec[0]
        return CONTROLNET_UNION in set(opts)
    except Exception:
        return False


def _upload_source(image_path):
    """Push the source design into ComfyUI's input dir; return the stored filename."""
    with open(image_path, "rb") as f:
        r = httpx.post(f"{COMFYUI_URL}/upload/image",
                       files={"image": (f"src_{int(time.time())}.png", f, "image/png")},
                       data={"overwrite": "true"}, timeout=60)
    r.raise_for_status()
    return r.json()["name"]


def _build_workflow(src_name, prompt, model, w, h, seed, strength):
    return {
        "1": {"inputs": {"image": src_name}, "class_type": "LoadImage"},
        "2": {"inputs": {"image": ["1", 0], "low_threshold": 0.4, "high_threshold": 0.8}, "class_type": "Canny"},
        "4": {"inputs": {"ckpt_name": model}, "class_type": "CheckpointLoaderSimple"},
        "5": {"inputs": {"width": w, "height": h, "batch_size": 1}, "class_type": "EmptyLatentImage"},
        "6": {"inputs": {"text": prompt, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "7": {"inputs": {"text": _NEG, "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "10": {"inputs": {"control_net_name": CONTROLNET_UNION}, "class_type": "ControlNetLoader"},
        "11": {"inputs": {"control_net": ["10", 0], "type": "canny/lineart/anime_lineart/mlsd"},
               "class_type": "SetUnionControlNetType"},
        "12": {"inputs": {"positive": ["6", 0], "negative": ["7", 0], "control_net": ["11", 0],
                          "image": ["2", 0], "strength": strength, "start_percent": 0.0, "end_percent": 0.85},
               "class_type": "ControlNetApplyAdvanced"},
        "3": {"inputs": {"seed": seed, "steps": 8, "cfg": 2, "sampler_name": "dpmpp_sde",
                         "scheduler": "karras", "denoise": 1.0, "model": ["4", 0],
                         "positive": ["12", 0], "negative": ["12", 1], "latent_image": ["5", 0]},
              "class_type": "KSampler"},
        "8": {"inputs": {"samples": ["3", 0], "vae": ["4", 2]}, "class_type": "VAEDecode"},
        "9": {"inputs": {"filename_prefix": "oc_collection", "images": ["8", 0]}, "class_type": "SaveImage"},
    }


def _run_one(src_name, prompt, model, w, h, seed, strength, out_path):
    wf = _build_workflow(src_name, prompt, model, w, h, seed, strength)
    r = httpx.post(f"{COMFYUI_URL}/prompt", json={"prompt": wf, "client_id": f"coll-{int(time.time())}"}, timeout=30)
    r.raise_for_status()
    pid = r.json()["prompt_id"]
    for _ in range(240):
        time.sleep(1)
        h_r = httpx.get(f"{COMFYUI_URL}/history/{pid}", timeout=15)
        hist = h_r.json().get(pid)
        if not hist:
            continue
        outs = hist.get("outputs", {})
        imgs = (outs.get("9", {}) or {}).get("images", [])
        if imgs:
            im = imgs[0]
            v = httpx.get(f"{COMFYUI_URL}/view",
                          params={"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                  "type": im.get("type", "output")}, timeout=60)
            v.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(v.content)
            return True
        if hist.get("status", {}).get("status_str") == "error":
            return False
    return False


def make_collection(design_id, variants, strength=0.8):
    """Generate a matching-collection from `design_id` using each string in `variants`
    as a themed prompt (shared composition via ControlNet). Returns created design ids."""
    orch = _orch_mod.orch
    conn = get_conn()
    src = conn.execute("SELECT image_path, product_type, prompt FROM designs WHERE id=?", (design_id,)).fetchone()
    conn.close()
    if not src or not src["image_path"]:
        return {"ok": False, "error": "source design not found or has no image"}
    if not controlnet_installed():
        return {"ok": False, "error": "ControlNet Union model not installed — download it in Studio → Image"}

    import os
    if not os.path.exists(src["image_path"]):
        return {"ok": False, "error": "source image file missing"}

    ptype = src["product_type"] or "Poster"
    model = DEFAULT_IMAGE_MODEL
    created = []
    orch.image_acquire()
    try:
        # Resize the source to <=1024 (RGB, no alpha) BEFORE Canny/upload — Canny on a
        # full 4096px render OOMs the GPU, and the control image should match the latent.
        from PIL import Image
        tmp = DESIGNS_PENDING / f".coll_src_{design_id}.png"
        with Image.open(src["image_path"]) as im0:
            im = im0.convert("RGB")
            im.thumbnail((1024, 1024), Image.LANCZOS)
            w, h = im.size
            im.save(tmp)
        src_name = _upload_source(str(tmp))
        for i, vp in enumerate([v for v in variants if (v or "").strip()][:6]):
            seed = (int(time.time()) + i * 7919) % (2**31 - 1)
            out_path = DESIGNS_PENDING / f"coll_{design_id}_{int(datetime.now().timestamp())}_{i}.png"
            ok = _run_one(src_name, vp.strip(), model, w, h, seed, strength, str(out_path))
            if not ok or not out_path.exists():
                logger.warning("collection variant %d failed for design %s", i, design_id)
                continue
            conn = get_conn()
            try:
                cur = conn.execute(
                    "INSERT INTO generations (prompt,product_type,width,height,steps,model,source,status,image_path) "
                    "VALUES (?,?,?,?,?,?, 'collection','done', ?)",
                    (vp.strip(), ptype, w, h, 8, model, str(out_path)))
                gid = cur.lastrowid
                conn.execute(
                    "INSERT INTO designs (generation_id,image_path,prompt,product_type,source) VALUES (?,?,?,?,?)",
                    (gid, str(out_path), vp.strip(), ptype, "collection"))
                conn.commit()
                created.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            finally:
                conn.close()
    except Exception as e:
        logger.exception("make_collection failed")
        return {"ok": False, "error": str(e), "created": created}
    finally:
        try:
            (DESIGNS_PENDING / f".coll_src_{design_id}.png").unlink(missing_ok=True)
        except Exception:
            pass
        orch.image_release()
    return {"ok": True, "created": created, "count": len(created)}
