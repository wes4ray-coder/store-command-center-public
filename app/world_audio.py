"""
The Company — GENERATED soundscape (own ambient beds + SFX one-shots).

The world tab ships a WebAudio synth fallback (static/js/world-audio.js), but the
store owns real audio models on the GPU node (Stable Audio / MusicGen). This module
renders the town's ambience and per-action foley with those models and caches the
wavs under DATA_DIR/world_audio/, so The Company literally generates its own sounds.

How it runs: each asset becomes a normal `audio_clips` row driven through
services.run_audio_clip — i.e. the SAME pipeline/GPU serialization as the Audio
Studio (clips also show up there, progress and all). Generation is MANUAL-ONLY
(the 🔊 mixer's "Generate" button); nothing auto-spawns GPU work. The frontend
"Generated" toggle (localStorage world_snd_gen) decides whether the cached wavs
are played or the synth stays.

Engines: "auto" prefers Stable Audio Open (real foley/ambience) when its snapshot
exists on the node, else falls back to MusicGen Small (always installable).
"""
import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from config import DATA_DIR, BOX_SSH
from deps import get_conn

logger = logging.getLogger("store")

ASSET_DIR = DATA_DIR / "world_audio"
_MANIFEST = ASSET_DIR / "manifest.json"

# ── the catalog ──────────────────────────────────────────────────────────────
# Ambient beds are picked by live context (phase → raid; else day/night, day by
# season) and looped client-side; SFX keys MUST match the SFX map in
# static/js/world-audio.js (the synth voice of the same name is the fallback).
_LOOP = "seamless background loop, field recording, no music, no melody"
_ONE = "single sound effect, one-shot, foley, clean, no music, no voice"
CATALOG = {
    # ambient beds (context → loop)
    "amb_day_spring": {"kind": "ambient", "dur": 20, "label": "Spring day ambience",
                       "prompt": f"gentle springtime village ambience, soft birdsong, light breeze in fresh leaves, distant friendly chatter, {_LOOP}"},
    "amb_day_summer": {"kind": "ambient", "dur": 20, "label": "Summer day ambience",
                       "prompt": f"warm summer afternoon town ambience, lazy insects buzzing, soft wind, sparse distant birds, {_LOOP}"},
    "amb_day_autumn": {"kind": "ambient", "dur": 20, "label": "Autumn day ambience",
                       "prompt": f"brisk autumn village ambience, wind through dry rustling leaves, distant crows, creaking wood, {_LOOP}"},
    "amb_day_winter": {"kind": "ambient", "dur": 20, "label": "Winter day ambience",
                       "prompt": f"cold winter ambience, steady icy wind, muffled stillness, faint far-off wind chime, {_LOOP}"},
    "amb_night":      {"kind": "ambient", "dur": 20, "label": "Night ambience",
                       "prompt": f"quiet peaceful night ambience, crickets chirping, soft breeze, distant owl hoot, {_LOOP}"},
    "amb_raid":       {"kind": "ambient", "dur": 20, "label": "Raid battle ambience",
                       "prompt": f"tense battle ambience, rolling war drums, low ominous rumble, distant metal clashes and shouting, {_LOOP}"},
    # event/action SFX one-shots (keys = world-audio.js SFX names)
    "door":    {"kind": "sfx", "dur": 3, "label": "Door",          "prompt": f"wooden door opening and shutting, {_ONE}"},
    "bless":   {"kind": "sfx", "dur": 3, "label": "Blessing chime","prompt": f"soft magical blessing chime, gentle ascending glass bells, {_ONE}"},
    "ship":    {"kind": "sfx", "dur": 3, "label": "Product ship",  "prompt": f"cheerful success chime with a short whoosh, {_ONE}"},
    "raid":    {"kind": "sfx", "dur": 4, "label": "Raid alarm",    "prompt": f"urgent town alarm bell ringing three times, {_ONE}"},
    "coin":    {"kind": "sfx", "dur": 3, "label": "Coin",          "prompt": f"a coin dropping and ringing on wood, bright metallic, {_ONE}"},
    "eat":     {"kind": "sfx", "dur": 3, "label": "Eating",        "prompt": f"a quick bite and munch of crunchy food, {_ONE}"},
    "mine":    {"kind": "sfx", "dur": 3, "label": "Mining pick",   "prompt": f"pickaxe striking rock with a metallic clink, {_ONE}"},
    "chop":    {"kind": "sfx", "dur": 3, "label": "Axe chop",      "prompt": f"axe chopping into a tree trunk, solid wood thock, {_ONE}"},
    "farm":    {"kind": "sfx", "dur": 3, "label": "Farming",       "prompt": f"garden hoe digging into soil, earthy rustle, {_ONE}"},
    "fish":    {"kind": "sfx", "dur": 3, "label": "Fishing plop",  "prompt": f"fishing bobber plopping into a calm pond, small splash, {_ONE}"},
    "build":   {"kind": "sfx", "dur": 3, "label": "Hammering",     "prompt": f"hammer tapping a nail into wood, {_ONE}"},
    "study":   {"kind": "sfx", "dur": 3, "label": "Page flip",     "prompt": f"paper page flipping in a book, soft rustle, {_ONE}"},
    "pray":    {"kind": "sfx", "dur": 3, "label": "Prayer bell",   "prompt": f"soft meditation bell with a long gentle decay, {_ONE}"},
    "swing":   {"kind": "sfx", "dur": 3, "label": "Weapon swing",  "prompt": f"sword whoosh followed by a metal clash, {_ONE}"},
    "kill":    {"kind": "sfx", "dur": 3, "label": "Enemy felled",  "prompt": f"heavy body thud hitting the ground, deep impact, {_ONE}"},
    "levelup": {"kind": "sfx", "dur": 3, "label": "Level-up",      "prompt": f"short triumphant level-up fanfare, rising chiptune arpeggio, {_ONE}"},
    "shop":    {"kind": "sfx", "dur": 3, "label": "Cash register", "prompt": f"old cash register ka-ching with drawer opening, {_ONE}"},
    "place":   {"kind": "sfx", "dur": 3, "label": "Furniture place","prompt": f"wooden furniture set down on a floor with a solid thunk, {_ONE}"},
}

