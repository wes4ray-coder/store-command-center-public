"""Per-token peer compute billing — "you only pay for the answers".

Covers the price model (per 1k COMPLETION tokens, prompt free by default), the
rounding rule (never in the counterparty's favour), the anti-cheat rules (we
count the answer ourselves and refuse to pay above our own count × tolerance),
the owner's three hard caps (clean refusal, never a partial charge), settlement
atomicity, the billing toggle, backward compatibility with a per-job peer, and
the monetary-mode boundary (an ASSUMED fiat rate can never touch real money).

No real JLY moves: jellycoin.transfer is monkeypatched everywhere a settlement
would otherwise hit the chain.
"""
import pytest

import jellycoin
import jellycoin_extra as jx

UNIT = jellycoin.UNIT


# ── fixtures / helpers ───────────────────────────────────────────────────────
def _set(key, value):
    from deps import get_conn
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()


@pytest.fixture
def transfers(monkeypatch):
    """Record every transfer instead of moving coin."""
    seen = []
    monkeypatch.setattr(jellycoin, "transfer",
                        lambda frm, dst, amt, **k: seen.append((frm, dst, amt)) or {"ok": True})
    return seen


@pytest.fixture
def token_mode():
    """Token metering ON at a known price, generous caps, default tolerance."""
    _set(jx.PEER_BILLING_KEY, "1")
    _set(jx.PEER_TOKEN_BILLING_KEY, "1")
    _set(jx.PEER_MODE_KEY, "token")
    _set(jx.PEER_COMPLETION_PRICE_KEY, "1.0")     # 1 JLY per 1k answer tokens
    _set(jx.PEER_PROMPT_PRICE_KEY, "0")
    _set(jx.PEER_TOLERANCE_KEY, str(jx.PEER_TOLERANCE_DEFAULT))
    _set(jx.PEER_CAP_JOB_KEY, "1000")
    _set(jx.PEER_CAP_PEER_DAY_KEY, "100000")
    _set(jx.PEER_CAP_DAY_KEY, "100000")
    yield
    _set(jx.PEER_TOKEN_BILLING_KEY, "0")          # leave the suite as we found it
    _set(jx.PEER_MODE_KEY, "job")
    _set(jx.PEER_BILLING_KEY, "1")


def _rows(peer):
    return [r for r in jx.peer_ledger(200)["rows"] if r["peer"] == f"peer:{peer}"]


def _today_total():
    from deps import get_conn
    conn = get_conn()
    try:
        return jx._spent_today(conn, None)
    finally:
        conn.close()


# ── the price model ──────────────────────────────────────────────────────────
def test_price_is_per_1k_completion_tokens(token_mode):
    rates = jx.peer_token_rates()
    assert rates["completion"] == UNIT and rates["prompt"] == 0
    # 500 answer tokens at 1 JLY/1k = 0.5 JLY
    assert jx.token_cost(0, 500, rates, "earned") == UNIT // 2
    assert jx.token_cost(0, 2000, rates, "earned") == 2 * UNIT


def test_prompt_tokens_are_free_by_default(token_mode):
    rates = jx.peer_token_rates()
    # a huge prompt with a tiny answer costs only the answer
    assert jx.token_cost(1_000_000, 100, rates, "earned") == jx.token_cost(0, 100, rates, "earned")


def test_prompt_rate_is_settable_without_a_schema_change(token_mode):
    _set(jx.PEER_PROMPT_PRICE_KEY, "0.5")
    rates = jx.peer_token_rates()
    assert rates["prompt"] == UNIT // 2
    assert jx.token_cost(1000, 1000, rates, "earned") == UNIT + UNIT // 2
    _set(jx.PEER_PROMPT_PRICE_KEY, "0")


def test_rounding_never_favours_the_counterparty(token_mode):
    """Rule: inbound (we EARN) rounds UP to the next ujly, outbound (we SPEND)
    rounds DOWN. The bias is at most 1 ujly and always toward this node."""
    rates = {"completion": 1, "prompt": 0}        # 1 ujly per 1k → sub-ujly amounts
    assert jx.token_cost(0, 1, rates, "earned") == 1      # 0.001 ujly → 1
    assert jx.token_cost(0, 1, rates, "spent") == 0       # 0.001 ujly → 0
    exact = {"completion": UNIT, "prompt": 0}
    assert jx.token_cost(0, 1000, exact, "earned") == jx.token_cost(0, 1000, exact, "spent") == UNIT


