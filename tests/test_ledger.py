"""God Console budget/ledger math (world_ops.py) — this handles REAL money
(Etsy/Printify spend, PayPal payouts), so lock the arithmetic down."""
import world_ops as wo
import db


def _fresh():
    conn = db.get_conn()
    wo.ensure(conn)
    conn.execute("DELETE FROM world_ops_ledger")
    conn.commit()
    return conn


def test_balance_sums_signed_ledger():
    conn = _fresh()
    wo._ledger(conn, 10000, "fund", "manual")     # +$100 funds
    wo._ledger(conn, -2500, "spend", "etsy")       # -$25 spend
    wo._ledger(conn, 5000, "revenue", "cults3d")   # +$50 revenue
    assert wo.balance_cents(conn) == 12500          # 100 - 25 + 50
    conn.close()


def test_negative_balance_means_owed():
    conn = _fresh()
    wo._ledger(conn, -3000, "spend", "etsy")        # spent $30 postpaid, no funds in
    assert wo.balance_cents(conn) == -3000           # company owes $30
    conn.close()


def test_cycle_spend_counts_only_spends():
    conn = _fresh()
    wo._ledger(conn, 10000, "fund")
    wo._ledger(conn, -2000, "spend")
    wo._ledger(conn, -3000, "spend")
    wo._ledger(conn, 5000, "revenue")               # revenue must NOT count as spend
    assert wo.cycle_spend_cents(conn) == 5000        # only the two spends ($20 + $30)
    conn.close()


def test_can_spend_enforces_monthly_cap():
    conn = _fresh()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('world_ops_cap_cents','2000')")
    conn.commit()
    assert wo.cap_cents() == 2000                    # $20 cap

    assert wo.can_spend(conn, 1500) is True          # nothing spent yet → $15 ok
    wo._ledger(conn, -1500, "spend")                 # now $15 spent this cycle
    assert wo.can_spend(conn, 1000) is False         # 15 + 10 = 25 > 20 → blocked
    assert wo.can_spend(conn, 500) is True           # 15 + 5 = 20 == cap → allowed (boundary)
    assert wo.can_spend(conn, 0) is True             # zero-cost always allowed
    assert wo.can_spend(conn, -50) is True           # negative cost never blocked
    conn.close()


def test_cap_zero_blocks_all_positive_spend():
    conn = _fresh()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('world_ops_cap_cents','0')")
    conn.commit()
    assert wo.can_spend(conn, 1) is False            # cap 0 → any real spend blocked
    assert wo.can_spend(conn, 0) is True
    conn.close()
