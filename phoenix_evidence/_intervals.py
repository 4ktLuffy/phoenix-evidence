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


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta function (Numerical Recipes, betacf)."""
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > 1e-300 else 1e-300)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-300 else 1e-300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + aa / c if abs(1 + aa / c) > 1e-300 else 1e-300
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-12:
            break
    return h


def _incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def student_t_cdf(t: float, df: float) -> float:
    tail = 0.5 * _incomplete_beta(df / 2, 0.5, df / (df + t * t))
    return 1 - tail if t >= 0 else tail


def student_t_quantile(q: float, df: float) -> float:
    """Quantile of Student's t by bisection on its exact cdf."""
    low, high = -1e3, 1e3
    for _ in range(200):
        mid = (low + high) / 2
        if student_t_cdf(mid, df) < q:
            low = mid
        else:
            high = mid
    return (low + high) / 2
