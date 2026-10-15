"""A trailing-window rate limiter, safe to share between threads.

Shared on purpose: the limit belongs to the upstream API key, not to a caller,
and FastAPI runs every sync endpoint on its own thread -- one limiter per
thread would multiply the allowance by the size of the threadpool.

Process-local, though. Several uvicorn workers each hold their own instance, so
the effective rate is ``workers x max_requests``. Enforcing one budget across
processes needs shared state (Redis, or the upstream 429 itself).
"""

import threading
import time
from collections import deque

_RATE_LIMIT_REQUESTS = 20
_RATE_LIMIT_WINDOW_SECONDS = 60.0


class RateLimiter:
    """Blocks until fewer than ``max_requests`` calls happened in the trailing window."""

    def __init__(
        self,
        max_requests: int = _RATE_LIMIT_REQUESTS,
        window_seconds: float = _RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        # Holds the times slots were *taken for*, which for a caller that has to
        # wait is in the future. Kept sorted, oldest first.
        self._slots: deque[float] = deque()

    def wait(self) -> None:
        """Return once this caller's slot is due, having claimed it."""
        due = self._claim()
        remaining = due - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def _claim(self) -> float:
        """Take the next free slot and report when it comes due.

        The slot is claimed under the lock but slept off outside it: holding the
        lock across the sleep would stall callers that have room, turning the
        limiter into a queue even when it is not limiting anything.
        """
        with self._lock:
            now = time.monotonic()
            while self._slots and now - self._slots[0] >= self._window_seconds:
                self._slots.popleft()

            if len(self._slots) < self._max_requests:
                due = now
            else:
                # The window is full, so this call belongs one window after the
                # oldest slot in it -- which is exactly when that slot expires.
                due = self._slots.popleft() + self._window_seconds

            self._slots.append(due)
            return due
