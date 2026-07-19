"""Cash App rail (cashapp_client + routers/cashapp) — endpoint-level tests.

Locks down:
  • $cashtag link building (normalization, amount forms) — pure, no network.
  • Config: the Square access token is ENCRYPTED AT REST (enc:v1: marker in the
    raw settings row), the $cashtag is validated + normalized.
  • The approval gates: cashapp_request / cashapp_checkout are GATEABLE kinds with
    user toggles (unlike paypal_payout they may be turned off — money-IN only),
    and both actions file prayers instead of acting directly.
  • The blessed executors: a blessed cashapp_request records a cash.app/$tag link;
    a blessed cashapp_checkout calls Square with a prayer-derived idempotency key;
    a failed Square call fails the prayer (and stores no row).
  • QR endpoints serve PNGs for the profile link and stored requests only.

EVERYTHING external (Square) is monkeypatched — no real network / money moves.
"""
import cashapp_client
import db
import world_ops as wo


# ── helpers ──────────────────────────────────────────────────────────────────
def _reset(conn):
    wo.ensure(conn)
    conn.execute("DELETE FROM world_prayers")
    conn.execute("DELETE FROM cashapp_requests")
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES "
                 "('world_ops_automation_mode','review')")
    conn.commit()


def _fresh(client, cashtag="JellyTest", token="sq-test-token"):
    """Blank prayer/request state + a configured cashtag (and optionally Square)."""
    conn = db.get_conn()
    try:
        _reset(conn)
    finally:
        conn.close()
    body = {"cashtag": cashtag}
    if token:
        body.update({"access_token": token, "mode": "sandbox"})
    r = client.post("/api/cashapp/config", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── pure client: $cashtag links ──────────────────────────────────────────────
def test_cashtag_normalization_and_links():
    assert cashapp_client.normalize_cashtag(" $Acme ") == "Acme"
    assert cashapp_client.normalize_cashtag("jelly.now-1") == "jelly.now-1"
    assert cashapp_client.normalize_cashtag("$") == ""
    assert cashapp_client.normalize_cashtag("1badstart") == ""     # must start with a letter
    assert cashapp_client.normalize_cashtag("has space") == ""

    assert cashapp_client.cashtag_link("Acme") == "https://cash.app/$Acme"
    assert cashapp_client.cashtag_link("$Acme", 25) == "https://cash.app/$Acme/25"
    assert cashapp_client.cashtag_link("Acme", 12.34) == "https://cash.app/$Acme/12.34"
    assert cashapp_client.cashtag_link("Acme", 0) == ""        # non-positive amount
    assert cashapp_client.cashtag_link("bad tag", 5) == ""


# ── config: validation + secrets at rest ─────────────────────────────────────
def test_config_normalizes_cashtag_and_encrypts_token(client):
    st = _fresh(client, cashtag="$MyTag", token="super-secret-token")
    assert st["cashtag"] == "MyTag"
    assert st["cashtag_link"] == "https://cash.app/$MyTag"
    assert st["square"]["configured"] is True
    assert st["square"]["mode"] == "sandbox"

    # the RAW settings row must be encrypted (secrets-at-rest), never plaintext
    conn = db.get_conn()
    try:
        raw = conn.execute("SELECT value FROM settings WHERE key='square_access_token'"
                           ).fetchone()["value"]
    finally:
        conn.close()
    assert raw.startswith("enc:v1:"), f"token stored in plaintext: {raw[:30]!r}"
    assert "super-secret-token" not in raw


def test_config_rejects_bad_inputs(client):
    r = client.post("/api/cashapp/config", json={"cashtag": "no spaces allowed"})
    assert r.status_code == 400
    r = client.post("/api/cashapp/config", json={"mode": "livemode"})
    assert r.status_code == 400
    r = client.post("/api/cashapp/config", json={})
    assert r.status_code == 400


# ── gates: present, labeled, and user-toggleable (money-IN, not ALWAYS_GATE) ─
def test_cashapp_gates_have_toggles(client):
    kinds = {g["kind"]: g for g in client.get("/api/world/ops/gates").json()["kinds"]}
    assert "cashapp_request" in kinds and "cashapp_checkout" in kinds
    assert kinds["cashapp_request"]["gated"] is True     # default ON

    # unlike paypal_payout these gates CAN be toggled off (receive-only money-in)…
    r = client.post("/api/world/ops/gates", json={"key": "cashapp_request", "on": False})
    assert r.status_code == 200, r.text
    assert "cashapp_request" not in wo.gated_kinds()
    # …and back on
    r = client.post("/api/world/ops/gates", json={"key": "cashapp_request", "on": True})
    assert r.status_code == 200
    assert "cashapp_request" in wo.gated_kinds()


# ── $cashtag request flow: prayer → bless → link + QR ────────────────────────
def test_request_requires_cashtag(client):
    _fresh(client, token="")
    conn = db.get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('cashapp_cashtag','')")
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/cashapp/request", json={"amount_cents": 500})
    assert r.status_code == 400 and "cashtag" in r.text.lower()


def test_request_files_gated_prayer_then_blessing_creates_link(client):
    _fresh(client)
    r = client.post("/api/cashapp/request", json={"amount_cents": 1234, "note": "deck deposit"})
    assert r.status_code == 200, r.text
    p = r.json()["prayer"]
    assert p["kind"] == "cashapp_request"
    assert p["status"] == "pending"          # review mode + gate ON → waits for blessing
    assert p["cost_cents"] == 0              # money-IN draws no budget

    # nothing exists until blessed
    assert client.get("/api/cashapp/requests").json()["requests"] == []

    r = client.post(f"/api/world/ops/prayers/{p['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["prayer"]["status"] == "done"

    reqs = client.get("/api/cashapp/requests").json()["requests"]
    assert len(reqs) == 1
    req = reqs[0]
    assert req["kind"] == "cashtag"
    assert req["url"] == "https://cash.app/$JellyTest/12.34"
    assert req["amount_cents"] == 1234
    assert req["prayer_id"] == p["id"]

    # QR endpoints serve PNGs (profile + stored request)
    r = client.get(f"/api/cashapp/requests/{req['id']}/qr")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    r = client.get("/api/cashapp/qr")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    # never arbitrary data — unknown ids 404
    assert client.get("/api/cashapp/requests/999999/qr").status_code == 404


# ── Square checkout flow: prayer → bless → Square call (mocked) ──────────────
def test_checkout_requires_square_config(client):
    _fresh(client, token="")
    conn = db.get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('square_access_token','')")
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/cashapp/checkout", json={"amount_cents": 500})
    assert r.status_code == 400 and "square" in r.text.lower()


def test_checkout_blessing_calls_square_idempotently(client, monkeypatch):
    _fresh(client)
    captured = {}

    def _fake_link(cfg, amount_cents, name="Payment", note="", idempotency_key=None):
        captured.update(cfg=cfg, amount=amount_cents, key=idempotency_key)
        return {"ok": True, "url": "https://square.link/u/FAKE", "link_id": "L1", "order_id": "O1"}

    monkeypatch.setattr(cashapp_client, "create_payment_link", _fake_link)

    r = client.post("/api/cashapp/checkout",
                    json={"amount_dollars": 20, "note": "invoice", "name": "Deck job"})
    assert r.status_code == 200, r.text
    p = r.json()["prayer"]
    assert p["kind"] == "cashapp_checkout" and p["status"] == "pending"
    assert captured == {}                      # filing the prayer must NOT call Square

    r = client.post(f"/api/world/ops/prayers/{p['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["prayer"]["status"] == "done"
    assert captured["amount"] == 2000
    assert captured["key"] == f"prayer-{p['id']}"    # retry-safe: Square dedupes by prayer
    assert captured["cfg"]["access_token"] == "sq-test-token"   # decrypted for the call

    reqs = client.get("/api/cashapp/requests").json()["requests"]
    assert len(reqs) == 1 and reqs[0]["kind"] == "checkout"
    assert reqs[0]["url"] == "https://square.link/u/FAKE"
    assert reqs[0]["link_id"] == "L1"


def test_checkout_square_failure_fails_prayer_and_stores_nothing(client, monkeypatch):
    _fresh(client)
    monkeypatch.setattr(cashapp_client, "create_payment_link",
                        lambda *a, **k: {"ok": False, "error": "auth failed (401)"})
    p = client.post("/api/cashapp/checkout", json={"amount_cents": 500}).json()["prayer"]
    r = client.post(f"/api/world/ops/prayers/{p['id']}/approve")
    assert r.status_code == 200
    assert r.json()["prayer"]["status"] == "failed"
    assert client.get("/api/cashapp/requests").json()["requests"] == []


# ── status + verify plumbing ─────────────────────────────────────────────────
def test_status_reports_gates_and_pending(client):
    _fresh(client)
    client.post("/api/cashapp/request", json={"amount_cents": 100})
    st = client.get("/api/cashapp/status").json()
    assert st["gates"] == {"cashapp_request": True, "cashapp_checkout": True}
    assert st["pending_prayers"] == 1
    assert st["cashtag"] == "JellyTest"


def test_verify_without_token_is_clean_error(client):
    _fresh(client, token="")
    conn = db.get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('square_access_token','')")
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/cashapp/verify")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False and "not configured" in (body["error"] or "")
