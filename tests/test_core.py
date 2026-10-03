import random

import pytest

from phoenix_evidence import (
    Direction,
    Verdict,
    agreement,
    clopper_pearson,
    cohen_kappa,
    compare,
    constant_judge,
    decide_rate,
    examples_to_pass,
    holm,
    pass_probability,
    rate_interval,
    sign_flip_p_value,
)
from phoenix_evidence._gate import min_successes_to_pass


def test_clopper_pearson_matches_known_values():
    # R: binom.test(13, 16)$conf.int -> 0.5435435 0.9595263
    low, high = clopper_pearson(13, 16)
    assert low == pytest.approx(0.5435435, abs=1e-6)
    assert high == pytest.approx(0.9595263, abs=1e-6)
    assert clopper_pearson(0, 10)[0] == 0.0
    assert clopper_pearson(10, 10)[1] == 1.0


def test_faithfulness_sized_suite_cannot_pass_a_0_7_gate_below_16_of_16():
    assert min_successes_to_pass(16, 0.7) == 16
    assert decide_rate([[True]] * 13 + [[False]] * 3, 0.7).verdict is Verdict.NOT_ENOUGH_EVIDENCE


def test_gate_counts_crashed_runs_as_failures():
    # Phoenix #15425: 3 of 10 runs score 1, 7 crash before scoring. Dropping them reads 100%.
    decision = decide_rate([[True]] * 3 + [[None]] * 7, 0.9)
    assert decision.estimate == pytest.approx(0.3)
    assert decision.missing == 7
    assert decision.verdict is Verdict.FAIL


def test_gate_fails_when_clearly_below_and_passes_when_clearly_above():
    assert decide_rate([[True]] * 20 + [[False]] * 80, 0.7).verdict is Verdict.FAIL
    assert decide_rate([[True]] * 98 + [[False]] * 2, 0.8).verdict is Verdict.PASS


def test_repetitions_do_not_narrow_the_interval_beyond_the_examples():
    once = rate_interval([[True]] * 9 + [[False]])
    ten_times = rate_interval([[True] * 10] * 9 + [[False] * 10])
    assert ten_times == once  # perfectly repeatable judgments add no new examples


def test_constant_judge_passes_an_all_positive_suite():
    check = constant_judge(['pii_detected'] * 150, 0.9)
    assert check.passes_gate and check.accuracy == 1.0
    assert not constant_judge(['a'] * 50 + ['b'] * 50, 0.7).passes_gate


def test_exact_pass_probability_and_sample_size_agree():
    n = examples_to_pass(0.85, 0.8)
    assert n is not None
    assert pass_probability(n, 0.85, 0.8) >= 0.8
    assert examples_to_pass(0.8, 0.8) is None


def test_sign_flip_is_exact_for_small_samples():
    rng = random.Random(0)
    assert sign_flip_p_value([1, 1, 1, 1, 1], rng) == pytest.approx(2 / 32)
    assert sign_flip_p_value([0, 0, 0], rng) == 1.0


def test_identical_experiments_show_no_difference():
    a = {str(i): [i % 3 != 0] for i in range(60)}
    result = compare(a, dict(a))
    assert result.direction is Direction.NO_DETECTABLE_DIFFERENCE
    assert result.difference == 0


def test_crashing_on_hard_examples_is_not_an_improvement():
    # A scores 1,1,0,0. B crashes (None) on the two hard examples. Dropping crashes reads B = 1.0.
    a = {'1': [1], '2': [1], '3': [0], '4': [0]}
    b = {'1': [1], '2': [1], '3': [None], '4': [None]}
    assert compare(a, b).difference == 0
    dropped = compare(a, b, missing_as=None)
    assert dropped.examples == 2 and dropped.notes


def test_clear_improvement_is_detected():
    a = {str(i): [i % 2 == 0] for i in range(80)}
    b = {str(i): [True] for i in range(80)}
    assert compare(a, b).direction is Direction.BETTER


def test_kappa_is_none_when_undefined_and_matches_hand_value():
    assert cohen_kappa([('a', 'a'), ('a', 'a')]) is None
    pairs = [('y', 'y')] * 20 + [('n', 'n')] * 15 + [('y', 'n')] * 3 + [('n', 'y')] * 2
    # po = 35/40; pe = (23*22 + 17*18) / 1600 = 0.5075
    assert cohen_kappa(pairs) == pytest.approx((0.875 - 0.5075) / (1 - 0.5075))


def test_agreement_interval_contains_estimate_and_counts_examples():
    by_example = [[('y', 'y')]] * 20 + [[('n', 'n')]] * 15 + [[('y', 'n')]] * 3 + [[('n', 'y')]] * 2
    result = agreement(by_example, resamples=500)
    assert result.examples == 40
    assert result.kappa_interval[0] <= result.kappa <= result.kappa_interval[1]
    assert result.recall_by_class['y'][:2] == (20, 23)


def test_holm_keeps_only_what_survives_together():
    kept = holm({'accuracy': 0.01, 'latency': 0.04, 'cost': 0.30})
    assert kept == {'accuracy': True, 'latency': False, 'cost': False}


def test_gate_estimate_lies_in_its_interval_when_repeats_are_uneven():
    decision = decide_rate([[True]] * 40 + [[False] * 1000], 0.8)
    assert decision.interval[0] <= decision.estimate <= decision.interval[1]
    assert decision.estimate == pytest.approx(40 / 41)


def test_recall_counts_judgments_not_majority_votes():
    by_example = [[('a', 'a'), ('a', 'b')]] * 20 + [[('b', 'b'), ('b', 'a')]] * 20
    result = agreement(by_example, resamples=200)
    correct, judged, (low, high) = result.recall_by_class['a']
    assert (correct, judged) == (20, 40)
    assert low <= 0.5 <= high


def test_an_example_with_no_scores_counts_as_a_crash():
    result = compare({'ok': [1], 'crash': [0]}, {'ok': [1], 'crash': []}, bootstrap=100)
    assert result.examples == 2 and result.missing_b == 1


def test_examples_to_pass_returns_the_first_size():
    n = examples_to_pass(0.75, 0.7)
    assert all(pass_probability(m, 0.75, 0.7) >= 0.8 for m in range(n, n + 20))
    assert not all(pass_probability(m, 0.75, 0.7) >= 0.8 for m in range(n - 1, n + 19))
