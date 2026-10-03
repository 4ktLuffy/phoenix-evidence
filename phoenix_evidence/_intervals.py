"""Intervals for a pass rate, with the example as the unit of evidence.

No scipy: closed forms and one bisection. Every interval here has its coverage measured in
`bench/coverage.py`; the docstrings say which one to trust where.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def wilson(successes: float, trials: float, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval; (0, 1) when there are no trials. Accepts fractional counts."""
    if trials <= 0:
        return 0.0, 1.0
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(max(p * (1 - p), 0.0) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p), summed in log space so large n does not overflow."""
    if k < 0:
        return 0.0
    if k >= n or p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    log_p, log_q, log_n = math.log(p), math.log1p(-p), math.lgamma(n + 1)
    terms = [log_n - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * log_p + (n - i) * log_q for i in range(k + 1)]
    top = max(terms)
    return min(1.0, math.exp(top) * sum(math.exp(t - top) for t in terms))


def clopper_pearson(successes: int, trials: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided binomial interval: covers at least 1 - alpha at every size and rate."""
    if trials <= 0:
        return 0.0, 1.0

    def upper(k: int) -> float:
        if k >= trials:
            return 1.0
        low, high = k / trials, 1.0
        for _ in range(60):  # P(X <= k | p) falls as p rises
            mid = (low + high) / 2
            low, high = (mid, high) if _binomial_cdf(k, trials, mid) > alpha / 2 else (low, mid)
        return high

    return 1 - upper(trials - successes), upper(successes)


def rate_interval(per_example: Sequence[Sequence[bool]], alpha: float = 0.05) -> tuple[float, float]:
    """Interval for a pass rate when each example may have several repeated judgments.

    One judgment per example: Clopper-Pearson, exact. Several: repetitions of one example are not
    independent, so each example counts once, by its share of passing judgments, and the exact
    interval is taken on the example count, with the shares' sum rounded down for the lower bound
    and up for the upper. A share in [0, 1] with mean p has variance at most p(1 - p), so this is
    conservative: repetitions never make the interval narrower than the examples alone allow.

    An earlier version estimated a design effect from the intra-example correlation and applied
    Wilson at the effective size; `bench/coverage.py` measured it at 0.90 coverage (16 examples,
    5 repetitions, examples that differ), so it was replaced.
    """
    examples = [list(e) for e in per_example if len(e) > 0]
    n = len(examples)
    if n == 0:
        return 0.0, 1.0
    shares = sum(sum(e) / len(e) for e in examples)
    low = clopper_pearson(math.floor(shares + 1e-9), n, alpha)[0]
    high = clopper_pearson(math.ceil(shares - 1e-9), n, alpha)[1]
    return low, high


def _z(q: float) -> float:
    """Standard normal quantile by bisection on erf; accurate to 1e-10, fast enough here."""
    low, high = -10.0, 10.0
    for _ in range(80):
        mid = (low + high) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < q:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def normal_quantile(q: float) -> float:
    return _z(q)
