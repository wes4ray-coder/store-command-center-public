"""Unified GPU job scheduler — the PURE decision core from GPU_QUEUE.md.

This module contains ONLY the scheduling algorithm (priority + model affinity + anti-
starvation aging) as pure functions over a list of Jobs. It has NO side effects and is
NOT yet wired into the live orchestrator — that integration (turning every LLM/vision/
image/video call into a Job, doing the LM Studio unload/load, folding in the OpenClaw
proxy) is the risky part that must be validated against the real GPU with a human present.

Doing the tricky ordering logic here, fully unit-tested, de-risks that later integration.

The rule (from GPU_QUEUE.md):
  1. Run the highest-priority pending job (priority 0 = most urgent).
  2. Affinity: among equally-urgent jobs, prefer one whose required model is ALREADY
     resident, so same-model work batches and we pay the VRAM swap once.
  3. Aging (anti-starvation): a job's *effective* priority rises the longer it waits, so
     affinity batching can never defer an urgent job forever. This is the subtlety —
     pure affinity would starve a lone urgent job behind a big same-model batch.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Job:
    id: int
    kind: str                      # 'llm' | 'vision' | 'image' | 'video'
    model: Optional[str] = None    # required model; '*' = borrow whatever's loaded; None = n/a
    priority: int = 1              # 0 user-facing > 1 autobuild/vision > 2 background
    origin: str = "store"          # 'store' | 'openclaw' | 'world'
    enqueued_at: float = 0.0       # epoch seconds (pass in — module stays time-source free)
    status: str = "pending"        # pending | running | done | error | cancelled
    _meta: dict = field(default_factory=dict)


def effective_priority(job: Job, now: float, age_step_sec: float = 60.0) -> int:
    """Priority after aging. Lower = more urgent. Each `age_step_sec` waited promotes the
    job one tier (toward 0), so a long-waiting low-priority job eventually wins."""
    waited = max(0.0, now - (job.enqueued_at or now))
    bumps = int(waited // age_step_sec) if age_step_sec > 0 else 0
    return max(0, int(job.priority) - bumps)


def borrows_resident(job: Job, resident_model: Optional[str]) -> bool:
    """True if running this job needs NO model swap (its model is resident, borrow-any, or n/a)."""
    return job.model in (resident_model, "*", None)


def pick_next(jobs, resident_model: Optional[str], now: float, age_step_sec: float = 60.0):
    """Choose the next job to run, or None if nothing is pending.

    jobs: iterable of Job. resident_model: the model currently loaded in VRAM (or None).
    """
    pending = [j for j in jobs if j.status == "pending"]
    if not pending:
        return None
    # 1. best (lowest) effective priority tier
    best = min(effective_priority(j, now, age_step_sec) for j in pending)
    tier = [j for j in pending if effective_priority(j, now, age_step_sec) == best]
    # 2. affinity within the tier — prefer a job needing no swap; tie-break oldest first
    if resident_model:
        affine = [j for j in tier if borrows_resident(j, resident_model)]
        if affine:
            return min(affine, key=lambda j: (j.enqueued_at, j.id))
    # 3. otherwise oldest in the tier
    return min(tier, key=lambda j: (j.enqueued_at, j.id))


def order(jobs, resident_model: Optional[str], now: float, age_step_sec: float = 60.0):
    """Full run order (repeatedly pick_next, updating the notional resident model to the
    picked job's model). Useful for previews/tests; the live scheduler picks one at a time."""
    remaining = [j for j in jobs if j.status == "pending"]
    resident = resident_model
    out = []
    # snapshot so we don't mutate caller state
    remaining = list(remaining)
    while remaining:
        nxt = pick_next(remaining, resident, now, age_step_sec)
        if nxt is None:
            break
        out.append(nxt)
        remaining = [j for j in remaining if j.id != nxt.id]
        if nxt.model not in (None, "*"):
            resident = nxt.model
    return out
