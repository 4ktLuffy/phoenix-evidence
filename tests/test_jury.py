import random

import pytest

from phoenix_evidence._jury import jury


def test_copies_are_worth_one_judge():
    truth = ['y', 'n'] * 50
    judge = ['n' if i % 7 == 0 else t for i, t in enumerate(truth)]
    j = jury([judge, list(judge), list(judge)], truth)
    assert j.correlation == pytest.approx(1.0) and j.effective_judges == pytest.approx(1.0)
    assert j.majority_accuracy == j.single_accuracy


def test_independent_judges_are_worth_their_number():
    # Negative control for the above: independent errors give rho near 0 and about k judges.
    rng = random.Random(0)
    truth = [rng.choice('yn') for _ in range(20000)]
    judges = [[('n' if t == 'y' else 'y') if rng.random() < 0.2 else t for t in truth] for _ in range(3)]
    j = jury(judges, truth)
    assert abs(j.correlation) < 0.03 and j.effective_judges == pytest.approx(3, abs=0.2)
    assert j.majority_accuracy > j.single_accuracy + 0.05  # 0.896 vs 0.8 in theory


def test_failures_count_as_errors_and_shapes_are_checked():
    j = jury([['y', None, 'n'], ['y', 'y', 'y']], ['y', 'y', 'n'])
    assert j.error_rates == [1 / 3, 1 / 3]
    with pytest.raises(ValueError):
        jury([['y']], ['y'])
