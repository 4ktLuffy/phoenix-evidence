from phoenix_evidence import Direction, switch_impact


def test_identical_judges_change_nothing():
    labels = {str(i): 'pass' if i % 3 else 'fail' for i in range(60)}
    impact = switch_impact(labels, dict(labels), 'pass')
    assert impact.flips == 0 and impact.pass_rate.direction is Direction.NO_DETECTABLE_DIFFERENCE


def test_a_stricter_judge_lowers_the_pass_rate_and_agrees_more_with_humans():
    human = {str(i): 'pass' if i < 70 else 'fail' for i in range(100)}
    old = {k: 'pass' for k in human}  # passes everything
    new = dict(human)  # agrees with humans
    impact = switch_impact(old, new, 'pass', human=human)
    assert impact.flips == 30
    assert impact.pass_rate.direction is Direction.WORSE  # lower pass rate
    assert impact.human_agreement.direction is Direction.BETTER
    assert impact.flipped_items == sorted(k for k in human if human[k] == 'fail')


def test_only_shared_items_count():
    impact = switch_impact({'a': 'pass', 'b': 'fail'}, {'b': 'pass', 'c': 'pass'}, 'pass')
    assert impact.items == 1 and impact.flips == 1
