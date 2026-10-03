"""Is version B really better than version A, or is it noise?

The comparison is paired: both versions ran on the same dataset examples, so each example gives
one difference, B minus A, averaged over its repetitions. The decision comes from a sign-flip
(permutation) test on those differences. It is exact (up to 16 differing examples; Monte Carlo
above) under the null that A and B are interchangeable on each example, which is what "no
difference between the versions" means for a paired run. It is not a test of equal means alone:
differences that are skewed but average zero can be rejected more often than alpha. The interval on the mean difference is a
bootstrap over examples and is descriptive; its coverage is measured in `bench/coverage.py`.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from phoenix_evidence._power import detectable_difference, paired_examples_needed

Scores = Mapping[str, Sequence[float | bool | None]]


class Direction(str, Enum):
    BETTER = 'B_BETTER'
    WORSE = 'B_WORSE'
    NO_DETECTABLE_DIFFERENCE = 'NO_DETECTABLE_DIFFERENCE'


@dataclass(frozen=True)
class Comparison:
    direction: Direction
    mean_a: float
    mean_b: float
    difference: float
    interval: tuple[float, float]
    p_value: float
    examples: int
    discordant: int
    missing_a: int
    missing_b: int
    unpaired: int
    detectable: float | None
    needed_for_observed: int | None
    notes: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        low, high = self.interval
        detect = f'{self.detectable:.3f}' if self.detectable is not None else 'n/a'
        need = self.needed_for_observed if self.needed_for_observed is not None else 'n/a'
        return (f'{self.direction.value}: B-A = {self.difference:+.3f} [{low:+.3f}, {high:+.3f}], '
                f'p = {self.p_value:.3g}, {self.examples} paired examples; smallest detectable '
                f'difference {detect}; examples needed for the observed difference: {need}')  # fmt: skip


def _example_means(scores: Scores, missing_as: float | None) -> tuple[dict[str, float], int]:
    means: dict[str, float] = {}
    missing = 0
    for key, values in scores.items():
        kept: list[float] = []
        # An example listed with no scores ran and produced nothing: one missing run, not absent.
        for v in values if len(values) else [None]:
            if v is None:
                missing += 1
                if missing_as is not None:
                    kept.append(missing_as)
            else:
                kept.append(float(v))
        if kept:
            means[key] = sum(kept) / len(kept)
    return means, missing


def sign_flip_p_value(differences: Sequence[float], rng: random.Random, draws: int = 20_000) -> float:
    """Two-sided p-value for mean difference 0, flipping the sign of each difference.

    Exact enumeration up to 16 non-zero differences, otherwise Monte Carlo with the observed
    statistic counted once (so the p-value is never 0 and the test stays valid).
    """
    nonzero = [d for d in differences if d != 0]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero))
    tol = 1e-12
    if len(nonzero) <= 16:
        hits = 0
        total = 0
        for signs in itertools.product((1, -1), repeat=len(nonzero)):
            total += 1
            if abs(sum(s * d for s, d in zip(signs, nonzero, strict=True))) >= observed - tol:
                hits += 1
        return hits / total
    hits = 1
    for _ in range(draws):
        if abs(sum(d if rng.random() < 0.5 else -d for d in nonzero)) >= observed - tol:
            hits += 1
    return hits / (draws + 1)


def compare(
    a: Scores,
    b: Scores,
    alpha: float = 0.05,
    missing_as: float | None = 0.0,
    power: float = 0.8,
    seed: int = 0,
    bootstrap: int = 4000,
) -> Comparison:
    """Compare two experiments run on the same examples.

    `a` and `b` map an example id to its scores (one per repetition; booleans are 1/0). `None` is
    a run that crashed or never got a score. By default it counts as 0, the intention-to-treat
    reading: a version does not improve by crashing on the hard examples. Pass `missing_as=None`
    to drop such runs instead, and the result says how many were dropped.
    """
    rng = random.Random(seed)
    mean_a, missing_a = _example_means(a, missing_as)
    mean_b, missing_b = _example_means(b, missing_as)
    shared = sorted(set(mean_a) & set(mean_b))
    unpaired = len(set(mean_a) ^ set(mean_b))
    notes: list[str] = []
    if unpaired:
        notes.append(f'{unpaired} examples ran in only one version and are left out of the comparison')
    if missing_as is None and (missing_a or missing_b):
        notes.append(f'dropped {missing_a} missing runs in A and {missing_b} in B; the means are over different runs')
    n = len(shared)
    if n == 0:
        return Comparison(Direction.NO_DETECTABLE_DIFFERENCE, math.nan, math.nan, math.nan, (math.nan, math.nan),
                          1.0, 0, 0, missing_a, missing_b, unpaired, None, None, notes + ['no shared examples'])  # fmt: skip
    diffs = [mean_b[k] - mean_a[k] for k in shared]
    diff = sum(diffs) / n
    p = sign_flip_p_value(diffs, rng)
    boots = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(bootstrap))
    interval = (boots[int(alpha / 2 * bootstrap)], boots[int((1 - alpha / 2) * bootstrap) - 1])
    discordant = sum(1 for d in diffs if d != 0)
    if p < alpha:
        direction = Direction.BETTER if diff > 0 else Direction.WORSE
    else:
        direction = Direction.NO_DETECTABLE_DIFFERENCE
    # Power uses the paired binary form with the observed share of examples that changed.
    p_disc = max(discordant / n, 1 / n)
    detectable = detectable_difference(n, p_disc, power, alpha)
    needed = paired_examples_needed(p_disc, abs(diff), power, alpha) if diff != 0 else None
    return Comparison(
        direction,
        sum(mean_a[k] for k in shared) / n,
        sum(mean_b[k] for k in shared) / n,
        diff,
        interval,
        p,
        n,
        discordant,
        missing_a,
        missing_b,
        unpaired,
        detectable,
        needed,
        notes,
    )


def holm(p_values: Mapping[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Holm's step-down correction: which of several metrics' differences survive, together."""
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ordered)
    result: dict[str, bool] = {}
    rejecting = True
    for i, (name, p) in enumerate(ordered):
        rejecting = rejecting and p <= alpha / (m - i)
        result[name] = rejecting
    return result
