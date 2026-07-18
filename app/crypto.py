"""Encryption for credential settings at rest.

Secret settings (API keys, tokens, passwords) are stored in the `settings` table
encrypted with Fernet (AES-128-CBC + HMAC). The key comes from the environment
(`STORE_SECRET_KEY`) or a local key file (`DATA_DIR/.secret_key`, chmod 600) — NEVER
from the DB, so a stolen `store.db` alone can't reveal the credentials.

`dec()` is passthrough-safe: any value without the marker (legacy plaintext, or a
non-secret) is returned unchanged. This makes the rollout backward-compatible, and a
key mishap degrades to "an integration can't authenticate", not "the app crashes".
"""
import os
import logging
from pathlib import Path

from cryptography.fernet import Fernet

try:
    from config import DATA_DIR
except Exception:
    DATA_DIR = Path(__file__).resolve().parent.parent

_log = logging.getLogger("store")
_MARKER = "enc:v1:"

# Setting keys whose VALUE is a credential to encrypt at rest.
SECRET_KEYS = {
    "printify_key", "etsy_key", "etsy_shared_secret", "etsy_access_token",
    "etsy_refresh_token", "cults3d_api_key", "hf_token", "lmstudio_api_key",
    "models3d_asset_token", "wp_consumer_key", "wp_consumer_secret", "wp_mcp_token",
    "world_paypal_client_id", "world_paypal_secret", "mail_pass",
    # money + crypto/markets tabs (2026-07-17)
    "money_signal_token", "btc_rpc_pass", "ft_api_pass",
    "rh_password", "rh_mfa_secret",
    # real light-wallet master seed — controls REAL funds
    "wallet_mnemonic",
    # Kraken exchange API credentials (real account)
    "kraken_api_key", "kraken_api_secret",
    # JellyCoin GPU-rig shared token (LAN mining auth)
    "jelly_miner_token",
}


def is_secret(key: str) -> bool:
    return key in SECRET_KEYS


def _key_path() -> Path:
    return Path(DATA_DIR) / ".secret_key"


def _load_key() -> bytes:
    env = os.environ.get("STORE_SECRET_KEY", "").strip()
    if env:
        return env.encode()
    p = _key_path()
    if p.exists():
        return p.read_bytes().strip()
    key = Fernet.generate_key()
    try:
        p.write_bytes(key)
        os.chmod(p, 0o600)
        _log.info("generated new secret key at %s (back this up — losing it loses the secrets)", p)
    except Exception as e:
        _log.error("could not persist secret key to %s: %s", p, e)
    return key


_fernet = None


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(_MARKER)


def enc(value):
    """Encrypt a plaintext string. No-op on empty/None or already-encrypted values."""
    if value is None or value == "":
        return value
    if is_encrypted(value):
        return value
    try:
        return _MARKER + _f().encrypt(str(value).encode()).decode()
    except Exception as e:
        _log.error("secret encrypt failed (storing plaintext): %s", e)
        return value


def dec(value):
    """Decrypt a value. Passthrough for anything not marked-encrypted (plaintext-safe)."""
    if not is_encrypted(value):
        return value
    try:
        return _f().decrypt(value[len(_MARKER):].encode()).decode()
    except Exception as e:
        _log.error("secret decrypt failed (returning raw): %s", e)
        return value


def dec_secrets(d: dict) -> dict:
    """Return a copy of a settings dict with its secret values decrypted."""
    if not d:
        return d
    out = dict(d)
    for k in SECRET_KEYS:
        if out.get(k):
            out[k] = dec(out[k])
    return out


def migrate_encrypt_secrets(get_conn) -> int:
    """Idempotent: encrypt any plaintext secret rows in the settings table. Safe to run on
    every startup — already-encrypted rows are skipped. Returns how many were encrypted."""
    try:
        conn = get_conn()
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        changed = 0
        for r in rows:
            k, v = r["key"], r["value"]
            if k in SECRET_KEYS and v and not is_encrypted(v):
                conn.execute("UPDATE settings SET value=? WHERE key=?", (enc(v), k))
                changed += 1
        if changed:
            conn.commit()
            _log.info("encrypted %d plaintext secret(s) at rest", changed)
        conn.close()
        return changed
    except Exception as e:
        _log.error("secret migration failed: %s", e)
        return 0
