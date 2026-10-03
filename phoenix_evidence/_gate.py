"""A gate that can say "not enough evidence", and the checks a gate needs before it means anything."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from phoenix_evidence._intervals import clopper_pearson, rate_interval


class Verdict(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    NOT_ENOUGH_EVIDENCE = 'NOT_ENOUGH_EVIDENCE'


@dataclass(frozen=True)
class RateDecision:
    """A pass rate against a bar, decided on an interval."""

    verdict: Verdict
    estimate: float
    interval: tuple[float, float]
    threshold: float
    examples: int
    judgments: int
    missing: int

    def __str__(self) -> str:
        low, high = self.interval
        tail = f', {self.missing} missing counted as failures' if self.missing else ''
        return (f'{self.verdict.value}: {self.estimate:.3f} [{low:.3f}, {high:.3f}] vs {self.threshold} '
                f'on {self.examples} examples ({self.judgments} judgments{tail})')  # fmt: skip


def decide_rate(
    per_example: Sequence[Sequence[bool | None]],
    threshold: float,
    alpha: float = 0.05,
) -> RateDecision:
    """PASS when the interval clears the bar, FAIL when it sits below it, otherwise NOT_ENOUGH_EVIDENCE.

    `per_example` holds the judgments of each example (several when repeated). `None` is a run that
    crashed or never recorded a score: it counts as a failure, because a gate that drops it passes
    a suite whose hard cases crash (Phoenix #15425). The interval is two-sided at `alpha`, so each
    of PASS and FAIL is wrong at most `alpha / 2` of the time at the boundary.
    """
    missing = sum(x is None for e in per_example for x in e)
    cleaned = [[bool(x) for x in e] for e in per_example if len(e) > 0]
    judgments = sum(len(e) for e in cleaned)
    # Each example counts once, by its share of passing judgments: the same basis as the interval,
    # so an example judged 1000 times does not outweigh forty judged once.
    estimate = sum(sum(e) / len(e) for e in cleaned) / len(cleaned) if cleaned else 0.0
    low, high = rate_interval(cleaned, alpha)
    verdict = Verdict.PASS if low >= threshold else Verdict.FAIL if high < threshold else Verdict.NOT_ENOUGH_EVIDENCE
    return RateDecision(verdict, estimate, (low, high), threshold, len(cleaned), judgments, missing)


@dataclass(frozen=True)
class ConstantJudgeCheck:
    """What a judge that ignores its input would score on this suite."""

    label: str
    accuracy: float
    passes_gate: bool
    classes: dict[str, int]

    def __str__(self) -> str:
        verb = 'PASSES' if self.passes_gate else 'fails'
        return f'a judge that always answers {self.label!r} scores {self.accuracy:.3f} and {verb} the gate'


def constant_judge(truth: Sequence[str], threshold: float) -> ConstantJudgeCheck:
    """The best accuracy a constant answer reaches: the floor any real judge must beat.

    A suite where this passes the gate cannot tell a working judge from a broken one.
    """
    counts = Counter(truth)
    label, top = counts.most_common(1)[0]
    accuracy = top / len(truth)
    return ConstantJudgeCheck(label, accuracy, accuracy >= threshold, dict(counts))


@lru_cache(maxsize=65536)
def min_successes_to_pass(n: int, threshold: float, alpha: float = 0.05) -> int | None:
    """The fewest correct out of n for which an exact interval clears the bar; None if no score does.

    The exact lower bound rises with k, so this is a binary search.
    """
    if n <= 0 or clopper_pearson(n, n, alpha)[0] < threshold:
        return None
    low, high = 0, n
    while low < high:
        mid = (low + high) // 2
        if clopper_pearson(mid, n, alpha)[0] >= threshold:
            high = mid
        else:
            low = mid + 1
    return low
