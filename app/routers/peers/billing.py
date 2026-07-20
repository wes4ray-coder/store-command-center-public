"""Owner-facing peer-compute billing: set the price, set the caps, read the ledger
and the observed market.

Session-authenticated (the node's OWNER only) — a peer key can never reach these
paths (the auth middleware only exempts /api/peers/rpc/*).

ROUTE ORDER MATTERS: these literal `/api/peers/billing/...` paths are registered
BEFORE api.py's `/api/peers/{pid}/config`, otherwise "billing" would be eaten as
a {pid} and 422 on int parsing. See __init__.py's import order.
"""
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional

from deps import get_conn

import jellycoin_extra as jx

from ._base import router


def _set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()


@router.get("/api/peers/billing/config")
def billing_config():
    """Everything the price panel needs, plus the defaults so the UI can say what
    "unset" means."""
    import jellycoin
    from deps import get_setting
    u = jellycoin.UNIT
    caps = jx.peer_caps()
    rates = jx.peer_token_rates()
    fiat = get_setting(jx.PEER_FIAT_REF_KEY)
    return {
        "symbol": jellycoin.SYMBOL,
        "billing": jx.peer_billing_enabled(),
        "billing_toggle": str(get_setting(jx.PEER_BILLING_KEY) or "1") in ("1", "true", "on"),
        "token_billing": str(get_setting(jx.PEER_TOKEN_BILLING_KEY) or "0") in ("1", "true", "on"),
        "mode": jx.peer_billing_mode(),
        "mode_setting": str(get_setting(jx.PEER_MODE_KEY) or "job"),
        "price_per_1k_completion_jly": rates["completion"] / u,
        "price_per_1k_prompt_jly": rates["prompt"] / u,
        "price_per_llm_job_jly": jx.peer_job_price("llm") / u,
        "tolerance": jx.peer_tolerance(),
        "cap_job_jly": caps["job"] / u,
        "cap_peer_day_jly": caps["peer_day"] / u,
        "cap_day_jly": caps["day"] / u,
        "fiat_ref_usd_per_jly": fiat or "",
        "flag_threshold": jx.PEER_FLAG_THRESHOLD,
        "chars_per_token": jx.CHARS_PER_TOKEN,
        "defaults": {"price_per_1k_completion_jly": jx.PEER_COMPLETION_PRICE_DEFAULT,
                     "price_per_1k_prompt_jly": jx.PEER_PROMPT_PRICE_DEFAULT,
                     "tolerance": jx.PEER_TOLERANCE_DEFAULT,
                     "cap_job_jly": jx.PEER_CAP_JOB_DEFAULT,
                     "cap_peer_day_jly": jx.PEER_CAP_PEER_DAY_DEFAULT,
                     "cap_day_jly": jx.PEER_CAP_DAY_DEFAULT},
        "quote": jx.peer_price_quote(),
    }


class BillingConfigIn(BaseModel):
    billing: Optional[bool] = None                    # master on/off
    token_billing: Optional[bool] = None              # the per-token gate (default OFF)
    mode: Optional[str] = None                        # job | token
    price_per_1k_completion_jly: Optional[float] = None
    price_per_1k_prompt_jly: Optional[float] = None
    price_per_llm_job_jly: Optional[float] = None     # legacy flat fee (kept working)
    tolerance: Optional[float] = None
    cap_job_jly: Optional[float] = None
    cap_peer_day_jly: Optional[float] = None
    cap_day_jly: Optional[float] = None
    fiat_ref_usd_per_jly: Optional[str] = None        # the OWNER'S assumption, never a quote


@router.post("/api/peers/billing/config")
def set_billing_config(body: BillingConfigIn):
    if body.mode is not None and body.mode not in ("job", "token"):
        raise HTTPException(400, "mode must be 'job' or 'token'")
    for val, key in ((body.billing, jx.PEER_BILLING_KEY),
                     (body.token_billing, jx.PEER_TOKEN_BILLING_KEY)):
        if val is not None:
            _set_setting(key, "1" if val else "0")
    if body.mode is not None:
        _set_setting(jx.PEER_MODE_KEY, body.mode)
    for val, key in ((body.price_per_1k_completion_jly, jx.PEER_COMPLETION_PRICE_KEY),
                     (body.price_per_1k_prompt_jly, jx.PEER_PROMPT_PRICE_KEY),
                     (body.price_per_llm_job_jly, jx.PEER_PRICE_KEY),
                     (body.cap_job_jly, jx.PEER_CAP_JOB_KEY),
                     (body.cap_peer_day_jly, jx.PEER_CAP_PEER_DAY_KEY),
                     (body.cap_day_jly, jx.PEER_CAP_DAY_KEY)):
        if val is not None:
            if val < 0:
                raise HTTPException(400, "prices and caps cannot be negative")
            _set_setting(key, val)
    if body.tolerance is not None:
        if body.tolerance < 1.0:
            raise HTTPException(400, "tolerance must be >= 1.0 (1.0 = pay only what we counted)")
        _set_setting(jx.PEER_TOLERANCE_KEY, body.tolerance)
    if body.fiat_ref_usd_per_jly is not None:
        v = (body.fiat_ref_usd_per_jly or "").strip()
        if v:
            try:
                float(v)
            except ValueError:
                raise HTTPException(400, "fiat reference must be a number (USD per JLY) or blank")
        _set_setting(jx.PEER_FIAT_REF_KEY, v)
    return {"ok": True, **billing_config()}


