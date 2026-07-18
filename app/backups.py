"""Automated DB backups.

A CONSISTENT online snapshot of the SQLite DB (via sqlite3's backup API — safe to take
while the app is writing), gzipped, written to the local backups dir AND an off-box
destination (e.g. an external drive) when configured, with retention. Wired into
scheduler.py to run nightly. The DB is the crown jewel (financial ledger, listings,
settings) — designs/videos are large + regenerable, so this snapshots the DB only.

Settings (all optional):
  backup_enabled       "1"/"0"   default on
  backup_interval_min   minutes   default 1440 (daily)
  backup_dest_dir       path      off-box copy target (e.g. /media/.../store-backups)
  backup_keep           int       how many to retain per destination (default 14)
"""
import gzip
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from config import DB_PATH, BACKUP_DIR
from db import get_conn

log = logging.getLogger("store")


def _setting(key, default=""):
    try:
        conn = get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row["value"] if row and row["value"] else default
    except Exception:
        return default


def _dest_dirs():
    """Always the local backups dir, plus an off-box dir if `backup_dest_dir` is set AND
    its mount point is present (so we never create dirs on an unmounted external path)."""
    dests = [Path(BACKUP_DIR)]
    ext = _setting("backup_dest_dir", "").strip()
    if ext:
        p = Path(ext)
        try:
            if p.exists() or p.parent.exists():   # mount present
                dests.append(p)
            else:
                log.warning("backup_dest_dir %s not available (drive unmounted?) — skipping off-box copy", ext)
        except Exception as e:
            log.warning("backup_dest_dir %s check failed: %s", ext, e)
    # de-dup by resolved path
    seen, out = set(), []
    for d in dests:
        r = str(Path(d).resolve())
        if r not in seen:
            seen.add(r); out.append(Path(d))
    return out


def _snapshot_gz(dest_file: Path):
    """Consistent online snapshot of the live DB → gzipped file at dest_file."""
    tmp = dest_file.with_name(dest_file.name + ".tmp")
    src = sqlite3.connect(str(DB_PATH))
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)          # atomic + consistent even mid-write
        finally:
            dst.close()
    finally:
        src.close()
    with open(tmp, "rb") as fin, gzip.open(str(dest_file), "wb") as fout:
        while True:
            chunk = fin.read(1 << 20)
            if not chunk:
                break
            fout.write(chunk)
    tmp.unlink(missing_ok=True)


def _prune(d: Path, keep: int):
    files = sorted(d.glob("store_db_*.sqlite.gz"), reverse=True)
    for old in files[max(1, keep):]:
        try:
            old.unlink()
        except Exception:
            pass


def run_scheduled_backup(keep=None):
    """Snapshot the DB to every destination, prune old ones. Returns a summary dict."""
    if keep is None:
        try:
            keep = int(_setting("backup_keep", "14"))
        except Exception:
            keep = 14
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"store_db_{ts}.sqlite.gz"
    copies, errors = [], []
    key_file = Path(DB_PATH).parent / ".secret_key"
    for d in _dest_dirs():
        try:
            d.mkdir(parents=True, exist_ok=True)
            _snapshot_gz(d / name)
            _prune(d, keep)
            # The DB is encrypted at rest — a restore is useless without the key, so keep a
            # copy alongside each backup (secure the backup medium; see HARDENING.md).
            if key_file.exists():
                (d / ".secret_key").write_bytes(key_file.read_bytes())
            copies.append(str(d / name))
        except Exception as e:
            errors.append(f"{d}: {e}")
            log.error("backup to %s failed: %s", d, e)
    log.info("scheduled DB backup wrote %d copies (%s)%s", len(copies), name,
             (" errors: " + "; ".join(errors)) if errors else "")
    # record last-run in settings for the UI/status
    try:
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('backup_last_run',?)",
                     (datetime.now().isoformat(timespec="seconds"),))
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('backup_last_copies',?)",
                     (str(len(copies)),))
        conn.commit(); conn.close()
    except Exception:
        pass
    return {"name": name, "copies": copies, "errors": errors}
