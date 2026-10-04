"""Has the judge drifted? A check you can run every day without the daily looks causing false alarms.

A frozen set of examples keeps the labels the judge gave when it was trusted. Each check re-scores
the set with today's judge and counts flips: examples where today's label differs from the stored
one. Some flips are noise (a judge is not deterministic), so drift means a flip rate above an
allowed rate, not any flip.

Testing that every day with an ordinary test at 5% raises a false alarm far more than 5% of the time
over a quarter: each look is another chance. This uses a mixture likelihood ratio instead (a mixture
sequential probability ratio test, Robbins 1970), which is a nonnegative supermartingale when the
judge has not drifted, so by Ville's inequality the chance it ever crosses 1/alpha, over any number
of looks, is at most alpha. Measured in bench/canary_sim.py.

The guarantee needs fresh judge calls: a response cache makes today's flips copies of yesterday's.
Examples may differ in how often they flip; the null is that their average flip rate is at most the
allowed rate.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from phoenix_evidence._intervals import _betacf


def _log_upper_mass(a: float, b: float, p0: float) -> float:
    """log of the integral of q^(a-1) (1-q)^(b-1) over [p0, 1], computed in logs throughout.

    The tail is the regularized incomplete beta I_{1-p0}(b, a). After many clean checks it is far
    below the smallest float while the likelihood ratio it enters is ordinary, so it must never be
    formed as a plain number (an earlier version did, and returned no evidence at all).
    """
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    x = 1 - p0  # tail = I_x(b, a)
    log_front = -log_beta + b * math.log(x) + a * math.log(p0)
    if x < (b + 1) / (a + b + 2):
        log_tail = log_front + math.log(_betacf(b, a, x) / b)
    else:
        log_tail = math.log1p(-min(1.0, math.exp(log_front) * _betacf(a, b, p0) / a))
    return log_beta + log_tail


def default_prior(allowed: float) -> tuple[float, float]:
    """Beta(1, (1 - allowed) / allowed): mean at the allowed rate, so after truncation most weight sits
    on drifts just above it. In bench/canary_sim.py this caught small drifts sooner than a uniform
    prior (median 22 vs 31 days for +3 points) at a false-alarm rate still under alpha."""
    return 1.0, (1 - allowed) / allowed


def log_evidence(flips: int, checks: int, allowed: float, prior: tuple[float, float] | None = None) -> float:
    """log of the mixture likelihood ratio for `flips` in `checks` against a flip rate of `allowed`.

    The alternative is a Beta prior (default: `default_prior`) truncated to rates above `allowed`. Every rate in it makes the
    one-check likelihood ratio have expectation at most 1 whenever the true rate is at most
    `allowed`, so the mixture is a supermartingale under the whole null, not only at its edge.
    """
    if not 0 < allowed < 1:
        raise ValueError('the allowed flip rate must be strictly between 0 and 1')
    if not 0 <= flips <= checks:
        raise ValueError('flips must be between 0 and the number of checks')
    a, b = prior or default_prior(allowed)
    fails = checks - flips
    mixture = _log_upper_mass(a + flips, b + fails, allowed) - _log_upper_mass(a, b, allowed)
    return mixture - flips * math.log(allowed) - fails * math.log1p(-allowed)


@dataclass(frozen=True)
class Look:
    label: str
    checks: int
    flips: int
    total_checks: int
    total_flips: int
    evidence: float  # the likelihood ratio; drift is declared when it reaches 1 / alpha
    drifted: bool


@dataclass(frozen=True)
class CanaryReport:
    allowed: float
    alpha: float
    looks: list[Look]

    @property
    def drifted(self) -> bool:
        return any(look.drifted for look in self.looks)

    @property
    def first_alarm(self) -> Look | None:
        return next((look for look in self.looks if look.drifted), None)

    def __str__(self) -> str:
        if not self.looks:
            return 'no checks yet'
        last = self.looks[-1]
        rate = last.total_flips / last.total_checks if last.total_checks else 0.0
        head = (f'{last.total_flips} flips in {last.total_checks} re-scored examples over {len(self.looks)} checks '
                f'(rate {rate:.3f}; allowed {self.allowed:.3f}). ')  # fmt: skip
        alarm = self.first_alarm
        if alarm:
            return head + (f'DRIFT: evidence passed {1 / self.alpha:.0f} at check {alarm.label!r} '
                           f'({alarm.total_flips} flips in {alarm.total_checks}); the chance of that '
                           f'without drift, however often you look, is at most {self.alpha * 100:g}%.')  # fmt: skip
        return head + (f'No drift shown: evidence {last.evidence:.2f}, alarm at {1 / self.alpha:.0f}. '
                       'Keep checking; looking again does not raise the false-alarm rate.')  # fmt: skip


def canary(
    checks: Sequence[tuple[str, int, int]],
    allowed: float,
    alpha: float = 0.05,
    prior: tuple[float, float] | None = None,
) -> CanaryReport:
    """Drift evidence after each check, in order. `checks` is (label, examples re-scored, flips).

    Once drift is declared it stays declared: the evidence is cumulative over every check so far.
    """
    if not 0 < alpha < 1:
        raise ValueError('alpha must be between 0 and 1')
    looks, total, flipped, alarmed = [], 0, 0, False
    for label, n, k in checks:
        if not 0 <= k <= n:
            raise ValueError(f'check {label!r}: flips must be between 0 and the number re-scored')
        total, flipped = total + n, flipped + k
        evidence = math.exp(min(log_evidence(flipped, total, allowed, prior), 700.0))
        alarmed = alarmed or evidence >= 1 / alpha
        looks.append(Look(label, n, k, total, flipped, evidence, alarmed))
    return CanaryReport(allowed, alpha, looks)


def count_flips(reference: dict[str, object], today: dict[str, Sequence[object]]) -> tuple[int, int]:
    """(re-scored, flips) for today's labels per example against the frozen ones.

    Every repetition is one re-score. A missing label today (the judge errored) counts as a flip:
    a judge that has started failing has changed. Examples not in the frozen set are ignored.
    """
    n = k = 0
    for example, labels in today.items():
        if example not in reference:
            continue
        for label in labels:
            n += 1
            k += label is None or label != reference[example]
    return n, k
