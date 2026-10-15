"""The shared rate limiter, exercised from several threads at once.

Threads rather than sequential calls, because that is how it is used: FastAPI
runs every sync endpoint on its own thread and they all reach the same limiter
instance. A version that only holds sequentially passes a sequential test.

Windows here are fractions of a second, so the suite stays fast.
"""

from __future__ import annotations

import threading
import time

from law_agent.utils import RateLimiter

WINDOW = 0.3
TOLERANCE = 0.02
"""Scheduling slack: a thread wakes up a little late, never early."""


def _call_times(limiter: RateLimiter, calls: int, *, threads: int = 1) -> list[float]:
    """When each of ``calls`` permitted calls actually happened, sorted."""
    times: list[float] = []
    guard = threading.Lock()
    start = threading.Barrier(threads)

    def worker(share: int) -> None:
        start.wait()
        for _ in range(share):
            limiter.wait()
            with guard:
                times.append(time.monotonic())

    workers = [threading.Thread(target=worker, args=(calls // threads,)) for _ in range(threads)]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join()
    return sorted(times)


def test_calls_within_the_limit_do_not_wait() -> None:
    limiter = RateLimiter(max_requests=5, window_seconds=WINDOW)

    started = time.monotonic()
    _call_times(limiter, 5)

    assert time.monotonic() - started < WINDOW


def test_the_call_over_the_limit_waits_out_the_window() -> None:
    limiter = RateLimiter(max_requests=2, window_seconds=WINDOW)

    times = _call_times(limiter, 3)

    assert times[2] - times[0] >= WINDOW - TOLERANCE


def test_concurrent_callers_share_one_budget() -> None:
    """The invariant, stated directly: no window ever holds more than the limit.

    With an unsynchronised limiter the threads all read the same count before
    any of them records a call, and every one of them goes straight through.
    """
    limit = 4
    limiter = RateLimiter(max_requests=limit, window_seconds=WINDOW)

    times = _call_times(limiter, calls=16, threads=16)

    assert len(times) == 16
    for index in range(len(times) - limit):
        assert times[index + limit] - times[index] >= WINDOW - TOLERANCE


def test_the_slot_queue_does_not_grow_with_the_number_of_calls() -> None:
    """Expired slots are dropped, so a long-lived limiter is not a leak."""
    limiter = RateLimiter(max_requests=2, window_seconds=0.05)

    for _ in range(20):
        limiter.wait()

    assert len(limiter._slots) <= 2
