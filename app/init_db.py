import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "store.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Re-run the script that has the migrations
    # I'll just paste the relevant part of the init_db from the read result
    # But wait, I can just read the file and execute the function if I'm in the same dir
    # Since I'm writing to store/app/init_db.py, it's easier to just write the logic.
    
    # The migration logic for security_scans:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS security_scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT,            -- healthy | needs_attention | unknown
        last_scan_at TEXT,
        report_path TEXT,
        summary_json TEXT,      -- parsed summary for API
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()
    print("Database initialized with security_scans table.")

if __name__ == "__main__":
    init_db()
