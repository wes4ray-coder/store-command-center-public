"""
Shared SQLite storage core for the library module (split out of library.py).

Holds the DB path + connection helper used by both the library-links drop system
(library_links.py) and the web archive / snapshots (library_archive.py).
Kept as its own tiny module so those two concerns share one connection helper
without importing each other (no import cycle).
"""
import sqlite3
from pathlib import Path

try:
    from config import DB_PATH
except Exception:
    DB_PATH = Path(__file__).parent.parent / "store.db"


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
