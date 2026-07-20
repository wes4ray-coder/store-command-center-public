"""Token metering for peer compute — how many ANSWER tokens a job actually produced.

Two sources, in order of trust:

  1. REPORTED — the `usage` block LM Studio returns on /chat/completions
     (`completion_tokens` / `prompt_tokens`). This is the model's own tokenizer
     count and is what we bill on when we have it. Rows carry reported=1.

  2. ESTIMATED — some provider paths (a patched/offline client, an older LM
     Studio build, any backend that omits `usage`) give us only the text. We
     then fall back to the documented ceil(chars/4) approximation in
     jellycoin_extra.estimate_tokens and mark the row reported=0, so the ledger
     and the UI say "estimated" rather than pretending the number is exact.

The generation itself is unchanged: `call_metered` first tries a usage-capturing
call, and on ANY failure falls back to the caller's own `fallback_fn` (which is
rpc.py's `_call_lmstudio`, so existing behaviour, model choice and test
monkeypatching all still apply).
"""
import httpx

from deps import LMSTUDIO_URL
from llm_client import _llm_headers
from orchestrator import orch

from jellycoin_extra import estimate_tokens   # noqa: F401 — re-exported for callers


def _raw_llm_call(system: str, user: str, max_tokens: int, timeout: int = 600):
    """Same request llm_client._call_lmstudio makes, but returns the usage block too.
    Kept as a separate call rather than editing the shared client so nothing outside
    the peer path changes."""
    from deps import ENHANCE_MODEL
    model = getattr(orch, "_current_llm_model", None) or ENHANCE_MODEL
    body = {"model": model,
            "messages": [{"role": "system", "content": system or ""},
                         {"role": "user", "content": user or ""}],
            "max_tokens": max_tokens, "temperature": 0.75, "reasoning_effort": "none"}
    r = httpx.post(f"{LMSTUDIO_URL}/chat/completions", json=body,
                   headers=_llm_headers(), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    text = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
    return text, (data.get("usage") or {}), model


def call_metered(fallback_fn, system: str, user: str, max_tokens: int) -> dict:
    """Run one peer llm job and return
    {output, prompt_tokens, completion_tokens, reported, model}."""
    try:
        text, usage, model = _raw_llm_call(system, user, max_tokens)
        ct = int(usage.get("completion_tokens") or 0)
        if ct > 0:
            return {"output": text, "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": ct, "reported": True, "model": model}
        # reached LM Studio but it told us nothing about usage → estimate from the text
        return {"output": text, "prompt_tokens": estimate_tokens(system) + estimate_tokens(user),
                "completion_tokens": estimate_tokens(text), "reported": False, "model": model}
    except Exception:
        pass
    text = fallback_fn(system, user, max_tokens)
    return {"output": text, "prompt_tokens": estimate_tokens(system) + estimate_tokens(user),
            "completion_tokens": estimate_tokens(text), "reported": False,
            "model": getattr(orch, "_current_llm_model", None)}
