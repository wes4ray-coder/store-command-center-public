"""The orchestrator's scheduler integration — _pick_pending() maps queued LLM tasks to
gpu_scheduler and returns the next one to run. Built with __new__ so no worker thread /
LM Studio calls are involved — pure ordering glue."""
import threading
import orchestrator


def _bare():
    o = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)
    o._lock = threading.RLock()
    o._current_llm_model = None
    o._tasks = {}
    o._order = []
    return o


def _add(o, tid, priority=1, model=None, enq=0.0, status="pending"):
    o._tasks[tid] = {"id": tid, "status": status, "priority": priority,
                     "model": model, "enqueued_at": enq}
    o._order.append(tid)


def test_pick_prefers_higher_priority_over_submit_order():
    o = _bare()
    _add(o, 1, priority=2, enq=0)   # background, submitted first
    _add(o, 2, priority=0, enq=1)   # user-facing, submitted later
    _add(o, 3, priority=1, enq=2)
    with o._lock:
        assert o._pick_pending()["id"] == 2   # priority 0 wins despite later enqueue


def test_pick_is_fifo_within_equal_priority():
    o = _bare()
    _add(o, 5, priority=1, enq=10)
    _add(o, 6, priority=1, enq=11)
    with o._lock:
        assert o._pick_pending()["id"] == 5   # oldest of the tier


def test_pick_none_when_no_pending():
    o = _bare()
    _add(o, 7, priority=0, enq=0, status="running")
    with o._lock:
        assert o._pick_pending() is None


def test_pick_affinity_batches_resident_model_within_tier():
    o = _bare()
    o._current_llm_model = "B"
    _add(o, 1, priority=1, model="A", enq=0)
    _add(o, 2, priority=1, model="B", enq=1)   # matches resident → run to avoid a swap
    with o._lock:
        assert o._pick_pending()["id"] == 2
