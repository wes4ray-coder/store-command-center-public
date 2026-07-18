"""Automated DB backups (app/backups.py). Runs against the temp DB; no external drive."""
import gzip
import sqlite3
from pathlib import Path

import backups
from config import BACKUP_DIR


def test_backup_creates_a_valid_db_snapshot():
    r = backups.run_scheduled_backup()
    assert r["copies"], "no backup copies were written"
    assert not r["errors"], r["errors"]
    gz = Path(r["copies"][0])
    assert gz.exists()
    assert gz.name.startswith("store_db_") and gz.name.endswith(".sqlite.gz")

    # decompress → must be a real, queryable SQLite DB (proves a consistent snapshot)
    restored = Path(BACKUP_DIR) / "_restore_check.sqlite"
    restored.write_bytes(gzip.open(str(gz), "rb").read())
    conn = sqlite3.connect(str(restored))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "settings" in tables, "restored snapshot is missing the settings table"


def test_prune_keeps_only_n(tmp_path):
    for i in range(6):
        (tmp_path / f"store_db_2026010{i}_000000.sqlite.gz").write_bytes(b"x")
    backups._prune(tmp_path, keep=2)
    remaining = sorted(p.name for p in tmp_path.glob("store_db_*.sqlite.gz"))
    assert len(remaining) == 2
    # keeps the NEWEST (highest timestamps sort last)
    assert remaining == ["store_db_20260104_000000.sqlite.gz", "store_db_20260105_000000.sqlite.gz"]


def test_dest_dirs_skips_unmounted_external():
    import db
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES "
                 "('backup_dest_dir','/no/such/mount/xyz/store-backups')")
    conn.commit(); conn.close()
    dests = [str(d) for d in backups._dest_dirs()]
    assert any("backups" in d for d in dests)                 # local dir always present
    assert not any("/no/such/mount" in d for d in dests)      # unmounted external skipped
    # cleanup
    conn = db.get_conn()
    conn.execute("DELETE FROM settings WHERE key='backup_dest_dir'")
    conn.commit(); conn.close()