@router.get("/api/peers/billing/ledger")
def billing_ledger(limit: int = 60, peer: Optional[str] = None):
    """Per-job metering history + per-peer running balances and discrepancy flags."""
    return {"ok": True, **jx.peer_ledger(limit, peer)}


@router.get("/api/peers/billing/cost-basis")
def cost_basis():
    """WHY the default price is what it is: measured throughput and power on this
    node's own GPU, the electricity rate (a setting — never invented here), the
    energy floor that falls out of them, and the JLY-native mining opportunity
    cost that actually sets the default."""
    return {"ok": True, **jx.compute_cost_basis(),
            "current_price_jly_per_1k": jx.peer_token_rates()["completion"] / 1_000_000}


class CostBasisIn(BaseModel):
    tok_per_s: Optional[float] = None
    gpu_watts: Optional[float] = None
    kwh_cost_usd: Optional[float] = None
    margin: Optional[float] = None


@router.post("/api/peers/billing/cost-basis")
def set_cost_basis(body: CostBasisIn):
    """Correct any input the owner knows better than we measured (his real utility
    rate, above all). Recording inputs does NOT change the charged price — it
    changes the DERIVED default and what the panel shows."""
    for val, key in ((body.tok_per_s, jx.COMPUTE_TOKS_KEY),
                     (body.gpu_watts, jx.COMPUTE_WATTS_KEY),
                     (body.kwh_cost_usd, jx.COMPUTE_KWH_KEY),
                     (body.margin, jx.COMPUTE_MARGIN_KEY)):
        if val is not None:
            if val < 0:
                raise HTTPException(400, "cost-basis inputs cannot be negative")
            _set_setting(key, val)
    jx.invalidate_compute_cache()
    return {"ok": True, **cost_basis()}


@router.post("/api/peers/billing/use-derived-price")
def use_derived_price():
    """Adopt the derived break-even as the explicit configured price."""
    basis = jx.compute_cost_basis()
    val = basis["derived_default_jly_per_1k"]
    if val is None:
        raise HTTPException(400, "No derived price yet — " + (basis["mining"].get("why") or
                            "not enough chain data to price against mining."))
    _set_setting(jx.PEER_COMPLETION_PRICE_KEY, val)
    return {"ok": True, "price_per_1k_completion_jly": val, "basis": basis}


class MonetaryIn(BaseModel):
    monetary_mode: Optional[bool] = None       # OFF by default: no fiat figure anywhere
    warning_hidden: Optional[bool] = None      # hides the banner, never the provenance chip
    count_in_net_worth: Optional[bool] = None  # OFF by default


@router.get("/api/peers/billing/monetary")
def monetary_config():
    """Monetary mode + the current rate's PROVENANCE. `valuation` carries no usd
    field at all while monetary mode is off — see jellycoin_extra.jelly_valuation."""
    return {"ok": True,
            "monetary_mode": jx.monetary_mode_on(),
            "warning_hidden": jx.fiat_warning_hidden(),
            "count_in_net_worth": jx.count_in_net_worth(),
            "bases": list(jx.FIAT_BASES), "evidenced_bases": list(jx.EVIDENCED_BASES),
            "rate": jx.current_fiat_rate(),
            "history": jx.fiat_rate_history(20),
            "valuation": jx.jelly_valuation(),
            "boundary": ("A fiat JLY figure can reach: the Peers valuation line and the "
                         "market panel. It can NEVER reach the treasury, safe-to-spend, "
                         "budget income or P&L unless real currency actually changed "
                         "hands (record a settlement below).")}


@router.post("/api/peers/billing/monetary")
def set_monetary_config(body: MonetaryIn):
    for val, key in ((body.monetary_mode, jx.MONETARY_MODE_KEY),
                     (body.warning_hidden, jx.FIAT_WARNING_HIDDEN_KEY),
                     (body.count_in_net_worth, jx.COUNT_IN_NET_WORTH_KEY)):
        if val is not None:
            _set_setting(key, "1" if val else "0")
    return {"ok": True, **monetary_config()}


class FiatRateIn(BaseModel):
    usd_per_jly: float
    basis: str = "owner_assumed"
    ref: Optional[str] = None
    note: Optional[str] = None


@router.post("/api/peers/billing/fiat-rate")
def set_fiat_rate(body: FiatRateIn):
    """Record a rate with its provenance. Recording a rate does NOT move any money —
    it only changes what the JLY line is displayed at."""
    try:
        return {"ok": True, "rate": jx.set_fiat_rate(body.usd_per_jly, body.basis,
                                                     body.ref, body.note),
                "current": jx.current_fiat_rate()}
    except ValueError as e:
        raise HTTPException(400, str(e))


class FiatSettlementIn(BaseModel):
    amount_jly: float
    usd_cents: int
    ref: str                                  # the real-world transaction id
    basis: str = "peer_settlement"
    source: str = "JellyCoin settlement"
    received_at: Optional[str] = None
    note: str = ""


@router.post("/api/peers/billing/fiat-settlement")
def post_fiat_settlement(body: FiatSettlementIn):
    """REAL currency actually received for JLY → posts once to the money ledger
    (paychecks) and records an evidenced rate. Idempotent on `ref`."""
    try:
        return jx.record_fiat_settlement(body.amount_jly, body.usd_cents, body.ref,
                                         basis=body.basis, source=body.source,
                                         received_at=body.received_at, note=body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/peers/billing/market")
def billing_market(limit: int = 40):
    """Observed value of JLY: what it has actually traded for per 1k answer tokens.
    Not an exchange price — see the `note` field, which the UI shows verbatim."""
    return {"ok": True, **jx.peer_market(limit)}
