"""Money math — calc_retail_price(base_cents, margin_pct) -> retail_cents.

These lock in the INTENDED behavior (documented in the app's own pricing help):
retail is rounded up to $X.99 and must still achieve at least the target margin.
They are the guardrail for the planned cleanup of this function.
"""
import pytest
from deps import calc_retail_price


def _dollars(cents):
    return cents / 100.0


def test_doc_example_tshirt():
    # The Settings/pricing help states: T-Shirt base $9.50, 40% margin -> retail $15.99.
    assert calc_retail_price(950, 40) == 1599


@pytest.mark.parametrize("base_cents,margin", [
    (500, 30), (950, 40), (1234, 45), (2000, 50), (799, 35),
    (100, 60), (4999, 40), (250, 25), (1500, 55), (333, 40),
])
def test_ends_in_99(base_cents, margin):
    retail = calc_retail_price(base_cents, margin)
    assert retail % 100 == 99, f"retail {retail} for base={base_cents} margin={margin} should end in .99"


@pytest.mark.parametrize("base_cents,margin", [
    (500, 30), (950, 40), (1234, 45), (2000, 50), (799, 35),
    (100, 60), (4999, 40), (250, 25), (1500, 55),
])
def test_achieves_target_margin(base_cents, margin):
    """Margin is on retail: (retail - base) / retail should be >= the target."""
    retail = calc_retail_price(base_cents, margin)
    achieved = (retail - base_cents) / retail
    assert achieved >= margin / 100 - 1e-9, (
        f"base={base_cents} margin={margin}: got retail {retail}, "
        f"achieved margin {achieved:.3f} < target {margin/100:.3f}"
    )


@pytest.mark.parametrize("base_cents,margin", [
    (500, 30), (950, 40), (2000, 50),
])
def test_retail_above_base(base_cents, margin):
    assert calc_retail_price(base_cents, margin) > base_cents


def test_margin_clamped_high_does_not_crash():
    # margins are clamped to [1, 99]; extreme values must not blow up.
    assert calc_retail_price(1000, 200) % 100 == 99
    assert calc_retail_price(1000, 0) % 100 == 99


def test_higher_margin_never_cheaper():
    """More margin on the same base should never produce a lower retail price."""
    base = 1200
    prices = [calc_retail_price(base, m) for m in (20, 30, 40, 50, 60)]
    assert prices == sorted(prices), f"retail not monotonic in margin: {prices}"


def test_returns_int_cents():
    r = calc_retail_price(950, 40)
    assert isinstance(r, int)
