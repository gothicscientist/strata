"""In-process token-bucket rate limiter (per key). For multi-instance deployments put a shared
limiter (e.g. Cloudflare rate-limiting rules) in front; this one bounds abuse per process."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    def __init__(
        self, rate_per_minute: float, burst: int, *, max_keys: int = 50_000, clock=time.monotonic
    ) -> None:
        self.rate = rate_per_minute / 60.0
        self.capacity = float(burst)
        self.max_keys = max_keys
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Take `cost` tokens. Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                if len(self._buckets) >= self.max_keys:
                    self._evict(now)
                b = self._buckets[key] = _Bucket(self.capacity, now)
            b.tokens = min(self.capacity, b.tokens + (now - b.updated) * self.rate)
            b.updated = now
            if b.tokens >= cost:
                b.tokens -= cost
                return True, 0.0
            deficit = cost - b.tokens
            return False, deficit / self.rate if self.rate > 0 else float("inf")

    def _evict(self, now: float) -> None:
        # Drop buckets that have refilled completely (they carry no state).
        full = [
            k
            for k, b in self._buckets.items()
            if b.tokens + (now - b.updated) * self.rate >= self.capacity
        ]
        for k in full:
            del self._buckets[k]
        if len(self._buckets) >= self.max_keys:
            oldest = sorted(self._buckets.items(), key=lambda kv: kv[1].updated)
            for k, _ in oldest[: len(oldest) // 2]:
                del self._buckets[k]

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