def test_local_token_estimate_is_the_documented_approximation():
    assert jx.estimate_tokens("") == 0
    assert jx.estimate_tokens("x" * 400) == 100          # ceil(chars / 4)
    assert jx.estimate_tokens("x" * 401) == 101


# ── metering + settlement ────────────────────────────────────────────────────
def test_earned_settlement_charges_the_peer_and_records_the_row(token_mode, transfers):
    r = jx.peer_settle_tokens("payer-pal", "earned", model="m", prompt_tokens=900,
                              completion_tokens=1500, reported=True)
    assert r["billed"] and r["amount"] == UNIT + UNIT // 2
    assert transfers == [("peer:payer-pal", jellycoin.COMPANY, r["amount"])]
    row = _rows("payer-pal")[0]
    assert row["status"] == "settled" and row["direction"] == "earned"
    assert row["completion_tokens"] == 1500 and row["prompt_tokens"] == 900
    assert row["reported"] == 1 and row["rate_completion_ujly_1k"] == UNIT


def test_estimated_counts_are_marked_not_silently_exact(token_mode, transfers):
    jx.peer_settle_tokens("est-pal", "earned", completion_tokens=1000, reported=False)
    assert _rows("est-pal")[0]["reported"] == 0


def test_billing_off_charges_nothing(token_mode, transfers):
    _set(jx.PEER_BILLING_KEY, "0")
    r = jx.peer_settle_tokens("free-pal", "earned", completion_tokens=99999)
    assert r["billed"] is False and r["reason"] == "billing off"
    assert transfers == [] and _rows("free-pal") == []


def test_token_meter_is_off_until_toggled_on():
    """House rule: the gate ships with a toggle, and it defaults OFF so an upgrade
    never starts metering anybody by surprise."""
    _set(jx.PEER_MODE_KEY, "token")
    _set(jx.PEER_TOKEN_BILLING_KEY, "0")
    assert jx.peer_billing_mode() == "job"
    _set(jx.PEER_TOKEN_BILLING_KEY, "1")
    assert jx.peer_billing_mode() == "token"
    _set(jx.PEER_MODE_KEY, "job")
    _set(jx.PEER_TOKEN_BILLING_KEY, "0")


# ── anti-cheat: our own count wins ───────────────────────────────────────────
def test_over_reporting_peer_is_billed_down_to_our_own_count(token_mode, transfers):
    """They claim 10,000 answer tokens; we counted 1,000 ourselves. Tolerance 1.25
    → we pay for 1,250, log the ratio, and never pay their number."""
    r = jx.peer_settle_tokens("liar-pal", "spent", completion_tokens=10_000,
                              own_estimate=1_000, reported=True)
    assert r["amount"] == int(1250 * UNIT / 1000)
    assert r["discrepancy_ratio"] == 10.0
    row = _rows("liar-pal")[0]
    assert row["reported_completion"] == 10_000 and row["completion_tokens"] == 1250
    assert transfers[0][2] == r["amount"] < 10 * UNIT


def test_honest_report_inside_tolerance_is_paid_as_reported(token_mode, transfers):
    r = jx.peer_settle_tokens("honest-pal", "spent", completion_tokens=1050,
                              own_estimate=1000, reported=True)
    assert r["discrepancy_ratio"] is None
    assert _rows("honest-pal")[0]["completion_tokens"] == 1050


def test_repeat_over_reporting_flags_the_peer_but_never_auto_bans(token_mode, transfers):
    for _ in range(jx.PEER_FLAG_THRESHOLD):
        jx.peer_settle_tokens("repeat-pal", "spent", completion_tokens=9000, own_estimate=100)
    bal = [b for b in jx.peer_ledger(200)["balances"] if b["peer"] == "peer:repeat-pal"][0]
    assert bal["discrepancies"] >= jx.PEER_FLAG_THRESHOLD and bal["flagged"] is True
    # flagged only — the peer is still approved and still billable (owner decides)
    assert jx.peer_settle_tokens("repeat-pal", "spent", completion_tokens=10,
                                 own_estimate=10)["billed"] is True


