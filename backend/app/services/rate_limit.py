"""Rate limiting for the credential endpoints.

A single-process sliding window: enough to make online password guessing and
registration spam impractical on one instance. It is deliberately *not* a distributed
limiter — with more than one worker each process keeps its own counters, so the
effective limit multiplies by the number of workers. A shared counter store (Redis or
a table) is the documented next step; see docs/AUTHENTICATION.md.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Optional


@dataclass(frozen=True)
class RateLimitPolicy:
    max_attempts: int
    window_seconds: int


class SlidingWindowRateLimiter:
    """Counts attempts per key inside a rolling window."""

    # Keys are emails/IPs supplied by clients; bound the dict so a flood cannot grow it forever.
    MAX_TRACKED_KEYS = 10_000

    def __init__(self, policy: RateLimitPolicy, clock: Callable[[], float] = time.monotonic) -> None:
        self._policy = policy
        self._clock = clock
        self._attempts: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def policy(self) -> RateLimitPolicy:
        return self._policy

    def _prune(self, key: str, now: float) -> Deque[float]:
        entries = self._attempts.get(key)
        if entries is None:
            return deque()
        cutoff = now - self._policy.window_seconds
        while entries and entries[0] <= cutoff:
            entries.popleft()
        if not entries:
            self._attempts.pop(key, None)
        return entries

    def retry_after(self, key: str) -> Optional[int]:
        """Seconds until another attempt is allowed, or None when allowed now."""
        with self._lock:
            now = self._clock()
            entries = self._prune(key, now)
            if len(entries) < self._policy.max_attempts:
                return None
            return max(1, int(round(entries[0] + self._policy.window_seconds - now)))

    def record(self, key: str) -> None:
        """Count one attempt (a failed login, a registration request)."""
        with self._lock:
            now = self._clock()
            entries = self._prune(key, now)
            if not entries and len(self._attempts) >= self.MAX_TRACKED_KEYS:
                # Cheap eviction: drop already-expired keys before adding another.
                # Snapshot the keys first: _prune() deletes from the same dict.
                for stale in list(self._attempts.keys()):
                    if not self._prune(stale, now):
                        self._attempts.pop(stale, None)
                if len(self._attempts) >= self.MAX_TRACKED_KEYS:
                    self._attempts.pop(next(iter(self._attempts)), None)
            self._attempts.setdefault(key, entries).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()
