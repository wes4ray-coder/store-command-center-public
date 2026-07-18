"""world_sell.sync_revenue — real Etsy sales → treasury revenue (closes the money loop)."""
import world_sell as ws
import world_ops as wo
import db


class _MockEtsy:
    """Stand-in for EtsyClient.get_receipts, honouring the min_created high-water mark."""
    def __init__(self, receipts):
        self._r = receipts

    def get_receipts(self, min_created=0):
        return [r for r in self._r if int(r.get("created", 0)) > int(min_created or 0)]


def _set(conn, key, val):
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, val))
    conn.commit()


def test_sync_ledgers_revenue_and_dedupes():
    conn = db.get_conn(); wo.ensure(conn)
    _set(conn, "world_sell_revenue_sync", "1")
    _set(conn, "world_sell_etsy_rev_hwm", "0")
    base = wo.balance_cents(conn)
    mock = _MockEtsy([
        {"receipt_id": 111, "created": 1000, "total_cents": 2499},
        {"receipt_id": 222, "created": 1100, "total_cents": 1800},
    ])
    r1 = ws.sync_revenue(conn=conn, etsy_client=mock)
    assert r1["ok"] and r1["added"] == 2 and r1["revenue_cents"] == 4299
    assert wo.balance_cents(conn) == base + 4299
    # dedupe: same receipts a second time add nothing (high-water mark + ledger check)
    r2 = ws.sync_revenue(conn=conn, etsy_client=mock)
    assert r2["added"] == 0 and r2["revenue_cents"] == 0
    assert wo.balance_cents(conn) == base + 4299
    conn.close()


def test_sync_respects_disabled_toggle():
    conn = db.get_conn(); wo.ensure(conn)
    _set(conn, "world_sell_revenue_sync", "0")
    try:
        r = ws.sync_revenue(conn=conn,
                            etsy_client=_MockEtsy([{"receipt_id": 333, "created": 5000, "total_cents": 500}]))
        assert r["ok"] is False and r["added"] == 0
    finally:
        _set(conn, "world_sell_revenue_sync", "1")   # restore for other tests (shared DB)
        conn.close()


def test_sync_no_client_is_safe_noop():
    conn = db.get_conn(); wo.ensure(conn)
    _set(conn, "world_sell_revenue_sync", "1")
    # etsy unconfigured in the temp DB → build_etsy_client() returns None → no-op, no crash
    r = ws.sync_revenue(conn=conn, etsy_client=None)
    assert r["ok"] and r["added"] == 0
    conn.close()
