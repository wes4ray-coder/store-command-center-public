"""Auth core: password hashing/verification, first-run secret, and the login page.

Extracted verbatim from deps.py for modularity. Re-exported through
`from deps import *` (deps re-imports these single-underscore names explicitly, and
its bottom __all__ picks them up), so the public surface of deps is unchanged.

Dependency direction: auth_core -> db (get_conn) + stdlib only. It does NOT import
deps, so there is no import cycle.
"""

import hashlib as _hashlib
import secrets as _secrets
import hmac as _hmac

from db import get_conn


def _ensure_db():
    from db import init_db as _init
    _init()


def _get_or_create_secret() -> str:
    _ensure_db()
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key='_auth_secret'").fetchone()
    if row:
        conn.close()
        return row["value"]
    key = _secrets.token_hex(32)
    conn.execute("INSERT INTO settings (key,value) VALUES ('_auth_secret',?)", (key,))
    conn.commit()
    conn.close()
    return key


def _pw_hash(pw: str, salt: str = None, iterations: int = 200_000) -> str:
    """Salted PBKDF2-HMAC-SHA256. Format: pbkdf2$<iters>$<salt_hex>$<derived_hex>.
    (Was plain sha256 — legacy hashes still verify + auto-upgrade on next login.)"""
    if salt is None:
        salt = _secrets.token_hex(16)
    dk = _hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2${iterations}${salt}${dk.hex()}"


def _verify_pw(pw: str, stored: str) -> bool:
    """Constant-time verify against a pbkdf2 hash, or a legacy plain-sha256 one."""
    if stored.startswith("pbkdf2$"):
        try:
            _, iters, salt, _h = stored.split("$", 3)
            return _hmac.compare_digest(_pw_hash(pw, salt=salt, iterations=int(iters)), stored)
        except Exception:
            return False
    return _hmac.compare_digest(_hashlib.sha256(pw.encode("utf-8")).hexdigest(), stored)


def _get_stored_hash() -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key='_auth_password_hash'").fetchone()
    conn.close()
    return row["value"] if row else None


def _set_stored_hash(pw: str):
    h = _pw_hash(pw)   # always stores salted pbkdf2
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('_auth_password_hash',?)", (h,))
    conn.commit()
    conn.close()


def is_default_password() -> bool:
    """True while the install still runs on the first-run default password —
    drives the login-page hint and the post-login 'change it now' banner."""
    if _get_stored_hash() is None:
        return True
    try:
        conn = get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key='_auth_default_pw'").fetchone()
        conn.close()
        return bool(row and row["value"] == "1")
    except Exception:
        return False


def _flag_default_pw(on: bool):
    try:
        conn = get_conn()
        if on:
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('_auth_default_pw','1')")
        else:
            conn.execute("DELETE FROM settings WHERE key='_auth_default_pw'")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _check_password(pw: str) -> bool:
    stored = _get_stored_hash()
    if stored is None:
        # First-run default password — accept it, but FLAG it so the UI walks the
        # user straight to changing it (it used to lock in silently, and anyone
        # typing the password they *wanted* just got "Incorrect password").
        if _hmac.compare_digest(_hashlib.sha256(pw.encode("utf-8")).hexdigest(),
                                _hashlib.sha256(b"store").hexdigest()):
            _set_stored_hash(pw)
            _flag_default_pw(True)
            return True
        return False
    if _verify_pw(pw, stored):
        if not stored.startswith("pbkdf2$"):   # transparent upgrade of legacy hashes
            _set_stored_hash(pw)
        return True
    return False


_LOGIN_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Store — Sign In</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:#0d0d12;color:#e2e2f0;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}
.card{background:#16161f;border:1px solid #2a2a3a;border-radius:16px;
  padding:40px;width:100%;max-width:360px;box-shadow:0 20px 60px rgba(0,0,0,.5);}
.logo{font-size:2.2rem;text-align:center;margin-bottom:8px;}
h1{text-align:center;font-size:1rem;color:#9090b0;margin-bottom:28px;font-weight:400;}
label{display:block;font-size:.78rem;font-weight:600;color:#9090b0;margin-bottom:6px;letter-spacing:.03em;text-transform:uppercase;}
input[type=password]{width:100%;padding:10px 14px;background:#0d0d12;
  border:1px solid #2a2a3a;border-radius:8px;color:#e2e2f0;font-size:.95rem;
  outline:none;transition:border-color .15s;}
input[type=password]:focus{border-color:#6c63ff;}
button{width:100%;margin-top:16px;padding:11px;background:#6c63ff;
  border:none;border-radius:8px;color:#fff;font-size:.95rem;font-weight:600;
  cursor:pointer;transition:background .15s;}
button:hover{background:#7c73ff;}
.err{background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);
  border-radius:8px;padding:10px 14px;font-size:.82rem;color:#f87171;
  margin-bottom:18px;}
</style>
</head>
<body>
<div class="card">
  <div class="logo">🛍️</div>
  <h1>Store Command Center</h1>
  {error_block}
  <form method="post">
    <label for="p">Password</label>
    <input type="password" id="p" name="password" autofocus placeholder="Enter password">
    <button type="submit">Sign In →</button>
  </form>
</div>
</body></html>"""

_AUTH_BYPASS = {"/login", "/logout"}
