"""Pure scheduling logic (app/gpu_scheduler.py) — priority, model affinity, aging."""
from gpu_scheduler import Job, pick_next, order, effective_priority


def J(id, priority=1, model=None, enq=0.0, kind="llm", status="pending"):
    return Job(id=id, kind=kind, model=model, priority=priority, enqueued_at=enq, status=status)


def test_empty_and_no_pending():
    assert pick_next([], None, now=100) is None
    assert pick_next([J(1, status="running")], None, now=100) is None


def test_highest_priority_wins():
    jobs = [J(1, priority=2), J(2, priority=0), J(3, priority=1)]
    assert pick_next(jobs, resident_model=None, now=0).id == 2


def test_affinity_batches_resident_model_within_tier():
    # same priority + same enqueue time; the one matching the resident model is chosen
    jobs = [J(1, priority=1, model="A", enq=0), J(2, priority=1, model="B", enq=0)]
    assert pick_next(jobs, resident_model="B", now=0).id == 2
    assert pick_next(jobs, resident_model="A", now=0).id == 1


def test_affinity_prefers_borrow_any_and_none():
    jobs = [J(1, model="A", enq=0), J(2, model="*", enq=1)]
    # both are "no swap" vs resident C? model A needs swap, '*' borrows — '*' preferred
    assert pick_next(jobs, resident_model="C", now=0).id == 2


def test_affinity_never_overrides_priority():
    # a fresh high-priority job for a NON-resident model still beats resident-model lower prio
    jobs = [J(1, priority=1, model="A", enq=0),   # resident, but lower priority
            J(2, priority=0, model="B", enq=0)]   # needs swap, but urgent
    assert pick_next(jobs, resident_model="A", now=0).id == 2


def test_aging_promotes_a_starved_job():
    # job 1 is low priority (2) but has waited 3 age-steps -> effective 0
    # job 2 is fresh priority 1 -> effective 1. The aged job should win.
    now = 300.0
    aged = J(1, priority=2, model="A", enq=now - 180)   # waited 180s, step 60 -> -3 -> eff 0
    fresh = J(2, priority=1, model="B", enq=now)         # eff 1
    assert effective_priority(aged, now) == 0
    assert effective_priority(fresh, now) == 1
    assert pick_next([fresh, aged], resident_model="B", now=now).id == 1


def test_order_batches_same_model_then_switches():
    # priority all equal; affinity should group model A together before switching to B
    jobs = [J(1, model="A", enq=0), J(2, model="B", enq=1),
            J(3, model="A", enq=2), J(4, model="B", enq=3)]
    ids = [j.id for j in order(jobs, resident_model="A", now=0)]
    # starts resident A -> both A jobs first (1,3), then B jobs (2,4)
    assert ids[:2] == [1, 3]
    assert set(ids[2:]) == {2, 4}


def test_order_is_stable_and_complete():
    jobs = [J(1, model="A", enq=0), J(2, model="A", enq=1), J(3, model="B", enq=2)]
    ids = sorted(j.id for j in order(jobs, resident_model=None, now=0))
    assert ids == [1, 2, 3]   # every pending job scheduled exactly once
