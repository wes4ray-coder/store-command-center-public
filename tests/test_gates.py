"""world_ops.gated_kinds — user-toggleable gates + always-on irreversible kinds."""
import world_ops as wo
import db


def _set(key, val):
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, val))
    conn.commit(); conn.close()


def test_defaults_gate_the_expected_kinds():
    for k in ("world_ops_gate_creations", "world_ops_gate_paypal_payout",
              "world_ops_gate_add_software", "world_ops_gate_post_etsy", "world_ops_gate_post_printify"):
        _set(k, wo.DEFAULTS[k])
    g = wo.gated_kinds()
    # per-kind gates default ON
    assert {"paypal_payout", "add_software", "post_etsy", "post_printify"} <= g
    # creations gate default OFF
    assert "publish_wordpress" not in g


def test_creations_toggle_adds_creation_kinds():
    _set("world_ops_gate_creations", "1")
    g = wo.gated_kinds()
    assert wo.CREATION_KINDS <= g
    _set("world_ops_gate_creations", "0")
    assert "publish_wordpress" not in wo.gated_kinds()


def test_per_kind_toggle_off_ungates_it():
    _set("world_ops_gate_add_software", "0")
    assert "add_software" not in wo.gated_kinds()
    _set("world_ops_gate_add_software", "1")
    assert "add_software" in wo.gated_kinds()


def test_irreversible_kinds_never_ungate():
    # ALWAYS_GATE (money-out / secret export) is unioned in regardless of any toggle
    assert wo.ALWAYS_GATE <= wo.gated_kinds()