def test_advertised_price_is_honoured_not_a_post_hoc_one(token_mode, transfers):
    """We settle at the rate quoted BEFORE the job; a provider that hikes its price
    mid-flight cannot bill the new rate for already-quoted work."""
    quoted = dict(jx.peer_token_rates())                 # 1 JLY / 1k
    _set(jx.PEER_COMPLETION_PRICE_KEY, "100")            # they hike it 100×
    r = jx.peer_settle_tokens("hiker-pal", "spent", completion_tokens=1000,
                              own_estimate=1000, quoted_rates=quoted)
    assert r["amount"] == UNIT                            # the quoted price, not 100 JLY
    _set(jx.PEER_COMPLETION_PRICE_KEY, "1.0")


# ── the owner's hard caps ────────────────────────────────────────────────────
def test_per_job_cap_blocks_cleanly_with_no_partial_charge(token_mode, transfers):
    _set(jx.PEER_CAP_JOB_KEY, "2")                       # 2 JLY max per job
    r = jx.peer_settle_tokens("whale-pal", "spent", completion_tokens=50_000,
                              own_estimate=50_000)
    assert r["billed"] is False and r["blocked"] and r["cap"] == "job"
    assert r["amount"] == 0 and transfers == []          # not even a partial transfer
    row = _rows("whale-pal")[0]
    assert row["status"] == "blocked" and row["amount_ujly"] == 0
    _set(jx.PEER_CAP_JOB_KEY, "1000")


def test_per_peer_daily_cap_blocks_cleanly(token_mode, transfers):
    _set(jx.PEER_CAP_PEER_DAY_KEY, "3")
    for _ in range(3):                                    # 1 JLY each → at the ceiling
        assert jx.peer_settle_tokens("daily-pal", "spent", completion_tokens=1000,
                                     own_estimate=1000)["billed"] is True
    r = jx.peer_settle_tokens("daily-pal", "spent", completion_tokens=1000, own_estimate=1000)
    assert r["billed"] is False and r["cap"] == "peer_day" and r["amount"] == 0
    assert len(transfers) == 3
    _set(jx.PEER_CAP_PEER_DAY_KEY, "100000")


def test_global_daily_cap_blocks_cleanly(token_mode, transfers):
    _set(jx.PEER_CAP_DAY_KEY, str((_today_total() + UNIT) / UNIT))   # room for exactly 1 JLY
    assert jx.peer_settle_tokens("g1-pal", "spent", completion_tokens=1000,
                                 own_estimate=1000)["billed"] is True
    r = jx.peer_settle_tokens("g2-pal", "spent", completion_tokens=1000, own_estimate=1000)
    assert r["billed"] is False and r["cap"] == "day" and r["amount"] == 0
    assert len(transfers) == 1
    _set(jx.PEER_CAP_DAY_KEY, "100000")


# ── atomicity ────────────────────────────────────────────────────────────────
def test_a_failed_transfer_never_leaves_a_paid_row(token_mode, monkeypatch):
    def boom(*a, **k):
        raise ValueError("insufficient funds: treasury has 0.00 JLY")
    monkeypatch.setattr(jellycoin, "transfer", boom)
    r = jx.peer_settle_tokens("broke-us", "spent", completion_tokens=1000, own_estimate=1000)
    assert r["billed"] is False
    row = _rows("broke-us")[0]
    assert row["status"] == "failed" and row["amount_ujly"] == 0


def test_a_successful_transfer_always_has_a_settled_row(token_mode, transfers):
    r = jx.peer_settle_tokens("atomic-pal", "earned", completion_tokens=1000)
    assert len(transfers) == 1
    rows = _rows("atomic-pal")
    assert len(rows) == 1 and rows[0]["status"] == "settled"
    assert rows[0]["amount_ujly"] == transfers[0][2] == r["amount"]


