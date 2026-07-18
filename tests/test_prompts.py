"""Prompt registry (app/prompts.py) — the config surface for every LLM system prompt."""
import pytest
import prompts


def test_every_prompt_resolves_a_nonempty_default():
    for p in prompts.PROMPTS:
        d = p.default()
        assert isinstance(d, str) and d.strip(), f"prompt {p.key} has an empty/invalid default"


def test_keys_are_unique():
    keys = [p.key for p in prompts.PROMPTS]
    assert len(keys) == len(set(keys)), "duplicate prompt keys"


def test_get_prompt_unknown_key_raises():
    with pytest.raises(KeyError):
        prompts.get_prompt("does_not_exist_xyz")


def test_override_and_reset_roundtrip():
    key = "image_enhance"
    default = prompts.get_prompt(key)
    try:
        prompts.set_prompt(key, "CUSTOM TEST VALUE")
        assert prompts.get_prompt(key) == "CUSTOM TEST VALUE"
        # and it shows as overridden in the listing
        item = next(x for x in prompts.list_prompts() if x["key"] == key)
        assert item["overridden"] is True
        assert item["value"] == "CUSTOM TEST VALUE"
    finally:
        prompts.reset_prompt(key)
    assert prompts.get_prompt(key) == default
    item = next(x for x in prompts.list_prompts() if x["key"] == key)
    assert item["overridden"] is False


def test_empty_override_falls_back_to_default():
    key = "audio_music"
    default = prompts.get_prompt(key)
    prompts.set_prompt(key, "   ")   # whitespace-only should not count as an override
    try:
        assert prompts.get_prompt(key) == default
    finally:
        prompts.reset_prompt(key)


def test_templated_prompts_format_without_keyerror():
    """Templated prompts advertise {placeholders}; a naive .format() must not KeyError
    on their OWN placeholders (this is what breaks a real call site if edited wrong)."""
    samples = {
        "resell_analyze":  dict(seller_context="ctx"),
        "resell_price":    dict(title="t", condition="c", category="cat"),
        "social_caption":  dict(plats="Instagram", tone="fun"),
        "resell_posting":  dict(platform="fb", title="t", price="9", price_mode="firm",
                                condition="good", category="c", description="d",
                                shipping_note="n", payment_note="p", photos="x",
                                platform_instructions="i"),
    }
    for key, kwargs in samples.items():
        p = next((x for x in prompts.PROMPTS if x.key == key), None)
        if p is None:
            continue
        assert p.templated, f"{key} should be marked templated"
        # must not raise
        out = prompts.get_prompt(key).format(**kwargs)
        assert isinstance(out, str) and out


def test_list_prompts_shape():
    items = prompts.list_prompts()
    assert len(items) == len(prompts.PROMPTS)
    for it in items:
        assert {"key", "label", "category", "value", "default", "overridden", "templated"} <= set(it)
