"""Regression tests for the third independent review (results/review/codex_review_3.md)."""

import itertools
from types import SimpleNamespace

import pytest

from phoenix_evidence._doctor import Example, diagnose, pair_accuracy
from phoenix_evidence._jury import jury
from phoenix_evidence._ppi import corrected_rate
from phoenix_evidence._price import _human_width, price_of_certainty
from phoenix_evidence.phoenix import judge_canary


def _experiment(label, score, indices=range(100)):
    return {
        'task_runs': [{'id': str(i), 'dataset_example_id': str(i), 'repetition_number': 1} for i in indices],
        'evaluation_runs': [{'experiment_run_id': str(i), 'name': 'judge', 'result': {'label': label, 'score': score}}
                            for i in indices],
    }  # fmt: skip


def _client(store):
    return SimpleNamespace(experiments=SimpleNamespace(get_experiment=lambda experiment_id: store[experiment_id]))


def test_canary_compares_labels_not_only_scores():
    # A judge that switched every label from A to B, with the same score, has drifted.
    c = _client({'ref': _experiment('A', 1), 'changed': _experiment('B', 1)})
    look = judge_canary(c, 'ref', ['changed'], 'judge', 0.05).looks[-1]
    assert look.flips == 100


def test_canary_counts_a_skipped_example_as_a_flip():
    # A check on 5 hand-picked examples must not be read as a fair sample of the frozen set.
    c = _client({'ref': _experiment('A', 1), 'partial': _experiment('A', 1, range(5))})
    look = judge_canary(c, 'ref', ['partial'], 'judge', 0.05).looks[-1]
    assert (look.checks, look.flips) == (100, 95)


def test_canary_refuses_a_replayed_check():
    c = _client({'ref': _experiment('A', 1, range(10)), 'one': _experiment('A', 1, range(10))})
    with pytest.raises(ValueError):
        judge_canary(c, 'ref', ['one'] * 100, 'judge', 0.05)
    with pytest.raises(ValueError):
        judge_canary(c, 'ref', ['ref'], 'judge', 0.05)


def test_price_finds_the_first_label_count_that_works():
    # Clopper-Pearson widths are not monotone in n; bisection returned 62 where 41 already works.
    target = 0.0875501642259883
    p = price_of_certainty(150, target, 0.002, 1.0, pass_rate=0.01)
    expected = next(n for n in range(1, 151) if _human_width(n, 0.01, 0.05) <= target)
    assert p.human_only.labels == expected == 41


def test_jury_of_judges_that_fail_on_different_cases():
    j = jury([['a', 'b'], ['b', 'a']], ['a', 'a'])  # errors perfectly anti-correlated
    assert j.correlation == pytest.approx(-1) and j.effective_judges is None
    assert 'different cases' in str(j)


def test_doctor_keeps_numbers_apart():
    d = diagnose([Example('a', {'x': 'the total is 1.0'}, 'a'), Example('b', {'x': 'the total is 1,0'}, 'b')])
    assert d.exact_copies == [] and d.conflicting == []


def test_pair_accuracy_scores_only_paired_repetitions():
    r = pair_accuracy([('a', 'b')], {'a': 'yes', 'b': 'no'}, {'a': ['yes', 'wrong'], 'b': ['no']})
    assert r['case_accuracy'] == 1.0 and r['pair_accuracy'] == 1.0 and r['pair_judgments'] == 1


def test_raw_estimate_is_unbiased_where_the_clipped_one_is_not():
    f, y, pi = [0.9] * 10, [0.0] * 10, [0.5] * 10
    raw, clipped = [], []
    for bits in itertools.product([0, 1], repeat=10):
        human = {i: y[i] for i, b in enumerate(bits) if b}
        if human:
            r = corrected_rate(f, human, pi)
            raw.append(r.raw_estimate)
            clipped.append(r.estimate)
    # Every non-empty draw (the empty one, 1 in 1024, has no estimate): raw averages to the truth up to
    # the missing empty draw's term; clipped is pushed up by about 0.11.
    assert sum(clipped) / len(clipped) > 0.1
    assert abs(sum(raw) / len(raw)) < 0.01