def test_a_broke_inbound_peer_is_comped_not_recorded_as_paid(token_mode, monkeypatch):
    monkeypatch.setattr(jellycoin, "transfer",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("insufficient funds")))
    r = jx.peer_settle_tokens("skint-pal", "earned", completion_tokens=1000)
    assert r["billed"] is False and r["reason"] == "comped"
    row = _rows("skint-pal")[0]
    assert row["status"] == "comped" and row["amount_ujly"] == 0


# ── backward compatibility ───────────────────────────────────────────────────
def test_a_per_job_mode_peer_still_bills_the_flat_fee(transfers):
    _set(jx.PEER_MODE_KEY, "job")
    _set(jx.PEER_TOKEN_BILLING_KEY, "0")
    assert jx.peer_billing_mode() == "job"
    assert jx.peer_job_charge("legacy-pal", "llm")["amount"] == jx.peer_job_price("llm")
    assert transfers[0][0] == "peer:legacy-pal"
    # and the quote we advertise says so, so their side settles the same way
    assert jx.peer_price_quote()["mode"] == "job"


def test_quote_advertises_both_price_models(client, token_mode):
    q = jx.peer_price_quote()
    assert q["mode"] == "token"
    assert q["price_per_1k_completion_jly"] == 1.0 and q["price_per_1k_prompt_jly"] == 0.0
    assert q["price_per_llm_job_jly"] > 0        # legacy field still advertised
    assert "quoted_at" in q


def test_rpc_price_route_is_peer_key_gated(client):
    from test_peers import _raw, _pair
    raw = _raw()
    pid, key = _pair(client, raw, name="quote-pal")
    assert raw.get("/api/peers/rpc/price").status_code == 401
    client.post(f"/api/peers/{pid}/approve")
    r = raw.get("/api/peers/rpc/price", headers={"X-Peer-Key": key})
    assert r.status_code == 200 and r.json()["mode"] in ("job", "token")


# ── owner-facing API ─────────────────────────────────────────────────────────
def test_billing_routes_are_not_eaten_by_the_pid_route(client):
    """/api/peers/billing/config must not be parsed as /api/peers/{pid}/config."""
    assert client.get("/api/peers/billing/config").status_code == 200
    r = client.post("/api/peers/billing/config", json={"price_per_1k_completion_jly": 2.5})
    assert r.status_code == 200 and r.json()["price_per_1k_completion_jly"] == 2.5
    client.post("/api/peers/billing/config", json={"price_per_1k_completion_jly": 1.0})


def test_config_rejects_nonsense(client):
    assert client.post("/api/peers/billing/config", json={"mode": "barter"}).status_code == 400
    assert client.post("/api/peers/billing/config", json={"tolerance": 0.5}).status_code == 400
    assert client.post("/api/peers/billing/config", json={"cap_job_jly": -1}).status_code == 400


def test_market_empty_state_is_honest_about_having_no_trades(client, monkeypatch):
    monkeypatch.setattr(jx, "peer_market", lambda limit=40: {
        "trades": [], "last_trade": None, "observed": None, "enough_data": False})
    m = client.get("/api/peers/billing/market").json()
    assert m["trades"] == [] and m["last_trade"] is None and m["enough_data"] is False


def test_market_reports_last_trade_and_withholds_a_trend_when_thin(token_mode, transfers):
    for _ in range(2):
        jx.peer_settle_tokens("market-pal", "earned", completion_tokens=1000)
    m = jx.peer_market(200)
    assert m["last_trade"]["peer"] == "market-pal"
    assert m["last_trade"]["rate_jly_per_1k"] == 1.0
    assert m["unit"] == "JLY per 1,000 completion tokens"
    assert "not listed on any exchange" in m["note"]
    if len(m["trades"]) < jx.MARKET_MIN_TRADES:
        assert m["enough_data"] is False


# ── monetary mode: the real-money boundary ───────────────────────────────────
def _monetary(client, **kw):
    return client.post("/api/peers/billing/monetary", json=kw).json()


def test_monetary_mode_off_produces_no_fiat_anywhere(client):
    _monetary(client, monetary_mode=False)
    v = jx.jelly_valuation()
    assert v["monetary_mode"] is False
    assert "usd_value" not in v and v["rate"] is None
    assert jx.peer_market(5)["fiat_ref_usd_per_jly"] is None
    m = client.get("/api/peers/billing/monetary").json()
    assert "usd_value" not in m["valuation"]


