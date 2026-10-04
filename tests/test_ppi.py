import random

import pytest

from phoenix_evidence._ppi import corrected_rate, plan_labels


def test_labelling_everything_gives_the_human_rate():
    human = {i: i % 4 != 0 for i in range(40)}
    judge = [1] * 40  # a judge that passes everything
    r = corrected_rate(judge, human, inclusion=[1.0] * 40)
    assert r.estimate == pytest.approx(0.75)
    assert r.judge_rate == 1.0


def test_corrected_rate_moves_a_lenient_judge_towards_the_humans():
    rng = random.Random(0)
    y = [int(rng.random() < 0.7) for _ in range(3000)]
    f = [1 if yi or rng.random() < 0.4 else 0 for yi in y]  # passes 40% of failures
    sample = rng.sample(range(3000), 200)
    r = corrected_rate(f, {i: y[i] for i in sample})
    truth = sum(y) / len(y)
    assert r.judge_rate > truth + 0.08
    assert r.interval[0] <= truth <= r.interval[1]
    assert r.interval[1] - r.interval[0] < r.human_only[1] - r.human_only[0]


def test_plan_spends_the_budget_and_never_excludes_a_trace():
    uncertainty = [0.0] * 900 + [1.0] * 100
    chosen, pi = plan_labels(uncertainty, 100)
    assert sum(pi) == pytest.approx(100)
    assert all(0 < p <= 1 for p in pi)
    assert pi[-1] == pytest.approx(pi[0] * 2)  # unsure traces twice as likely at the default floor
    assert plan_labels(uncertainty, 100, floor=0.2)[1][-1] == pytest.approx(0.2 * 6 / (0.2 * 900 + 1.2 * 100) * 100)


def test_plan_caps_probabilities_at_one():
    _, pi = plan_labels([0.0] * 10 + [100.0] * 5, 8)
    assert max(pi) == 1.0 and sum(pi) == pytest.approx(8)


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        corrected_rate([1, 0], {})
    with pytest.raises(ValueError):
        corrected_rate([1, 0], {0: 1}, inclusion=[0.0, 0.5])
    with pytest.raises(ValueError):
        plan_labels([0.1, 0.2], 3)


def test_estimate_is_unbiased_by_exact_enumeration():
    # Review 2's counterexample to the tuned version: judge and humans agree perfectly,
    # unequal inclusion probabilities. Enumerate every possible draw.
    import itertools

    y, f, pi = [0, 0, 1], [0, 0, 1], [1.0, 0.3, 0.7]
    expected = 0.0
    for draw in itertools.product((0, 1), repeat=3):
        p = 1.0
        for d, q in zip(draw, pi, strict=True):
            p *= q if d else 1 - q
        human = {i: y[i] for i in range(3) if draw[i]}
        if not human or p == 0:
            continue
        expected += p * corrected_rate(f, human, inclusion=pi, min_ratio=0).estimate
    # Draws without index 0 are impossible (pi = 1), so every possible draw has a label.
    assert expected == pytest.approx(1 / 3)


def test_a_census_gives_the_exact_rate():
    y = [i % 2 for i in range(100)]
    r = corrected_rate([0] * 100, {i: y[i] for i in range(100)}, inclusion=[1.0] * 100)
    assert r.estimate == 0.5 and r.interval == (0.5, 0.5)


def test_almost_never_sampled_traces_are_refused():
    with pytest.raises(ValueError, match='almost never labelled'):
        corrected_rate([0] * 100, {0: 1}, inclusion=[1.0] * 50 + [0.0001] * 50)


def test_interval_ends_stay_in_zero_one():
    r = corrected_rate([0] * 100, {i: 1 for i in range(50)}, inclusion=[0.5] * 100)
    assert 0 <= r.interval[0] <= r.interval[1] <= 1


def test_bad_shapes_are_refused():
    with pytest.raises(ValueError):
        corrected_rate([1, 0, 1], {0: 1}, inclusion=[0.5, 0.5])
    with pytest.raises(ValueError):
        corrected_rate([1, 0], {5: 1})
    with pytest.raises(ValueError):
        plan_labels([0.0, 0.0], 1, floor=0)
