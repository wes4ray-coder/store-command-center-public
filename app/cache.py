"""Tiny in-process TTL cache.

For endpoints that block on slow external services (WooCommerce over HTTPS, `docker
ps`, SSH to the GPU box) so repeated tab loads within a few seconds don't re-hit them
every time. Not distributed, not persisted — a per-process dict with expiry, which is
exactly right for the single-worker uvicorn the store runs.

    data = cached("portal:wp-products", 30, fetch_products)   # ttl in seconds
    @ttl_cached(10)
    def connections(): ...
"""
import threading
import time
from functools import wraps

_store: dict = {}
_lock = threading.Lock()


def cached(key, ttl_seconds, producer):
    """Return the cached value for `key`, or call `producer()` and cache it for `ttl_seconds`.

    The producer runs OUTSIDE the lock (it may be slow), so a cold miss under
    concurrent load can call it more than once — acceptable for read-only external
    fetches and avoids serializing all callers behind one slow request.
    """
    now = time.time()
    with _lock:
        hit = _store.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = producer()
    with _lock:
        _store[key] = (now + ttl_seconds, value)
    return value


def invalidate(key=None):
    """Drop one key, or the entire cache when key is None (e.g. after a write)."""
    with _lock:
        if key is None:
            _store.clear()
        else:
            _store.pop(key, None)


def invalidate_prefix(prefix):
    """Drop every key starting with `prefix` — for busting a family of cached
    variants (e.g. per-page product lists) after a write."""
    with _lock:
        for k in [k for k in _store if k.startswith(prefix)]:
            _store.pop(k, None)


def ttl_cached(ttl_seconds, key=None):
    """Decorator caching a function's result by (qualname, args). `key`, if given, is
    a callable(*args, **kwargs) -> str that overrides the derived cache key."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            k = (key(*args, **kwargs) if key
                 else f"{fn.__module__}.{fn.__qualname__}:{args!r}:{sorted(kwargs.items())!r}")
            return cached(k, ttl_seconds, lambda: fn(*args, **kwargs))
        return wrapper
    return deco