def test_owner_assumed_rate_carries_its_provenance_chip(client):
    _monetary(client, monetary_mode=True)
    client.post("/api/peers/billing/fiat-rate", json={"usd_per_jly": 0.25, "basis": "owner_assumed"})
    v = jx.jelly_valuation()
    assert v["rate"]["basis"] == "owner_assumed" and v["rate"]["chip"] == "assumed"
    assert "usd_value" in v and "OWNER-ASSUMED" in v["fiat_note"]


def test_hiding_the_warning_does_not_hide_the_provenance_chip(client):
    _monetary(client, monetary_mode=True, warning_hidden=True)
    m = client.get("/api/peers/billing/monetary").json()
    assert m["warning_hidden"] is True
    assert m["valuation"]["chip"] in ("assumed", "evidenced")   # chip survives
    assert m["rate"]["chip"] == "assumed"


def test_an_assumed_rate_never_moves_treasury_safe_to_spend_or_income(client):
    """The hard rule: the budget decides whether groceries are affordable, so a
    self-declared token price must not move it — even with net worth counting on."""
    _monetary(client, monetary_mode=True, count_in_net_worth=True)
    before_period = client.get("/api/budget/period").json()
    before_ledger = client.get("/api/ledger/summary").json()
    client.post("/api/peers/billing/fiat-rate", json={"usd_per_jly": 999999, "basis": "owner_assumed"})
    assert client.get("/api/budget/period").json()["safe_to_spend_cents"] == \
        before_period["safe_to_spend_cents"]
    assert client.get("/api/ledger/summary").json() == before_ledger
    # the valuation line itself is allowed to show it — as its OWN asset class
    v = jx.jelly_valuation()
    assert v["counts_in_net_worth"] is True and v["posts_to_real_money"] is False
    _monetary(client, count_in_net_worth=False, monetary_mode=False)


def test_an_assumed_rate_may_not_post_to_the_money_ledger(client):
    with pytest.raises(ValueError):
        jx.record_fiat_settlement(10, 500, "ref-assumed", basis="owner_assumed")
    r = client.post("/api/peers/billing/fiat-settlement",
                    json={"amount_jly": 10, "usd_cents": 500, "ref": "r1", "basis": "owner_assumed"})
    assert r.status_code == 400


def test_a_real_settlement_posts_once_and_only_once(client):
    before = client.get("/api/ledger/summary").json()["month"]["income_cents"]
    body = {"amount_jly": 100, "usd_cents": 2500, "ref": "cashapp-tx-42",
            "basis": "peer_settlement", "source": "buddy JLY buyout"}
    a = client.post("/api/peers/billing/fiat-settlement", json=body).json()
    assert a["duplicate"] is False and a["usd_per_jly"] == 0.25
    b = client.post("/api/peers/billing/fiat-settlement", json=body).json()
    assert b["duplicate"] is True and b["paycheck_id"] == a["paycheck_id"]
    assert client.get("/api/ledger/summary").json()["month"]["income_cents"] == before + 2500
    rate = jx.current_fiat_rate()
    assert rate["basis"] == "peer_settlement" and rate["chip"] == "evidenced"
    assert rate["ref"] == "cashapp-tx-42"


def test_evidenced_basis_requires_a_reference(client):
    with pytest.raises(ValueError):
        jx.set_fiat_rate(0.3, "peer_settlement")
    assert jx.set_fiat_rate(0.3, "peer_settlement", ref="tx-1")["ok"]


# ── the grounded default price (derived, not a placeholder) ──────────────────
@pytest.fixture
def cost_inputs():
    """Known cost-basis inputs so the arithmetic is checkable by hand."""
    _set(jx.COMPUTE_TOKS_KEY, "31.2")
    _set(jx.COMPUTE_WATTS_KEY, "158")
    _set(jx.COMPUTE_KWH_KEY, "0.15")
    _set(jx.COMPUTE_MARGIN_KEY, "1.0")
    jx.invalidate_compute_cache()
    yield
    jx.invalidate_compute_cache()


