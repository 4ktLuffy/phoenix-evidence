"""What does it cost to know a pass rate to within a given width, and which way is cheapest?

Two ways to learn the pass rate humans would give over `traces` production traces:

- humans label a uniform sample (exact Clopper-Pearson interval);
- the judge scores every trace and humans label a uniform sample, combined by `corrected_rate`.

The second pays for a judge call on every trace and needs fewer labels the more the judge agrees
with humans. The label counts come from the same interval formulas the package reports, so the
plan is what `corrected-rate` and a Clopper-Pearson interval will actually show, given the pass
rate and disagreement rate you expect (measure the disagreement with `certify-feedback`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from phoenix_evidence._intervals import clopper_pearson, student_t_quantile
from phoenix_evidence._ppi import PSEUDO_DISAGREEMENTS


def _corrected_width(labels: int, traces: int, disagreement: float, alpha: float) -> float:
    # corrected_rate's variance at uniform inclusion pi = n / N, judge weight 1, binary verdicts:
    # sum over labelled of (1 - pi) / pi^2 * gap^2 / N^2 = (1 - pi) * d / n, plus the pseudo-disagreements.
    pi = labels / traces
    variance = (1 - pi) * (disagreement / labels + PSEUDO_DISAGREEMENTS / labels**2)
    return 2 * student_t_quantile(1 - alpha / 2, max(labels - 1, 1)) * math.sqrt(variance)


def _human_width(labels: int, pass_rate: float, alpha: float) -> float:
    lo, hi = clopper_pearson(round(pass_rate * labels), labels, alpha)
    return hi - lo


def _smallest(width_of, target: float, high: int) -> int | None:
    """Smallest n whose width is at most `target`, for widths that fall monotonically with n."""
    if width_of(high) > target:
        return None
    lo, hi = 1, high
    while lo < hi:
        mid = (lo + hi) // 2
        if width_of(mid) <= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _first(width_of, target: float, high: int) -> int | None:
    """Smallest n whose width is at most `target`, scanning up: Clopper-Pearson widths are not monotone
    in n (the count is rounded), so a bisection can stop above the first n that works (review 3)."""
    return next((n for n in range(1, high + 1) if width_of(n) <= target), None)


@dataclass(frozen=True)
class Plan:
    name: str
    labels: int | None
    judge_calls: int
    cost: float | None


@dataclass(frozen=True)
class Price:
    width: float
    human_only: Plan
    corrected: Plan
    break_even_human_cost: float | None  # above this cost per label, the judge pays for itself

    @property
    def cheapest(self) -> Plan | None:
        options = [p for p in (self.human_only, self.corrected) if p.cost is not None]
        return min(options, key=lambda p: p.cost) if options else None

    def __str__(self) -> str:
        def show(p: Plan) -> str:
            if p.labels is None:
                return f'{p.name}: cannot reach +/-{self.width / 2:.3f} on these traces'
            calls = f' + {p.judge_calls} judge calls' if p.judge_calls else ''
            return f'{p.name}: {p.labels} human labels{calls}, cost {p.cost:,.2f}'

        best = self.cheapest
        lines = [show(self.human_only), show(self.corrected)]
        if best:
            lines.append(f'cheapest: {best.name}')
        if self.break_even_human_cost is not None:
            lines.append(
                f'the judge pays for itself when a human label costs more than {self.break_even_human_cost:,.3f}'
            )
        return '\n'.join(lines)


def price_of_certainty(
    traces: int,
    width: float,
    judge_cost: float,
    human_cost: float,
    pass_rate: float = 0.5,
    disagreement: float = 0.1,
    alpha: float = 0.05,
) -> Price:
    """Cheapest way to an interval no wider than `width` for the human pass rate over `traces`.

    `judge_cost` is per judge call, `human_cost` per human label. `pass_rate` is your guess at the
    rate (0.5 is the worst case for humans alone); `disagreement` is how often the judge and a
    human differ on a trace (an upper bound is safe: the gap's variance is at most that).
    """
    if traces < 2 or not 0 < width < 1:
        raise ValueError('need at least 2 traces and a width between 0 and 1')
    if not 0 <= disagreement <= 1 or not 0 <= pass_rate <= 1:
        raise ValueError('pass_rate and disagreement are rates in [0, 1]')
    n_h = _first(lambda n: _human_width(n, pass_rate, alpha), width, traces)
    # monotone: (1 - n/N)(d/n + 2/n^2) and the t quantile both fall with n
    n_c = _smallest(lambda n: _corrected_width(n, traces, disagreement, alpha), width, traces)
    human = Plan('human labels only', n_h, 0, None if n_h is None else n_h * human_cost)
    corrected = Plan('judge on every trace + human labels', n_c, traces,
                     None if n_c is None else traces * judge_cost + n_c * human_cost)  # fmt: skip
    saved = None if n_h is None or n_c is None else n_h - n_c
    break_even = traces * judge_cost / saved if saved and saved > 0 else None
    return Price(width, human, corrected, break_even)
