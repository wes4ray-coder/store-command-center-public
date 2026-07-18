"""model_registry — per-feature model selection + fallback."""
import pytest

import model_registry
import db


def _clear(key):
    conn = db.get_conn(); conn.execute("DELETE FROM settings WHERE key=?", (key,)); conn.commit(); conn.close()


def _set(key, val):
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, val))
    conn.commit(); conn.close()


def test_security_model_falls_back_to_global_llm():
    _set("enhance_model", "google/gemma-4-12b-qat")
    _clear("security_model")                       # unset → fallback to enhance_model
    assert model_registry.resolve("security_model") == "google/gemma-4-12b-qat"


def test_explicit_model_overrides_fallback():
    _set("security_model", "qwen3-coder-30b-a3b-instruct")
    try:
        assert model_registry.resolve("security_model") == "qwen3-coder-30b-a3b-instruct"
    finally:
        _clear("security_model")


def test_set_model_rejects_unknown_slot():
    with pytest.raises(KeyError):
        model_registry.set_model("not_a_real_slot", "x")


def test_slots_carry_effective_and_raw():
    _set("enhance_model", "google/gemma-4-12b-qat")
    slots = {s["key"]: s for s in model_registry.slots()}
    assert slots["enhance_model"]["value"] == "google/gemma-4-12b-qat"
    assert "desc" in slots["security_model"] and slots["security_model"]["kind"] == "llm"
