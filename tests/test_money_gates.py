"""Endpoint-level tests for the newly-hardened money-path GATES.

The ledger *arithmetic* was already covered (tests/test_ledger.py); the mutation
PATHS — the gate-set endpoint, the PayPal withdraw prayer, the generic-prayer
recipient block, double-approve, and the secret-export gate — had ZERO coverage.
These lock down the fixes:

  H1  a payout carries its REAL amount as cost_cents and cannot be approved past
      the monthly budget cap.
  H2  the irreversible money-out / secret-export gates can never be toggled off,
      and gated_kinds() unions them in regardless of stored toggles.
  H3  paypal_payout/wallet_send/secret_export cannot be filed via the generic
      prayer API; the payout executor always pays the configured OWNER email,
      never a payload-supplied one.
  P1  approving the same prayer twice never double-charges; a failed execution is
      refunded so no phantom debit is left on the ledger.
  H4  the crypto secret backup is gated behind a blessed, single-use prayer.

EVERYTHING external (PayPal) is monkeypatched — no real network / money moves.
The `client` fixture is already authenticated (session cookie from the "store"
first-run password), so every /api/... call rides that auth. Localhost auth-bypass
is irrelevant here: the TestClient logs in for real.
"""
import json

import world_ops as wo
import db
import paypal_client
import routers.world_ops as wo_router


# ── helpers ──────────────────────────────────────────────────────────────────
def _reset(conn):
    """Blank slate: no ledger rows, no prayers, review mode (nothing auto-runs)."""
    wo.ensure(conn)
    conn.execute("DELETE FROM world_ops_ledger")
    conn.execute("DELETE FROM world_prayers")
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES "
                 "('world_ops_automation_mode','review')")
    conn.commit()


def _set(conn, key, val):
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(val)))
    conn.commit()


# ── H2: ALWAYS_GATE is non-toggleable ────────────────────────────────────────
def test_always_gate_cannot_be_turned_off(client):
    for kind in ("paypal_payout", "wallet_send", "secret_export"):
        r = client.post("/api/world/ops/gates", json={"key": kind, "on": False})
        assert r.status_code == 400, f"{kind} off should be rejected, got {r.status_code} {r.text}"
        assert "cannot" in r.text.lower() or "irreversible" in r.text.lower()


def test_always_gate_toggle_on_is_allowed(client):
    # turning the payout gate ON is fine (it's already on) — only OFF is forbidden.
    r = client.post("/api/world/ops/gates", json={"key": "paypal_payout", "on": True})
    assert r.status_code == 200, r.text
    assert r.json()["on"] is True


def test_gated_kinds_always_unions_always_gate(client):
    # Even with EVERY per-kind toggle forced OFF in the DB, the irreversible kinds
    # remain gated — the union is unconditional, not toggle-derived.
    conn = db.get_conn()
    try:
        for kind in ("paypal_payout",):
            _set(conn, f"world_ops_gate_{kind}", "0")
        _set(conn, "world_ops_gate_creations", "0")
    finally:
        conn.close()
    g = wo.gated_kinds()
    assert {"paypal_payout", "wallet_send", "secret_export"} <= g, g


