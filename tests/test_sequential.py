import math

import pytest

from phoenix_evidence._sequential import SequentialComparison, log_evidence


def test_evidence_is_a_martingale_under_a_fair_coin():
    # E[next | now] == now exactly when each disagreement is a fair coin: Ville's inequality applies.
    for b in range(40):
        for w in range(40):
            now = log_evidence(b, w)
            nxt = 0.5 * math.exp(log_evidence(b + 1, w) - now) + 0.5 * math.exp(log_evidence(b, w + 1) - now)
            assert nxt == pytest.approx(1.0, abs=1e-9)


def test_evidence_grows_under_a_real_difference():
    # Negative control: a test whose evidence cannot grow would never decide.
    now = log_evidence(30, 10)
    nxt = 0.8 * math.exp(log_evidence(31, 10) - now) + 0.2 * math.exp(log_evidence(30, 11) - now)
    assert nxt > 1


def test_decides_once_and_in_the_right_direction():
    s = SequentialComparison()
    s.extend([(0, 1)] * 3 + [(1, 1)] * 50)  # three wins and ties: not enough
    assert s.decision is None and 'Not decided' in str(s)
    s.extend([(0, 1)] * 12)
    assert s.decision == 'candidate better' and s.decided_at is not None and 'DECIDED' in str(s)
    first = s.decided_at
    s.extend([(1, 0)] * 5)
    assert s.decided_at == first  # a decision is not revisited


def test_lower_is_better_flips_the_direction():
    s = SequentialComparison(higher_is_better=False).extend([(0.0, 1.0)] * 15)  # errors rose
    assert s.decision == 'candidate worse'