# ── job state (one generation run at a time) ─────────────────────────────────
_job = {"status": "idle", "done": 0, "total": 0, "current": "", "errors": [], "started": 0}
_lock = threading.Lock()


def _manifest() -> dict:
    try:
        return json.loads(_MANIFEST.read_text())
    except Exception:
        return {}


def _save_manifest(man: dict):
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    _MANIFEST.write_text(json.dumps(man, indent=1))


def asset_path(key: str) -> Path:
    return ASSET_DIR / f"{key}.wav"


def list_assets() -> dict:
    """Everything the frontend needs: per-asset ready/url + the running job."""
    man = _manifest()
    assets = []
    for key, spec in CATALOG.items():
        ready = asset_path(key).exists()
        a = {"key": key, "kind": spec["kind"], "label": spec["label"], "ready": ready,
             "url": f"/api/world/audio/file/{key}" if ready else None}
        if ready and key in man:
            a["engine"] = man[key].get("engine")
        assets.append(a)
    job = {k: v for k, v in _job.items() if k != "errors"}
    job["errors"] = _job["errors"][-5:]
    return {"assets": assets, "job": job}


def resolve_engine(engine: str = "auto") -> str:
    """'auto' → Stable Audio Open if its snapshot is on the node, else MusicGen."""
    if engine and engine != "auto":
        return engine
    try:
        import services as _svc
        adir = _svc.audio_models_dir()
        hub = f"{adir}/hub" if adir else "$HOME/.cache/huggingface/hub"
        d = "models--stabilityai--stable-audio-open-1.0"
        r = subprocess.run(
            BOX_SSH + [f'ls "{hub}/{d}/snapshots" 2>/dev/null | grep -q . && echo ok'],
            capture_output=True, text=True, timeout=12)
        if "ok" in (r.stdout or ""):
            return "stable_audio"
    except Exception:
        pass
    return "musicgen"


def start_generate(keys=None, engine: str = "auto", force: bool = False) -> dict:
    """Queue the missing (or listed / forced) assets through the normal audio-clip
    pipeline, sequentially in a background thread. Manual-only — the 🔊 mixer button."""
    with _lock:
        if _job["status"] == "running":
            return {"ok": True, "queued": 0, "status": "already_running"}
        todo = [k for k in (keys or CATALOG) if k in CATALOG
                and (force or not asset_path(k).exists())]
        if not todo:
            return {"ok": True, "queued": 0, "status": "nothing_to_do"}
        eng = resolve_engine(engine)
        _job.update(status="running", done=0, total=len(todo), current="starting…",
                    errors=[], started=int(time.time()))
        threading.Thread(target=_worker, args=(todo, eng), daemon=True,
                         name="world-audio-gen").start()
        return {"ok": True, "queued": len(todo), "engine": eng, "status": "running"}


def _worker(todo: list, engine: str):
    import services  # late: heavy module, and tests monkeypatch run_audio_clip on it
    ok_n = 0
    for i, key in enumerate(todo):
        spec = CATALOG[key]
        _job.update(done=i, current=spec["label"])
        try:
            conn = get_conn()
            cur = conn.execute(
                "INSERT INTO audio_clips (kind,prompt,engine,model_id,duration,lyrics,status) "
                "VALUES ('music',?,?,NULL,?,NULL,'queued')",
                (spec["prompt"], engine, spec["dur"]))
            cid = cur.lastrowid
            conn.commit()
            conn.close()
            services.run_audio_clip(cid)      # blocks; orchestrator serializes the GPU
            conn = get_conn()
            row = conn.execute("SELECT status,audio_path FROM audio_clips WHERE id=?",
                               (cid,)).fetchone()
            conn.close()
            if row and row["status"] == "done" and row["audio_path"] and Path(row["audio_path"]).exists():
                ASSET_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(row["audio_path"], asset_path(key))
                man = _manifest()
                man[key] = {"clip_id": cid, "engine": engine, "created": int(time.time())}
                _save_manifest(man)
                ok_n += 1
            else:
                _job["errors"].append(f"{key}: clip {cid} did not complete")
        except Exception as ex:
            logger.error("world audio asset %s failed: %s", key, ex)
            _job["errors"].append(f"{key}: {str(ex)[:120]}")
    _job.update(done=len(todo), current="",
                status="done" if ok_n else "error")
    if not ok_n and _job["errors"]:
        _job["error"] = _job["errors"][-1]
    logger.info("world audio generation finished: %d/%d ok", ok_n, len(todo))