# ── H1: a payout respects the budget cap and carries its real amount ─────────
def test_payout_carries_real_cost_and_is_cap_blocked(client, monkeypatch):
    # No real PayPal call is ever reached (the cap blocks approval first), but stub
    # it anyway so a regression can never leak a network call.
    monkeypatch.setattr(paypal_client, "create_payout",
                        lambda *a, **k: {"ok": True, "batch_id": "x", "status": "PENDING"})

    conn = db.get_conn()
    try:
        _reset(conn)
        wo._ledger(conn, 10000, "fund", "manual")   # +$100 in the wallet
    finally:
        conn.close()

    # configure PayPal so the withdraw endpoint's precondition checks pass
    r = client.post("/api/world/ops/paypal/config",
                    json={"client_id": "cid", "secret": "sec",
                          "mode": "sandbox", "email": "owner@example.com"})
    assert r.status_code == 200, r.text
    # low cap ($5); withdraw $50 — well over the cap but within the wallet balance
    r = client.post("/api/world/ops/config", json={"cap_cents": 500})
    assert r.status_code == 200, r.text

    r = client.post("/api/world/ops/paypal/withdraw", json={"amount_cents": 5000})
    assert r.status_code == 200, r.text
    p = r.json()["prayer"]
    # the REAL amount is on the prayer — a payout can't hide its value as cost 0
    assert p["cost_cents"] == 5000, p
    assert p["status"] == "pending"
    assert p["kind"] == "paypal_payout"
    pid = p["id"]

    # approving is blocked by the cap (can_spend) — no force flag
    r = client.post(f"/api/world/ops/prayers/{pid}/approve")
    assert r.status_code == 400, f"cap should block approve, got {r.status_code} {r.text}"
    assert "cap" in r.text.lower()

    # and NOTHING moved: balance still the original fund, no payout ledger row
    conn = db.get_conn()
    try:
        assert wo.balance_cents(conn) == 10000
        n = conn.execute("SELECT COUNT(*) c FROM world_ops_ledger WHERE kind='payout'").fetchone()["c"]
        assert n == 0
    finally:
        conn.close()


# ── H3: arbitrary recipients / generic-prayer money-out is blocked ───────────
def test_generic_prayer_api_rejects_money_out_kinds(client):
    for kind in ("paypal_payout", "wallet_send", "secret_export"):
        r = client.post("/api/world/ops/prayers", json={"kind": kind, "title": "sneaky"})
        assert r.status_code == 403, f"{kind} via generic API should 403, got {r.status_code} {r.text}"
        assert "dedicated endpoint" in r.text.lower()


def test_payout_executor_ignores_payload_email(client, monkeypatch):
    # The payout must always go to the CONFIGURED owner email, never a payload-supplied
    # recipient an attacker could smuggle into the prayer.
    captured = {}

    def _fake_payout(cfg, amount_dollars, receiver_email, note="", prayer_id=None):
        captured["email"] = receiver_email
        captured["amount"] = amount_dollars
        return {"ok": True, "batch_id": "b1", "status": "PENDING"}

    monkeypatch.setattr(paypal_client, "create_payout", _fake_payout)

    conn = db.get_conn()
    try:
        _reset(conn)
        wo._ledger(conn, 10000, "fund", "manual")           # wallet has $100
        _set(conn, "world_paypal_email", "owner@example.com")
        prayer = {"id": 999, "kind": "paypal_payout",
                  "payload": json.dumps({"amount_cents": 1000,
                                         "email": "attacker@evil.com",  # must be ignored
                                         "note": "x"})}
        res = wo_router._exec_paypal_payout(conn, prayer)
    finally:
        conn.close()

    assert captured["email"] == "owner@example.com", captured
    assert captured["amount"] == 10.0
    assert "b1" in res


# ── P1: double-approve never double-charges ──────────────────────────────────
def test_double_approve_is_idempotent_no_double_charge(client):
    wo.register_executor("test_paid_ok", lambda conn, p: "ok")
    conn = db.get_conn()
    try:
        _reset(conn)
        _set(conn, "world_ops_cap_cents", "100000")     # roomy cap so approve is allowed
        p = wo.pray("test_paid_ok", "paid op", cost_cents=100, conn=conn)
        pid = p["id"]
        assert p["status"] == "pending"
    finally:
        conn.close()

    r1 = client.post(f"/api/world/ops/prayers/{pid}/approve")
    assert r1.status_code == 200, r1.text
    assert r1.json()["prayer"]["status"] == "done"

    r2 = client.post(f"/api/world/ops/prayers/{pid}/approve")
    assert r2.status_code == 400, f"second approve should be rejected, got {r2.status_code}"
    assert "already" in r2.text.lower()

    conn = db.get_conn()
    try:
        spends = conn.execute("SELECT COUNT(*) c FROM world_ops_ledger "
                              "WHERE prayer_id=? AND kind='spend'", (pid,)).fetchone()["c"]
        assert spends == 1, f"double-charged: {spends} spend rows"
        assert wo.balance_cents(conn) == -100    # one $1 debit, nothing funded
    finally:
        conn.close()