def _fake_chain(monkeypatch, mean_gap=64.6, reward_jly=50.0):
    monkeypatch.setattr(jx, "mining_rate", lambda: {
        "enough_data": True, "blocks": 199, "mean_block_seconds": mean_gap,
        "median_block_seconds": 36.0, "block_reward_jly": reward_jly,
        "jly_per_second": reward_jly / mean_gap})
    jx.invalidate_compute_cache()


def test_energy_floor_math_is_watts_times_seconds_over_kwh(cost_inputs):
    b = jx.compute_cost_basis()
    assert b["seconds_per_1k_tokens"] == round(1000 / 31.2, 2)      # 32.05 s
    # 158 W × 32.051 s = 5064 J = 0.0014067 kWh
    assert b["kwh_per_1k_tokens"] == pytest.approx(158 * (1000 / 31.2) / 3_600_000, rel=1e-9)
    assert b["energy_floor_usd_per_1k"] == pytest.approx(0.000211, abs=1e-6)


def test_changing_the_kwh_setting_moves_the_floor(cost_inputs):
    before = jx.compute_cost_basis()["energy_floor_usd_per_1k"]
    _set(jx.COMPUTE_KWH_KEY, "0.30")                                # double the rate
    after = jx.compute_cost_basis()["energy_floor_usd_per_1k"]
    assert after == pytest.approx(before * 2, rel=1e-9)
    _set(jx.COMPUTE_KWH_KEY, "0")                                   # free power → zero floor
    assert jx.compute_cost_basis()["energy_floor_usd_per_1k"] == 0
    _set(jx.COMPUTE_KWH_KEY, "0.15")


def test_electricity_price_is_a_labelled_placeholder_not_a_researched_figure(cost_inputs):
    b = jx.compute_cost_basis()
    assert b["inputs"]["kwh_cost_usd"]["provenance"] == "placeholder"
    assert b["inputs"]["tok_per_s"]["provenance"] == "measured"
    assert b["inputs"]["gpu_watts"]["provenance"] == "measured"
    assert any("amortisation" in x for x in b["excluded"])          # excluded, and said so


def test_slower_hardware_costs_more_per_1k_tokens(cost_inputs):
    fast = jx.compute_cost_basis()["energy_floor_usd_per_1k"]
    _set(jx.COMPUTE_TOKS_KEY, "15.6")                               # half the throughput
    slow = jx.compute_cost_basis()["energy_floor_usd_per_1k"]
    assert slow == pytest.approx(fast * 2, rel=1e-9)
    _set(jx.COMPUTE_TOKS_KEY, "31.2")


def test_default_price_is_the_mining_opportunity_cost(cost_inputs, monkeypatch):
    """The same GPU either mines JLY or answers tokens, so the JLY-native cost of
    an answer is what the miner would have earned meanwhile — no exchange rate."""
    _fake_chain(monkeypatch, mean_gap=64.6, reward_jly=50.0)
    b = jx.compute_cost_basis()
    expected = (50.0 / 64.6) * (1000 / 31.2)                        # ≈ 24.81 JLY
    assert b["opportunity_cost_jly_per_1k"] == pytest.approx(expected, rel=1e-6)
    assert b["derived_default_jly_per_1k"] == pytest.approx(expected, rel=1e-6)


def test_margin_scales_the_derived_default(cost_inputs, monkeypatch):
    _fake_chain(monkeypatch)
    breakeven = jx.compute_cost_basis()["derived_default_jly_per_1k"]
    _set(jx.COMPUTE_MARGIN_KEY, "2.0")
    jx.invalidate_compute_cache()
    assert jx.compute_cost_basis()["derived_default_jly_per_1k"] == pytest.approx(breakeven * 2, rel=1e-6)
    _set(jx.COMPUTE_MARGIN_KEY, "1.0")


def test_a_faster_chain_makes_compute_more_expensive_in_jly(cost_inputs, monkeypatch):
    _fake_chain(monkeypatch, mean_gap=64.6)
    slow_chain = jx.compute_cost_basis()["derived_default_jly_per_1k"]
    _fake_chain(monkeypatch, mean_gap=32.3)      # blocks twice as often → mining worth more
    assert jx.compute_cost_basis()["derived_default_jly_per_1k"] == pytest.approx(slow_chain * 2, rel=1e-6)


