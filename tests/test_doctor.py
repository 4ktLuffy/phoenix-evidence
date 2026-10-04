from phoenix_evidence._doctor import Example, diagnose, pair_accuracy

TEXT = (
    'the refund for order 1234 was issued on monday and should arrive within five business days; '
    'if it has not arrived by then please reply to this message with your bank name and the last '
    'four digits of the card so that our payments team can trace it with the processor directly'
)


def test_copies_conflicts_and_leakage_are_found():
    examples = [
        Example('a', {'q': TEXT}, 'pass', ('train',)),
        Example('b', {'q': TEXT.upper() + '  '}, 'pass', ('test',)),  # same text: copy, across splits
        Example('c', {'q': TEXT.replace('five', 'ten')}, 'fail', ('test',)),  # near-copy, other label
        Example('d', {'q': 'completely different words about shipping a parcel abroad today'}, None, ('train', 'test')),
    ]
    d = diagnose(examples)
    assert d.exact_copies == [['a', 'b']]
    assert {(x, y) for x, y, _ in d.conflicting} == {('a', 'c'), ('b', 'c')}
    assert ('a', 'b', 1.0) in d.cross_split and any({x, y} == {'a', 'c'} for x, y, _ in d.cross_split)
    assert d.in_several_splits == ['d'] and d.unlabelled == ['d']
    assert len(d.problems()) == 5


def test_a_clean_dataset_has_no_problems():
    # Negative control: distinct examples, balanced labels, a bar a real judge can clear.
    examples = [Example(str(i), {'q': f'question {i} ' + ' '.join(f'w{i}x{k}' for k in range(8))}, 'pass' if i % 2 else 'fail')
                for i in range(200)]  # fmt: skip
    d = diagnose(examples, threshold=0.7)
    assert d.problems() == [] and str(d).endswith('no problems found')


def test_constant_judge_warning_comes_through():
    examples = [
        Example(str(i), {'q': f'q{i} alpha beta gamma delta'}, 'pass' if i < 90 else 'fail') for i in range(100)
    ]
    assert any('always answers' in p for p in diagnose(examples, threshold=0.8).problems())


def test_pair_accuracy_gives_nothing_for_one_label_on_both():
    pairs, truth = [('a', 'b'), ('c', 'd')], {'a': 'y', 'b': 'n', 'c': 'y', 'd': 'n'}
    constant = pair_accuracy(pairs, truth, {k: ['y'] for k in truth})
    assert constant['case_accuracy'] == 0.5 and constant['pair_accuracy'] == 0 and constant['same_label_on_both'] == 1
    perfect = pair_accuracy(pairs, truth, {k: [v, v] for k, v in truth.items()})
    assert perfect['pair_accuracy'] == 1 and perfect['pair_judgments'] == 4
