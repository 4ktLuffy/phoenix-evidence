"""How well a judge agrees with human labels, with the margin of error Phoenix does not show.

Labels are strings, so this works for Phoenix's multi-class evaluators as well as pass/fail. Each
example is one unit of evidence: an example judged several times is resampled as a whole.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from phoenix_evidence._intervals import clopper_pearson

Pair = tuple[str, str]  # (human label, judge label)


def cohen_kappa(pairs: Sequence[Pair]) -> float | None:
    """Cohen's kappa for any number of labels; None when undefined (no pairs, or chance agreement is 1)."""
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(h == j for h, j in pairs) / n
    human = Counter(h for h, _ in pairs)
    judge = Counter(j for _, j in pairs)
    expected = sum(human[c] * judge.get(c, 0) for c in human) / (n * n)
    if expected >= 1:
        return None
    return (observed - expected) / (1 - expected)


def balanced_accuracy(pairs: Sequence[Pair]) -> float | None:
    """Mean recall over the human classes: 1/k for a constant judge on k classes, whatever the mix."""
    by_class: dict[str, list[bool]] = defaultdict(list)
    for h, j in pairs:
        by_class[h].append(h == j)
    if not by_class:
        return None
    return sum(sum(v) / len(v) for v in by_class.values()) / len(by_class)


@dataclass(frozen=True)
class Agreement:
    examples: int
    judgments: int
    accuracy: float
    accuracy_interval: tuple[float, float]
    kappa: float | None
    kappa_interval: tuple[float, float]
    balanced_accuracy: float | None
    balanced_accuracy_interval: tuple[float, float]
    recall_by_class: dict[str, tuple[int, int, tuple[float, float]]]
    human_classes: int

    def __str__(self) -> str:
        def iv(x: tuple[float, float]) -> str:
            return f'[{x[0]:.2f}, {x[1]:.2f}]'

        kappa = 'undefined' if self.kappa is None else f'{self.kappa:.2f} {iv(self.kappa_interval)}'
        lines = [f'{self.examples} examples, {self.judgments} judgments',
                 f'accuracy {self.accuracy:.2f} {iv(self.accuracy_interval)}', f'kappa {kappa}']  # fmt: skip
        if self.balanced_accuracy is not None:
            lines.append(f'balanced accuracy {self.balanced_accuracy:.2f} {iv(self.balanced_accuracy_interval)}')
        for label, (hit, total, ci) in sorted(self.recall_by_class.items()):
            lines.append(f'  recall on {label!r}: {hit}/{total} {iv(ci)}')
        return '\n'.join(lines)


def agreement(
    by_example: Sequence[Sequence[Pair]],
    alpha: float = 0.05,
    resamples: int = 2000,
    seed: int = 0,
) -> Agreement:
    """Judge-vs-human agreement on the examples given, each a list of (human, judge) pairs.

    Accuracy and per-class recall use exact intervals with each example counted once (by its
    share of agreeing judgments, rounded down, so the bound is conservative). Kappa and balanced
    accuracy use a percentile bootstrap over examples, with the kappa lower bound floored by the
    exact bound on agreement carried to kappa, because the bootstrap collapses to a point when
    every example agrees (the case where n matters most). Coverage is measured in
    `bench/coverage.py`.
    """
    clusters = [list(c) for c in by_example if c]
    pairs = [p for c in clusters for p in c]
    n = len(clusters)
    if n == 0:
        nan = (math.nan, math.nan)
        return Agreement(0, 0, math.nan, nan, None, nan, None, nan, {}, 0)
    accuracy = sum(h == j for h, j in pairs) / len(pairs)
    shares = sum(sum(h == j for h, j in c) / len(c) for c in clusters)
    acc_ci = clopper_pearson(math.floor(shares + 1e-9), n, alpha)
    acc_ci = (acc_ci[0], clopper_pearson(math.ceil(shares - 1e-9), n, alpha)[1])

    # Recall per human class, each example counted once by its share of correct judgments (the
    # same basis as accuracy). Reported as (correct judgments, judgments, interval by example).
    recall: dict[str, tuple[int, int, tuple[float, float]]] = {}
    for label in sorted({h for h, _ in pairs}):
        own = [c for c in clusters if c[0][0] == label]
        share = sum(sum(h == j for h, j in c) / len(c) for c in own)
        low = clopper_pearson(math.floor(share + 1e-9), len(own), alpha)[0]
        high = clopper_pearson(math.ceil(share - 1e-9), len(own), alpha)[1]
        correct = sum(h == j for c in own for h, j in c)
        recall[label] = (correct, sum(len(c) for c in own), (low, high))

    kappa = cohen_kappa(pairs)
    bal = balanced_accuracy(pairs)
    rng = random.Random(seed)
    kappas: list[float] = []
    bals: list[float] = []
    for _ in range(resamples):
        sample = [p for _ in range(n) for p in clusters[rng.randrange(n)]]
        k = cohen_kappa(sample)
        if k is not None:
            kappas.append(k)
        b = balanced_accuracy(sample)
        if b is not None:
            bals.append(b)
    kappa_ci = _percentile(kappas, alpha)
    if kappa is not None:
        kappa_ci = (min(kappa_ci[0], _exact_kappa_floor(pairs, clusters, alpha)), kappa_ci[1])
    return Agreement(
        n, len(pairs), accuracy, acc_ci, kappa, kappa_ci, bal, _percentile(bals, alpha), recall, len(recall)
    )


def _percentile(values: list[float], alpha: float) -> tuple[float, float]:
    if not values:
        return (math.nan, math.nan)
    values.sort()
    lo = values[max(0, int(alpha / 2 * len(values)))]
    hi = values[min(len(values) - 1, int((1 - alpha / 2) * len(values)))]
    return lo, hi


def _exact_kappa_floor(pairs: Sequence[Pair], clusters: Sequence[Sequence[Pair]], alpha: float) -> float:
    """Exact lower bound on agreement, by example, carried to kappa at the observed chance agreement."""
    n = len(pairs)
    human = Counter(h for h, _ in pairs)
    judge = Counter(j for _, j in pairs)
    expected = sum(human[c] * judge.get(c, 0) for c in human) / (n * n)
    if expected >= 1:
        return -1.0
    shares = sum(sum(h == j for h, j in c) / len(c) for c in clusters)
    low = clopper_pearson(math.floor(shares + 1e-9), len(clusters), alpha)[0]
    return max(-1.0, (low - expected) / (1 - expected))
