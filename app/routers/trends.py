"""trends routes."""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Form, UploadFile, File
from deps import *
from services import *

router = APIRouter()


@router.get("/api/trends/status")
def trend_status():
    return _trend_scan

@router.get("/api/trends/config")
def trend_config():
    conn = get_conn()
    rows = conn.execute("SELECT key,value FROM settings WHERE key LIKE 'trend_%'").fetchall()
    conn.close()
    cfg = {r["key"]: r["value"] for r in rows}
    return {
        "google_enabled":  cfg.get("trend_google_enabled",  "true") == "true",
        "reddit_enabled":  cfg.get("trend_reddit_enabled",  "true") == "true",
        "rss_enabled":     cfg.get("trend_rss_enabled",     "true") == "true",
        "google_region":   cfg.get("trend_google_region",   "US"),
        "reddit_subs":     cfg.get("trend_reddit_subs",     ",".join(DEFAULT_SUBS)),
        "rss_urls":        cfg.get("trend_rss_urls",        "\n".join(DEFAULT_RSS_FEEDS)),
        "last_run":        cfg.get("trend_last_run",        ""),
        "last_count":      int(cfg.get("trend_last_count",  "0")),
    }

@router.patch("/api/trends/config")
def save_trend_config(data: dict):
    conn = get_conn()
    mapping = {
        "google_enabled":  "trend_google_enabled",
        "reddit_enabled":  "trend_reddit_enabled",
        "rss_enabled":     "trend_rss_enabled",
        "google_region":   "trend_google_region",
        "reddit_subs":     "trend_reddit_subs",
        "rss_urls":        "trend_rss_urls",
    }
    for k, dbk in mapping.items():
        if k in data:
            v = data[k]
            if isinstance(v, bool):
                v = "true" if v else "false"
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (dbk, str(v)))
    conn.commit()
    conn.close()
    return {"ok": True}

@router.post("/api/trends/scan")
def trigger_trend_scan(background_tasks: BackgroundTasks):
    if _trend_scan["status"] == "running":
        return {"ok": False, "message": "Scan already running"}
    background_tasks.add_task(_run_trend_scan)
    return {"ok": True, "message": "Scan started"}