def test_approve_after_reject_does_not_charge(client):
    wo.register_executor("test_paid_ok", lambda conn, p: "ok")
    conn = db.get_conn()
    try:
        _reset(conn)
        _set(conn, "world_ops_cap_cents", "100000")
        p = wo.pray("test_paid_ok", "paid op 2", cost_cents=100, conn=conn)
        pid = p["id"]
    finally:
        conn.close()

    r = client.post(f"/api/world/ops/prayers/{pid}/reject")
    assert r.status_code == 200 and r.json()["prayer"]["status"] == "rejected"

    r = client.post(f"/api/world/ops/prayers/{pid}/approve")
    assert r.status_code == 400, r.text

    conn = db.get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM world_ops_ledger WHERE prayer_id=?",
                        (pid,)).fetchone()["c"]
        assert n == 0, "a rejected prayer must never touch the ledger"
    finally:
        conn.close()


# ── P1: a failed execution is refunded (no phantom debit) ────────────────────
def test_failed_execution_is_refunded(client):
    def _boom(conn, p):
        raise RuntimeError("executor exploded")

    wo.register_executor("test_fail_exec", _boom)
    conn = db.get_conn()
    try:
        _reset(conn)
        _set(conn, "world_ops_cap_cents", "100000")
        p = wo.pray("test_fail_exec", "doomed op", cost_cents=100, conn=conn)
        pid = p["id"]
    finally:
        conn.close()

    r = client.post(f"/api/world/ops/prayers/{pid}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["prayer"]["status"] == "failed"

    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT amount_cents, kind FROM world_ops_ledger "
                            "WHERE prayer_id=? ORDER BY id", (pid,)).fetchall()
        kinds = [(row["amount_cents"], row["kind"]) for row in rows]
        assert (-100, "spend") in kinds, kinds
        assert (100, "refund") in kinds, kinds
        # net effect of the failed op on the wallet is zero
        net = sum(row["amount_cents"] for row in rows)
        assert net == 0, f"phantom debit left behind: net={net}"
    finally:
        conn.close()


# ── H4: crypto secret backup is gated behind a blessed, single-use prayer ────
def test_backup_requires_blessed_prayer(client):
    # no prayer_id → 403
    r = client.get("/api/crypto/backup")
    assert r.status_code == 403, r.text
    # a bogus / non-existent prayer_id → 403
    r = client.get("/api/crypto/backup", params={"prayer_id": 999999})
    assert r.status_code == 403, r.text


def test_backup_request_files_gated_secret_export_prayer(client):
    r = client.post("/api/crypto/backup/request")
    assert r.status_code == 200, r.text
    p = r.json()["prayer"]
    assert p["kind"] == "secret_export"
    assert p["status"] == "pending"          # never auto-runs — it's ALWAYS_GATE
    assert p["cost_cents"] == 0
    assert "secret_export" in wo.gated_kinds()


def test_backup_blessed_then_single_use(client):
    # file the export prayer
    p = client.post("/api/crypto/backup/request").json()["prayer"]
    pid = p["id"]

    # unblessed → still 403
    r = client.get("/api/crypto/backup", params={"prayer_id": pid})
    assert r.status_code == 403, r.text

    # bless it (cost 0 → within any cap); executor is the default no-op → status done
    r = client.post(f"/api/world/ops/prayers/{pid}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["prayer"]["status"] in ("approved", "done")

    # first download succeeds
    r = client.get("/api/crypto/backup", params={"prayer_id": pid})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"

    # blessing is single-use — the second attempt is refused
    r = client.get("/api/crypto/backup", params={"prayer_id": pid})
    assert r.status_code == 403, f"blessing must be single-use, got {r.status_code}"
