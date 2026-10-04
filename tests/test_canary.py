import math

import pytest

from phoenix_evidence._canary import canary, count_flips, log_evidence


def one_step(s: int, n: int, p: float, allowed: float) -> float:
    """E[evidence after one more check | now] / evidence now, exactly."""
    now = log_evidence(s, n, allowed)
    return p * math.exp(log_evidence(s + 1, n + 1, allowed) - now) + (1 - p) * math.exp(
        log_evidence(s, n + 1, allowed) - now
    )


@pytest.mark.parametrize('rate', [0.0, 0.02, 0.05])
def test_evidence_never_grows_on_average_without_drift(rate):
    # Ville's inequality needs a supermartingale under every rate in the null, not only its edge.
    worst = max(one_step(s, n, rate, 0.05) for n in range(120) for s in range(n + 1))
    assert worst <= 1 + 1e-9


def test_evidence_grows_on_average_with_drift():
    # The negative control for the test above: a check that could not grow would never alarm.
    assert one_step(3, 60, 0.15, 0.05) > 1


def test_heterogeneous_examples_are_covered():
    # Examples flip at different rates (average = allowed); the product of their one-check ratios
    # still has expectation at most 1 (AM-GM), checked exactly for a rate mixture.
    rates, q, allowed = [0.0, 0.01, 0.14], 0.3, 0.05
    expectation = math.prod(r * q / allowed + (1 - r) * (1 - q) / (1 - allowed) for r in rates)
    assert sum(rates) / len(rates) == pytest.approx(allowed)
    assert expectation <= 1


def test_canary_alarms_on_drift_and_stays_quiet_on_noise():
    quiet = canary([(f'day {d}', 50, 2) for d in range(90)], allowed=0.05)  # 4%, under the allowed 5%
    assert not quiet.drifted and 'No drift shown' in str(quiet)
    loud = canary([(f'day {d}', 50, 2) for d in range(10)] + [(f'day {d}', 50, 10) for d in range(10, 20)],
                  allowed=0.05)  # fmt: skip
    assert loud.drifted and loud.first_alarm.label in {f'day {d}' for d in range(10, 20)}
    assert 'DRIFT' in str(loud)
    assert all(look.drifted for look in loud.looks[loud.looks.index(loud.first_alarm) :])


def test_count_flips_counts_errors_and_every_repetition():
    reference = {'a': 'pass', 'b': 'fail', 'c': 'pass'}
    assert count_flips(reference, {'a': ['pass', 'fail'], 'b': [None], 'z': ['pass']}) == (3, 2)


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        log_evidence(1, 10, 0.0)
    with pytest.raises(ValueError):
        canary([('d', 5, 6)], allowed=0.05)


def test_log_tail_matches_the_plain_formula_where_it_does_not_underflow():
    from phoenix_evidence._intervals import _incomplete_beta

    def plain(s, n, allowed):
        a, b = 1.0, (1 - allowed) / allowed

        def mass(x, y):
            return math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y) + math.log(_incomplete_beta(y, x, 1 - allowed))

        return mass(a + s, b + n - s) - mass(a, b) - s * math.log(allowed) - (n - s) * math.log1p(-allowed)

    for s, n in [(0, 10), (3, 50), (40, 400), (0, 2000), (150, 2000), (900, 2000)]:
        assert log_evidence(s, n, 0.05) == pytest.approx(plain(s, n, 0.05), rel=1e-9, abs=1e-9)


def test_drift_after_a_long_clean_history_is_still_caught():
    # Review 3: after 15,000 clean checks the tail underflowed and the evidence read as exactly zero
    # (true: about 0.001). It only underflows far below the allowed rate, so no alarm decision changed;
    # the first assertion fails on the old code, the rest guards the decision.
    assert math.isfinite(log_evidence(0, 15_000, 0.05))
    history = [('clean', 15_000, 0)] + [(f'day {d}', 500, 150) for d in range(20)]  # 30% flips
    report = canary(history, allowed=0.05)
    assert report.drifted and report.first_alarm.label != 'clean'
