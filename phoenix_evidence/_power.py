"""How many examples a decision needs, computed exactly where it can be."""

from __future__ import annotations

import math

from phoenix_evidence._gate import min_successes_to_pass
from phoenix_evidence._intervals import _binomial_cdf, clopper_pearson, normal_cdf, normal_quantile


def pass_probability(n: int, true_rate: float, threshold: float, alpha: float = 0.05) -> float:
    """Exact chance that `decide_rate` says PASS for a judge whose true accuracy is `true_rate`."""
    k = min_successes_to_pass(n, threshold, alpha)
    if k is None:
        return 0.0
    return 1.0 - _binomial_cdf(k - 1, n, true_rate)


def fail_probability(n: int, true_rate: float, threshold: float, alpha: float = 0.05) -> float:
    """Exact chance that `decide_rate` says FAIL (the upper bound falls below the bar)."""
    # The exact upper bound rises with k: find the largest k whose upper bound is below the bar.
    if clopper_pearson(0, n, alpha)[1] >= threshold:
        return 0.0
    low, high = 0, n
    while low < high:
        mid = (low + high + 1) // 2
        if clopper_pearson(mid, n, alpha)[1] < threshold:
            low = mid
        else:
            high = mid - 1
    return _binomial_cdf(low, n, true_rate)


def examples_to_pass(
    true_rate: float, threshold: float, power: float = 0.8, alpha: float = 0.05, limit: int = 100_000
) -> int | None:
    """Fewest examples at which a judge with `true_rate` passes the bar with probability `power`.

    Exact binomial power is saw-toothed in n, so this returns the first n from which power stays
    at or above the target for the next 20 sizes. None when the judge is not above the bar.
    """
    if true_rate <= threshold:
        return None
    # Start from the normal approximation, then search exactly around it.
    za, zb = normal_quantile(1 - alpha / 2), normal_quantile(power)
    guess = ((za * math.sqrt(threshold * (1 - threshold)) + zb * math.sqrt(true_rate * (1 - true_rate)))
             / (true_rate - threshold)) ** 2  # fmt: skip

    def holds_from(m: int) -> bool:
        return all(pass_probability(k, true_rate, threshold, alpha) >= power for k in range(m, m + 20))

    n = max(1, int(guess * 0.7))
    while n <= limit and not holds_from(n):
        n += max(1, n // 50)  # coarse steps to the region where power holds...
    if n > limit:
        return None
    while n > 1 and holds_from(n - 1):
        n -= 1  # ...then back to the first size from which it holds
    return n


def paired_examples_needed(p_discordant: float, delta: float, power: float = 0.8, alpha: float = 0.05) -> int | None:
    """Examples needed to detect a paired difference `delta` in pass rate (McNemar, normal form).

    `p_discordant` is the share of examples on which the two versions disagree; `delta` is the
    difference in pass rate. Connor (1987): n = (za*sqrt(pd) + zb*sqrt(pd - delta^2))^2 / delta^2.
    """
    if delta <= 0 or p_discordant <= 0 or abs(delta) > p_discordant:
        return None
    za, zb = normal_quantile(1 - alpha / 2), normal_quantile(power)
    return math.ceil((za * math.sqrt(p_discordant) + zb * math.sqrt(p_discordant - delta**2)) ** 2 / delta**2)


def detectable_difference(n: int, p_discordant: float, power: float = 0.8, alpha: float = 0.05) -> float | None:
    """Smallest paired difference in pass rate that n examples detect with `power` (inverse of above)."""
    if n <= 0 or p_discordant <= 0:
        return None
    low, high = 1e-6, p_discordant
    if (paired_examples_needed(p_discordant, high, power, alpha) or math.inf) > n:
        return None
    for _ in range(60):
        mid = (low + high) / 2
        needed = paired_examples_needed(p_discordant, mid, power, alpha)
        if needed is not None and needed <= n:
            high = mid
        else:
            low = mid
    return high


def two_proportion_power(n: int, p1: float, p2: float, alpha: float = 0.05) -> float:
    """Approximate power of an unpaired two-sided test of p1 vs p2, n examples each."""
    if n <= 0:
        return 0.0
    p_bar = (p1 + p2) / 2
    se0 = math.sqrt(2 * p_bar * (1 - p_bar) / n)
    se1 = math.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / n)
    if se1 == 0:
        return 1.0 if p1 != p2 else 0.0
    za = normal_quantile(1 - alpha / 2)
    return normal_cdf((abs(p1 - p2) - za * se0) / se1)