def test_halving_the_block_reward_halves_the_derived_price(cost_inputs, monkeypatch):
    """Reward is read live via jellycoin.block_reward, so emission changes land here
    automatically rather than needing this module edited."""
    _fake_chain(monkeypatch, reward_jly=50.0)
    full = jx.compute_cost_basis()["derived_default_jly_per_1k"]
    _fake_chain(monkeypatch, reward_jly=25.0)
    assert jx.compute_cost_basis()["derived_default_jly_per_1k"] == pytest.approx(full / 2, rel=1e-6)


def test_a_young_chain_refuses_to_derive_and_falls_back(cost_inputs, monkeypatch):
    monkeypatch.setattr(jx, "mining_rate", lambda: {
        "enough_data": False, "blocks": 3, "min_blocks": jx.MINING_MIN_BLOCKS,
        "why": "this chain has not produced enough blocks to read a mining rate from yet"})
    jx.invalidate_compute_cache()
    b = jx.compute_cost_basis()
    assert b["derived_default_jly_per_1k"] is None       # no guess offered
    assert b["opportunity_cost_jly_per_1k"] is None
    assert jx.derived_default_completion_price() == jx.COMPUTE_FALLBACK_PRICE


def test_mining_rate_reads_the_real_chain():
    m = jx.mining_rate()
    assert "enough_data" in m
    if m["enough_data"]:
        assert m["jly_per_second"] > 0 and m["mean_block_seconds"] > 0
    else:
        assert m["blocks"] < jx.MINING_MIN_BLOCKS and m["why"]


def test_an_unset_price_uses_the_derived_default_and_a_set_price_wins(cost_inputs, monkeypatch):
    _fake_chain(monkeypatch)
    derived = jx.compute_cost_basis()["derived_default_jly_per_1k"]
    _set(jx.PEER_COMPLETION_PRICE_KEY, "")                          # unconfigured
    assert jx.peer_token_rates()["completion"] == int(derived * UNIT)
    _set(jx.PEER_COMPLETION_PRICE_KEY, "3.5")                       # owner's choice wins
    assert jx.peer_token_rates()["completion"] == int(3.5 * UNIT)
    _set(jx.PEER_COMPLETION_PRICE_KEY, "1.0")


def test_cost_basis_api_exposes_the_whole_derivation(client):
    b = client.get("/api/peers/billing/cost-basis").json()
    assert b["ok"] and "energy_floor_usd_per_1k" in b and "mining" in b
    assert b["inputs"]["kwh_cost_usd"]["provenance"] == "placeholder"
    assert "current_price_jly_per_1k" in b
    r = client.post("/api/peers/billing/cost-basis", json={"kwh_cost_usd": 0.22})
    assert r.status_code == 200 and r.json()["inputs"]["kwh_cost_usd"]["value"] == 0.22
    assert client.post("/api/peers/billing/cost-basis", json={"gpu_watts": -5}).status_code == 400
    client.post("/api/peers/billing/cost-basis", json={"kwh_cost_usd": 0.15})


def test_use_derived_price_adopts_the_break_even(client, cost_inputs, monkeypatch):
    _fake_chain(monkeypatch)
    r = client.post("/api/peers/billing/use-derived-price").json()
    assert r["ok"] and r["price_per_1k_completion_jly"] > 0
    assert jx.peer_token_rates()["completion"] == int(r["price_per_1k_completion_jly"] * UNIT)
    _set(jx.PEER_COMPLETION_PRICE_KEY, "1.0")


def test_use_derived_price_refuses_when_there_is_nothing_to_derive(client, monkeypatch):
    monkeypatch.setattr(jx, "mining_rate", lambda: {
        "enough_data": False, "blocks": 1, "why": "chain too young"})
    jx.invalidate_compute_cache()
    r = client.post("/api/peers/billing/use-derived-price")
    assert r.status_code == 400 and "too young" in r.json()["detail"]
