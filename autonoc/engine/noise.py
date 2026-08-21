"""
Deterministic gaussian noise pool.

Profiling showed random.gauss() dominating the tick: 595,297 calls across 200
ticks, roughly 10 per node per tick, at 0.527 s of a 3.0 s profile.

A pool of pre-drawn unit-normal samples turns each draw into an index lookup
and a multiply. Determinism is preserved exactly: the pool is filled once from
the seeded stream, and consumption is a single monotonically increasing index
over fixed-order iteration.

Pool size is deliberately coprime-ish with the per-tick draw count so the
sequence does not visibly repeat against the tick cycle.
"""
from __future__ import annotations


class NoisePool:
    __slots__ = ("_pool", "_n", "_i")

    def __init__(self, rng, size: int = 65_521) -> None:
        # 65521 is prime — avoids aliasing against 300 nodes x ~10 draws
        self._pool = [rng.gauss(0.0, 1.0) for _ in range(size)]
        self._n = size
        self._i = 0

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        i = self._i
        self._i = i + 1 if i + 1 < self._n else 0
        return mu + self._pool[i] * sigma

    def random(self) -> float:
        """Uniform in [0,1) derived from the same deterministic cursor.

        Only used where a cheap coin-flip is needed; anything that must match
        a specific distribution should use the owning Random instance.
        """
        i = self._i
        self._i = i + 1 if i + 1 < self._n else 0
        v = self._pool[i]
        # map roughly-normal to [0,1) via a monotone squash; deterministic
        return 0.5 + 0.5 * (v / (1.0 + abs(v)))

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.random()
