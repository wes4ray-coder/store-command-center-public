"""Secret encryption at rest (app/crypto.py) + the settings PATCH/GET flow."""
import crypto
import db


def test_roundtrip():
    ct = crypto.enc("super-secret-token")
    assert crypto.is_encrypted(ct)
    assert ct != "super-secret-token"
    assert crypto.dec(ct) == "super-secret-token"


def test_dec_passthrough_on_plaintext():
    # legacy plaintext / non-secret values must pass through unchanged
    assert crypto.dec("plain-value") == "plain-value"
    assert crypto.dec("") == ""
    assert crypto.dec(None) is None


def test_enc_noop_on_empty_and_double_encrypt():
    assert crypto.enc("") == ""
    assert crypto.enc(None) is None
    once = crypto.enc("x")
    assert crypto.enc(once) == once  # already-encrypted is not re-wrapped


def test_dec_secrets_only_touches_secret_keys():
    d = {"printify_key": crypto.enc("pk_live"), "store_name": "My Shop", "default_steps": "20"}
    out = crypto.dec_secrets(d)
    assert out["printify_key"] == "pk_live"
    assert out["store_name"] == "My Shop"      # untouched
    assert out["default_steps"] == "20"


def test_migration_encrypts_plaintext_secret():
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('hf_token','hf_PLAINTEXT')")
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('store_name','Not A Secret')")
    conn.commit(); conn.close()

    crypto.migrate_encrypt_secrets(db.get_conn)

    conn = db.get_conn()
    hf = conn.execute("SELECT value FROM settings WHERE key='hf_token'").fetchone()["value"]
    sn = conn.execute("SELECT value FROM settings WHERE key='store_name'").fetchone()["value"]
    conn.close()
    assert crypto.is_encrypted(hf), "secret should be encrypted at rest after migration"
    assert crypto.dec(hf) == "hf_PLAINTEXT"
    assert sn == "Not A Secret", "non-secret must stay plaintext"


def test_settings_patch_encrypts_and_get_decrypts(client):
    # PATCH a secret via the API
    r = client.patch("/api/settings", json={"printify_key": "pk_test_123", "store_name": "Shop X"})
    assert r.status_code < 400, r.text

    # raw DB value must be ENCRYPTED
    conn = db.get_conn()
    raw = conn.execute("SELECT value FROM settings WHERE key='printify_key'").fetchone()["value"]
    conn.close()
    assert crypto.is_encrypted(raw), f"printify_key stored plaintext: {raw!r}"

    # GET must DECRYPT for the UI
    got = client.get("/api/settings").json()
    assert got["printify_key"] == "pk_test_123"
    assert got["store_name"] == "Shop X"

    # and the in-process getter decrypts too
    import deps
    assert deps.get_setting("printify_key") == "pk_test_123"
