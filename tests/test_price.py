import random

import pytest

from phoenix_evidence._ppi import corrected_rate
from phoenix_evidence._price import price_of_certainty


def test_planned_labels_give_the_promised_width_in_corrected_rate():
    # The plan must match what corrected_rate reports, not an approximation of it.
    traces, target, d = 2000, 0.10, 0.1
    price = price_of_certainty(traces, target, judge_cost=0.001, human_cost=1.0, disagreement=d)
    n = price.corrected.labels
    rng = random.Random(0)
    widths = []
    for _ in range(300):
        judge = [float(rng.random() < 0.8) for _ in range(traces)]
        flips = set(rng.sample(range(traces), int(d * traces)))
        human = [1 - j if i in flips else j for i, j in enumerate(judge)]
        sample = rng.sample(range(traces), n)
        r = corrected_rate(judge, {i: human[i] for i in sample})
        widths.append(r.interval[1] - r.interval[0])
    assert sum(widths) / len(widths) == pytest.approx(target, rel=0.05)
    assert price.human_only.labels > n


def test_the_cheapest_plan_follows_the_costs():
    cheap_humans = price_of_certainty(5000, 0.1, judge_cost=0.01, human_cost=0.001)
    assert cheap_humans.cheapest.name == 'human labels only'
    dear_humans = price_of_certainty(5000, 0.1, judge_cost=0.01, human_cost=5.0)
    assert dear_humans.cheapest.name.startswith('judge')
    be = dear_humans.break_even_human_cost
    assert price_of_certainty(5000, 0.1, 0.01, be * 1.01).cheapest.name.startswith('judge')
    assert price_of_certainty(5000, 0.1, 0.01, be * 0.99).cheapest.name == 'human labels only'


def test_a_judge_that_always_disagrees_buys_nothing():
    p = price_of_certainty(5000, 0.1, judge_cost=0.0, human_cost=1.0, disagreement=1.0)
    assert p.corrected.labels >= p.human_only.labels and p.break_even_human_cost is None
    assert 'cannot reach' in str(price_of_certainty(10, 0.01, 0.0, 1.0))
