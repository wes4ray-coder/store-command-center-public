"""
The Company — publish adapters (extracted from world_auto).

Blessed publish prayers → the real world: 3D models to Cults3D and generated
media to the WordPress media library, reusing the proven internal endpoints /
MCP client. Registered as world_ops executors at IMPORT time (publish_cults3d /
publish_wordpress) — world_auto imports this module so those registrations run.
Kept resilient: report rather than crash.
"""
import json, logging, os, time
import httpx
from deps import get_setting
import world_ops as wo

_LOCAL = "http://127.0.0.1:8787"   # internal calls ride the localhost auth-bypass

logger = logging.getLogger("store")


def _publish_cults3d(conn, prayer):
    """Blessed 3D model → propose listing (LLM metadata) then publish to Cults3D,
    reusing the proven internal endpoints. Resilient: reports rather than crashes."""
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    mid = payload.get("model_id")
    if not mid:
        return "no model_id"
    try:
        # 1) draft the listing (title/desc/tags/price) — async task, poll it
        pr = httpx.post(f"{_LOCAL}/api/models3d/{mid}/propose", timeout=30)
        tid = (pr.json() or {}).get("task_id")
        if tid:
            for _ in range(40):
                time.sleep(3)
                ts = httpx.get(f"{_LOCAL}/api/tasks/{tid}", timeout=15).json()
                if ts.get("status") in ("done", "error", "cancelled", "not_found"):
                    break
        # 2) publish to Cults3D (async background on success)
        pub = httpx.post(f"{_LOCAL}/api/models3d/{mid}/publish", timeout=30)
        if pub.status_code >= 400:
            msg = (pub.json() or {}).get("detail") or pub.text[:150]
            wo.note(f"Couldn’t publish model {mid} to Cults3D: {msg}", kind="warning",
                    from_agent=prayer.get("agent_name"), conn=conn)
            return f"publish rejected: {msg}"
        wo.note(f"🧊 Model {mid} is being offered on Cults3D.", kind="praise",
                from_agent=prayer.get("agent_name"), conn=conn)
        return "publishing to Cults3D underway"
    except Exception as e:
        logger.exception("cults3d publish failed")
        wo.note(f"Tried to publish model {mid} to Cults3D but hit an error ({e}).", kind="warning",
                from_agent=prayer.get("agent_name"), conn=conn)
        return f"error: {e}"


wo.register_executor("publish_cults3d", _publish_cults3d)


# ── executor: publish an approved piece to WordPress (free) ──────────────────
def _wp_mcp():
    ep = get_setting("wp_mcp_url", "")
    tok = get_setting("wp_mcp_token", "")
    if not (ep and tok):
        return None
    from wc_client import WPMcpClient
    return WPMcpClient(ep, tok)


def _web_bytes(path, max_bytes=1_900_000):
    """(filename, bytes) sized for the web media library (≤~2 MB). The print-res
    upscales (4096px) blow past WordPress's 2 MB limit, so downscale for the gallery
    while KEEPING the full-res file on disk for Printify/Etsy. Transparency preserved."""
    import os as _os
    try:
        raw = open(path, "rb").read()
        if len(raw) <= max_bytes:
            return _os.path.basename(path), raw
        from PIL import Image
        import io
        im = Image.open(path)
        transp = im.mode in ("RGBA", "LA", "P")
        base = _os.path.splitext(_os.path.basename(path))[0]
        name, out = _os.path.basename(path), raw
        for px in (1600, 1280, 1024, 800, 640, 512):
            w = im.copy()
            w.thumbnail((px, px), Image.LANCZOS)
            buf = io.BytesIO()
            if transp:
                w.save(buf, "PNG", optimize=True); name = base + ".png"
            else:
                w.convert("RGB").save(buf, "JPEG", quality=85, optimize=True); name = base + ".jpg"
            out = buf.getvalue()
            if len(out) <= max_bytes:
                break
        return name, out
    except Exception:
        return _os.path.basename(path), open(path, "rb").read()


def _publish_wordpress(conn, prayer):
    """Blessed → upload the generated media to the WordPress media library.
    Resilient: if WP isn't configured or the upload fails, the piece stays saved
    locally and we say so — the prayer still resolves 'done'."""
    try:
        payload = json.loads(prayer["payload"] or "{}")
    except Exception:
        payload = {}
    path = payload.get("path")
    # titles arrive as "Publish new artwork/track/clip: <subject>" — keep the subject
    title = prayer["title"].split(": ", 1)[-1].strip() or "Company artwork"

    if not path or not os.path.exists(path):
        wo.note(f"Wanted to publish “{title}” but the file was missing.", kind="warning",
                from_agent=prayer.get("agent_name"), conn=conn)
        return "file missing — nothing published"

    mcp = _wp_mcp()
    if not mcp:
        wo.note(f"“{title}” is ready but WordPress isn't connected — saved locally for now.",
                kind="info", from_agent=prayer.get("agent_name"), conn=conn)
        return "saved locally (WordPress MCP not configured)"

    try:
        up_name, data = _web_bytes(path)   # downscale big print-res renders for the 2 MB WP limit
        att = mcp.upload_media_base64(up_name, data, title=title,
                                      alt_text=payload.get("prompt", title))
        wp_id = att.get("id") or att.get("attachment_id")
        wp_link = att.get("source_url") or att.get("url") or ""
        conn.execute(
            "INSERT INTO portal_pushes (source,source_ref,kind,wp_id,wp_link,title) VALUES (?,?,?,?,?,?)",
            ("world_auto", str(payload.get("gen_id") or ""), "media", str(wp_id or ""), wp_link, title))
        conn.commit()
        wo.note(f"🌐 “{title}” is now live on example.com.", kind="praise",
                from_agent=prayer.get("agent_name"), conn=conn)
        return f"published to WordPress (id {wp_id})"
    except Exception as e:
        logger.exception("world_auto publish failed")
        wo.note(f"Tried to publish “{title}” but WordPress refused ({e}). Saved locally.",
                kind="warning", from_agent=prayer.get("agent_name"), conn=conn)
        return f"publish failed: {e}"


wo.register_executor("publish_wordpress", _publish_wordpress)
