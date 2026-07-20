"""THE COMPANY — run modes: how FAST and how AUTONOMOUS the sim runs.

  normal — real pace; your automation settings exactly as-is (default).
  fast   — the ticker runs ~5x faster so you can WATCH the town evolve (agents move,
           gather, tech/era advance). LLM cognition, GPU creation and money keep their
           OWN real cadences + gates — fast never hammers the GPU/LLM or spends more.
  test   — fast speed AND automation auto-runs: a DRY RUN where the FREE internal loops
           (art/music/agent work/era progression) run without waiting for your approval
           so the world visibly progresses, WHILE money + code actions stay gated exactly
           as always. Nothing real can be spent or posted in test mode — it's safe by
           construction (it only forces automation_mode='budget', which already keeps the
           money/code kinds gated).

One tiny setting: world_run_mode ("normal" | "fast" | "test"). Import-safe, no side effects.
"""
from deps import get_setting

_SPEED = {"normal": 1, "fast": 5, "test": 5}
MODES = ("normal", "fast", "test")


def mode() -> str:
    m = (get_setting("world_run_mode", "normal") or "normal").strip().lower()
    return m if m in _SPEED else "normal"


def speed() -> int:
    """Tick-rate multiplier for the CHEAP per-tick sim (never the LLM/GPU/money cadences)."""
    return _SPEED.get(mode(), 1)


def is_test() -> bool:
    return mode() == "test"
