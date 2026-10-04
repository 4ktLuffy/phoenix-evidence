"""Is B better than A yet? A comparison you may check after every batch, and stop as soon as it decides.

Running both versions on every example of a big dataset, then testing once, spends judge calls on
examples that no longer change the answer. Testing after every batch with an ordinary test and
stopping at the first "significant" result is worse: each look is another chance of a false win.

This test looks only at examples where the two versions disagree (one better, one worse) and asks
whether "B better" happens more often than "A better". Under no difference, and when the two
versions are interchangeable on each example (the same null as `compare`'s sign-flip test), each
such example is a fair coin. The evidence is a mixture likelihood ratio over the coin's bias with a
symmetric Beta(a, a) prior: a nonnegative martingale under the null, so by Ville's inequality the
chance it ever reaches 1/alpha, however often it is checked, is at most alpha. Measured in
bench/sequential_sim.py.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

PRIOR = 2.0  # Beta(a, a); chosen in bench/sequential_sim.py


def log_evidence(better: int, worse: int, a: float = PRIOR) -> float:
    """log of the Beta(a, a) mixture likelihood ratio against a fair coin, for `better` wins of B and
    `worse` wins of A among the examples where they differ."""
    if better < 0 or worse < 0:
        raise ValueError('counts must be non-negative')
    n = better + worse
    log_beta = math.lgamma(a + better) + math.lgamma(a + worse) - math.lgamma(2 * a + n)
    log_prior = 2 * math.lgamma(a) - math.lgamma(2 * a)
    return log_beta - log_prior + n * math.log(2)


@dataclass
class SequentialComparison:
    """Feed paired scores as they arrive; `decision` is set once the evidence reaches 1/alpha.

    `higher_is_better=False` for metrics such as errors or latency. Ties are not evidence and are
    only counted. A missing score (a crash) should be passed as the worst score, as `compare` does.
    """

    alpha: float = 0.05
    higher_is_better: bool = True
    prior: float = PRIOR
    pairs: int = 0
    ties: int = 0
    better: int = 0  # B (the candidate) better
    worse: int = 0
    decision: str | None = None  # 'candidate better' | 'candidate worse'
    decided_at: int | None = None
    history: list[float] = field(default_factory=list)

    def add(self, base: float, candidate: float) -> SequentialComparison:
        """One pair, in the order the pairs really arrived; checks the evidence after it."""
        self._count(base, candidate)
        self._check()
        return self

    def look(self, pairs: Iterable[tuple[float, float]]) -> SequentialComparison:
        """A batch of pairs whose arrival order is not known: counted, then checked once."""
        for base, candidate in pairs:
            self._count(base, candidate)
        self._check()
        return self

    def _count(self, base: float, candidate: float) -> None:
        if math.isnan(base) or math.isnan(candidate):
            raise ValueError('a score is NaN: pass a missing score as the worst score instead')
        self.pairs += 1
        diff = candidate - base if self.higher_is_better else base - candidate
        if diff > 0:
            self.better += 1
        elif diff < 0:
            self.worse += 1
        else:
            self.ties += 1

    def _check(self) -> None:
        e = self.evidence
        self.history.append(e)
        if self.decision is None and e >= 1 / self.alpha:
            self.decision = 'candidate better' if self.better > self.worse else 'candidate worse'
            self.decided_at = self.pairs

    def extend(self, pairs: Iterable[tuple[float, float]]) -> SequentialComparison:
        for base, candidate in pairs:
            self.add(base, candidate)
        return self

    @property
    def evidence(self) -> float:
        return math.exp(min(log_evidence(self.better, self.worse, self.prior), 700.0))

    def __str__(self) -> str:
        head = (f'{self.pairs} paired examples: candidate better on {self.better}, worse on {self.worse}, '
                f'tied on {self.ties}. ')  # fmt: skip
        if self.decision:
            return head + (f'DECIDED after {self.decided_at} examples: {self.decision} (evidence passed '
                           f'{1 / self.alpha:.0f}; the chance of a wrong call, however often you checked, is at '
                           f'most {self.alpha * 100:g}%). You can stop.')  # fmt: skip
        return head + (f'Not decided: evidence {self.evidence:.2f}, decision at {1 / self.alpha:.0f}. Run more '
                       'examples; checking again does not raise the error rate.')  # fmt: skip
