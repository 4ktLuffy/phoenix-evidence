"""How many independent judges is a jury worth?

Running a judge three times, or three configurations of it, and taking the majority only helps as
far as their mistakes are independent. With an average pairwise correlation rho between the
judges' error indicators, k judges carry the information of k / (1 + (k - 1) rho) independent ones
(the design-effect formula for equicorrelated votes). Repeats of one model tend to make the same
mistakes, so a jury of repeats is often worth little more than one judge.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations


def _phi(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    n = len(a)
    pa, pb = sum(a) / n, sum(b) / n
    if pa in (0, 1) or pb in (0, 1):
        return None  # a judge that never (or always) errs has no error variance
    both = sum(1 for x, y in zip(a, b, strict=True) if x and y) / n
    return (both - pa * pb) / math.sqrt(pa * (1 - pa) * pb * (1 - pb))


@dataclass(frozen=True)
class Jury:
    judges: int
    cases: int
    error_rates: list[float]
    correlation: float | None  # mean pairwise phi of the error indicators
    effective_judges: float | None
    single_accuracy: float  # the best single judge
    majority_accuracy: float

    def __str__(self) -> str:
        if self.correlation is None:
            return f'{self.judges} judges on {self.cases} cases: too few errors to measure their correlation'
        if self.effective_judges is None:
            return (f'{self.judges} judges on {self.cases} cases: errors correlate at {self.correlation:.2f}, so they '
                    f'fail on different cases; majority accuracy {self.majority_accuracy:.3f} vs {self.single_accuracy:.3f}')  # fmt: skip
        return (f'{self.judges} judges on {self.cases} cases: errors correlate at {self.correlation:.2f}, so the jury is '
                f'worth {self.effective_judges:.2f} independent judges; majority accuracy {self.majority_accuracy:.3f} '
                f'vs {self.single_accuracy:.3f} for the best single judge')  # fmt: skip


def jury(labels: Sequence[Sequence[str | None]], truth: Sequence[str]) -> Jury:
    """`labels[j][i]` is judge j's label on case i (None when it failed: counted as an error)."""
    k, n = len(labels), len(truth)
    if k < 2 or any(len(row) != n for row in labels):
        raise ValueError('need at least two judges, each with a label per case')
    errors = [[row[i] is None or row[i] != truth[i] for i in range(n)] for row in labels]
    phis = [p for a, b in combinations(errors, 2) if (p := _phi(a, b)) is not None]
    rho = sum(phis) / len(phis) if phis else None
    # Negatively correlated errors (judges that fail on different cases) make the denominator zero or
    # negative: the formula does not apply, and the jury is worth at least k judges.
    effective = None if rho is None or 1 + (k - 1) * rho <= 0 else k / (1 + (k - 1) * rho)
    majority = 0
    for i in range(n):
        votes: dict[str, int] = {}
        for row in labels:
            if row[i] is not None:
                votes[row[i]] = votes.get(row[i], 0) + 1
        top = max(votes.values()) if votes else 0
        winners = [lab for lab, c in votes.items() if c == top]
        majority += len(winners) == 1 and winners[0] == truth[i]  # a tie is not a decision
    return Jury(k, n, [sum(e) / n for e in errors], rho, effective,
                1 - min(sum(e) / n for e in errors), majority / n)  # fmt: skip
