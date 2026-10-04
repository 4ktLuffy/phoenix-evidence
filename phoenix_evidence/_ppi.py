"""A judge's pass rate, corrected with a few human labels, and which traces to label next.

A judge scores every trace; humans label a few. The judge's own rate is biased by however much it
disagrees with humans, and the human labels alone are few. Prediction-powered inference
(Angelopoulos et al. 2023, "Prediction-powered inference"; the power-tuned form is PPI++, 2023)
combines them: the judge's rate over all traces, plus the human-minus-judge gap measured where
humans labelled. With inclusion probabilities that favour the traces the judge is least sure of
(Zrnic and Candes 2024, "Active statistical inference"), the same number of labels buys a
narrower interval. Each label is weighted by 1 / its inclusion probability, so the estimate stays
unbiased however the probabilities were chosen, as long as they were chosen before the labels
were seen and every trace had a chance.

Coverage and savings are measured in bench/ppi_sim.py.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from phoenix_evidence._intervals import student_t_quantile

PSEUDO_DISAGREEMENTS = 2


@dataclass(frozen=True)
class CorrectedRate:
    estimate: float
    interval: tuple[float, float]
    judge_rate: float
    human_only: tuple[float, float]
    labelled: int
    traces: int
    weight: float
    raw_estimate: float | None = None  # unclipped: unbiased, but can fall outside [0, 1]

    def __str__(self) -> str:
        lo, hi = self.interval
        base = (f'{self.estimate:.3f} [{lo:.3f}, {hi:.3f}] from {self.labelled} human labels on {self.traces} '
                f'traces; the judge alone says {self.judge_rate:.3f}')  # fmt: skip
        lo, hi = self.human_only
        base += f'; the human labels alone give [{lo:.3f}, {hi:.3f}]'
        if hi - lo < self.interval[1] - self.interval[0]:
            base += ': the judge adds nothing here; rely on the human labels'
        return base


def corrected_rate(
    judge: Sequence[float],
    human: Mapping[int, float],
    inclusion: Sequence[float] | None = None,
    alpha: float = 0.05,
    weight: float = 1.0,
    min_ratio: float = 0.1,
) -> CorrectedRate:
    """The pass rate humans would give, from the judge on every trace and humans on some.

    `judge[i]` is the judge's verdict (1/0, or a probability) on trace i. `human` maps the indices of
    labelled traces to the human verdict (a fraction when several people labelled the trace).
    `inclusion[i]` is the probability trace i was chosen for labelling, each trace drawn
    independently (uniform `len(human) / len(judge)` when omitted). Every chosen trace must be
    labelled: a chosen trace with no label is not a zero gap, and the caller must not pass the
    labelled subset of a larger draw.

    The estimate is `mean(weight * judge) + mean over traces of I_i (human_i - weight * judge_i) / pi_i`
    (Horvitz-Thompson), unbiased for any fixed `weight` because the weight does not depend on the
    labels. Weight 1 is plain prediction-powered inference; weight 0 is the human labels alone. Its
    variance is the design variance for independent unequal-probability draws,
    `N^-2 sum over labelled i of (1 - pi_i) / pi_i^2 * gap_i^2`, plus two pseudo-disagreements for
    small samples, with a Student-t quantile on the number of labels. The reported `estimate` is
    clipped to [0, 1], which biases it near the ends (review 3: a true rate of 0 read 0.11 on average
    in a ten-trace design); `raw_estimate` is the unbiased, unclipped value, for averaging or audits.
    Traces with a far smaller chance of being labelled than the rest make that variance unestimable
    (a group that is almost never sampled contributes nothing to it), so an inclusion probability
    below `min_ratio` times the mean is refused; `plan_labels` keeps every probability well above that.
    """
    n_all = len(judge)
    if n_all == 0 or not human:
        raise ValueError('need judge verdicts on some traces and human labels on at least one')
    if any(not 0 <= i < n_all for i in human):
        raise ValueError('a labelled index is outside the judged traces')
    pi = list(inclusion) if inclusion is not None else [len(human) / n_all] * n_all
    if len(pi) != n_all:
        raise ValueError('need one inclusion probability per judged trace')
    if any(not 0 < p <= 1 for p in pi):
        raise ValueError('every trace needs an inclusion probability in (0, 1]')
    mean_pi = sum(pi) / n_all
    if min(pi) < min_ratio * mean_pi:
        raise ValueError(
            f'the smallest inclusion probability ({min(pi):.4g}) is below {min_ratio} times the mean '
            f'({mean_pi:.4g}): traces that are almost never labelled make the interval unreliable'
        )
    f = [float(x) for x in judge]
    quantile = student_t_quantile(1 - alpha / 2, max(len(human) - 1, 1))

    def interval_for(w: float) -> tuple[float, tuple[float, float]]:
        gaps = {i: float(human[i]) - w * f[i] for i in human}
        estimate = (w * sum(f) + sum(gaps[i] / pi[i] for i in gaps)) / n_all
        weights = [(1 - pi[i]) / pi[i] ** 2 for i in gaps]
        variance = sum(wt * gaps[i] ** 2 for wt, i in zip(weights, gaps, strict=True)) / n_all**2
        # Small-sample guard, measured in bench/ppi_sim.py: with few labels most gaps are 0 and the
        # design variance is underestimated (coverage 88% at 80 planned labels without it). Two
        # pseudo-disagreements at the average weight are added; 1 was not enough (93.5%).
        variance += PSEUDO_DISAGREEMENTS * (sum(weights) / len(weights)) / n_all**2
        half = quantile * math.sqrt(variance)
        low, high = estimate - half, estimate + half
        return estimate, (min(max(low, 0.0), 1.0), max(min(high, 1.0), 0.0))

    estimate, interval = interval_for(weight)
    _, human_only = interval_for(0.0)
    return CorrectedRate(
        estimate=min(max(estimate, 0.0), 1.0),
        interval=interval,
        judge_rate=sum(f) / n_all,
        human_only=human_only,
        labelled=len(human),
        traces=n_all,
        weight=weight,
        raw_estimate=estimate,
    )


def plan_labels(
    uncertainty: Sequence[float], budget: int, floor: float = 1.0, seed: int = 0
) -> tuple[list[int], list[float]]:
    """Which traces to send to humans: more likely where the judge is unsure, never impossible.

    `uncertainty[i]` is any non-negative measure of the judge's doubt on trace i (it changed its
    answer on a repeat, a probability near 0.5, ...). Inclusion probabilities are proportional to
    `floor + uncertainty`, scaled to `budget` expected labels and capped at 1, then each trace is
    drawn independently. Returns the chosen indices and every trace's inclusion probability, which
    `corrected_rate` needs.

    The floor caps how far a trace's chance can rise above the rest: with uncertainty in [0, 1], at
    most (floor + 1) / floor times. A noisy signal, such as one repeat's disagreement, undersamples
    half of the truly uncertain traces, and a wide ratio then widens the interval: at floor 0.2 it
    cost labels against uniform sampling (0.66x), at 1.0 it did not (0.99x), and with the rates
    measured on a real judge 1.0 did as well as 0.2 (bench/planner_sensitivity.py).
    """
    n = len(uncertainty)
    if not 0 < budget <= n:
        raise ValueError('budget must be between 1 and the number of traces')
    if floor <= 0:
        raise ValueError('floor must be positive: every trace needs a chance of being labelled')
    raw = [floor + max(0.0, u) for u in uncertainty]
    pi = [0.0] * n
    remaining, free = float(budget), list(range(n))
    while free:  # water-filling: cap at 1 and spread the excess over the rest
        total = sum(raw[i] for i in free)
        scale = remaining / total
        capped = [i for i in free if raw[i] * scale >= 1]
        if not capped:
            for i in free:
                pi[i] = raw[i] * scale
            break
        for i in capped:
            pi[i] = 1.0
        remaining -= len(capped)
        free = [i for i in free if i not in set(capped)]
    rng = random.Random(seed)
    chosen = [i for i in range(n) if rng.random() < pi[i]]
    return chosen, pi
