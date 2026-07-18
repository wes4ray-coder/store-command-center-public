#!/usr/bin/env python3
"""Forgot the Store Command Center password? Run this ON THE SERVER, from the
repo root (the venv is not required — stdlib only):

    python3 reset_password.py               # reset to first-run state:
                                            #   log in with the default password
                                            #   "store" and you'll be walked
                                            #   through choosing a new one
    python3 reset_password.py MyNewPass     # or set a specific password now

Works directly on store.db (settings table) — the running app picks it up on
the next login attempt, no restart needed.
"""
import hashlib
import os
import secrets
import sqlite3
import sys
from pathlib import Path

data_dir = os.environ.get("STORE_DATA_DIR") or str(Path(__file__).parent)
db = Path(data_dir) / "store.db"
if not db.exists():
    sys.exit(f"store.db not found at {db} — run from the repo root (or set STORE_DATA_DIR)")

conn = sqlite3.connect(db)
if len(sys.argv) > 1:
    pw = sys.argv[1]
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 390000)
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('_auth_password_hash',?)",
                 (f"pbkdf2$390000${salt}${dk.hex()}",))
    conn.execute("DELETE FROM settings WHERE key='_auth_default_pw'")
    print("Password set. Sign in with your new password.")
else:
    conn.execute("DELETE FROM settings WHERE key IN ('_auth_password_hash','_auth_default_pw')")
    print('Reset to first-run: sign in with the default password "store" — '
          "the app will prompt you to choose a new one.")
conn.commit()
conn.close()
