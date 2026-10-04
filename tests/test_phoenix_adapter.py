"""The Phoenix-facing commands, against a fake client shaped like phoenix.client's return values."""

import json
from types import SimpleNamespace

from phoenix_evidence.cli import main as cli
from phoenix_evidence.phoenix import (
    audit_labels,
    compare_experiments,
    experiment_scores,
    feedback_certificate,
    pairs_from_span_annotations,
)


def experiment(eid, outcomes):
    """outcomes: example id -> 'pass' | 'fail' | 'crash' (task raised; the evaluator errored)."""
    runs, evals = [], []
    for k, (example, outcome) in enumerate(outcomes.items()):
        rid = f'{eid}-run-{k}'
        runs.append({'id': rid, 'dataset_example_id': example, 'repetition_number': 1,
                     'error': 'boom' if outcome == 'crash' else None})  # fmt: skip
        if outcome == 'crash':
            evals.append(SimpleNamespace(experiment_run_id=rid, name='correct', error='TypeError', result=None))
        else:
            evals.append(SimpleNamespace(experiment_run_id=rid, name='correct', error=None,
                                         result={'score': 1.0 if outcome == 'pass' else 0.0}))  # fmt: skip
    return {'experiment_id': eid, 'task_runs': runs, 'evaluation_runs': evals}


class FakeClient:
    def __init__(self, experiments=(), annotations=(), datasets=None):
        store = {e['experiment_id']: e for e in experiments}
        self.experiments = SimpleNamespace(get_experiment=lambda experiment_id: store[experiment_id])
        self.spans = SimpleNamespace(get_spans=lambda **kw: [], get_span_annotations=lambda **kw: list(annotations))
        self.datasets = SimpleNamespace(get_dataset=lambda dataset: datasets[dataset])


BASE = {str(i): 'pass' if i < 84 else 'fail' for i in range(100)}
# Crashes on 10 of the baseline's failures; Phoenix averages the rest and shows it as better.
FRAGILE = {str(i): 'pass' if i < 84 else ('crash' if i < 94 else 'fail') for i in range(100)}


def test_crashed_runs_are_scored_not_dropped():
    client = FakeClient([experiment('a', BASE), experiment('b', FRAGILE)])
    scores = experiment_scores(client, 'b')
    assert scores['correct']['90'] == [None]
    assert scores['task_error']['90'] == [1.0]
    result = compare_experiments(client, 'a', 'b')
    rows = {r['metric']: r for r in result.rows()}
    assert rows['correct']['difference'] == 0  # dropping crashes would read 84/90 = 0.933 vs 0.84
    assert result.regressions() == ['task_error']


def test_cli_compare_fails_on_regression_only_when_asked(monkeypatch, tmp_path, capsys):
    client = FakeClient([experiment('a', BASE), experiment('b', FRAGILE)])
    monkeypatch.setattr('phoenix_evidence.cli._client', lambda url: client)
    assert cli(['compare', 'a', 'b']) == 0
    out = tmp_path / 'r.json'
    assert cli(['compare', 'a', 'b', '--fail-on-regression', '--json', str(out)]) == 1
    assert json.loads(out.read_text())['regressions'] == ['task_error']
    assert '| task_error |' in capsys.readouterr().out


def test_identical_experiments_show_nothing():
    client = FakeClient([experiment('a', BASE), experiment('b', BASE)])
    result = compare_experiments(client, 'a', 'b')
    assert result.regressions() == [] and result.improvements() == []


def test_lower_is_better_metrics_score_missing_runs_as_worst():
    def scored(eid, values):
        runs = [{'id': f'{eid}{k}', 'dataset_example_id': str(k), 'repetition_number': 1, 'error': None}
                for k in range(len(values))]  # fmt: skip
        evals = [SimpleNamespace(experiment_run_id=f'{eid}{k}', name='toxicity', error=None if v is not None else 'x',
                                 result=None if v is None else {'score': v}) for k, v in enumerate(values)]  # fmt: skip
        return {'experiment_id': eid, 'task_runs': runs, 'evaluation_runs': evals}

    client = FakeClient([scored('a', [0.0] * 20), scored('b', [None] * 20)])
    result = compare_experiments(client, 'a', 'b', lower_is_better=['task_error', 'toxicity'])
    # every candidate score is missing; scoring it 0 would make it look as clean as the base
    assert result.by_metric['toxicity'].difference == 0  # worst seen is 0.0 here: nothing to compare
    client = FakeClient([scored('a', [0.0] * 19 + [1.0]), scored('b', [None] * 20)])
    result = compare_experiments(client, 'a', 'b', lower_is_better=['task_error', 'toxicity'])
    assert result.by_metric['toxicity'].difference > 0  # missing counts as the worst (1.0)


def annotations(n_agree, n_disagree, judge_identifier='judge-v1'):
    rows = []
    for k in range(n_agree + n_disagree):
        human = 'good' if k % 2 else 'bad'
        judge = human if k < n_agree else ('bad' if human == 'good' else 'good')
        rows.append({'span_id': f's{k}', 'name': 'q', 'annotator_kind': 'HUMAN', 'identifier': '',
                     'result': {'label': human}})  # fmt: skip
        rows.append({'span_id': f's{k}', 'name': 'q', 'annotator_kind': 'LLM', 'identifier': judge_identifier,
                     'result': {'label': judge}, 'updated_at': '2026-10-03'})  # fmt: skip
    return rows


def test_feedback_certificate_decides_and_lists_disagreements():
    result = feedback_certificate(FakeClient(annotations=annotations(190, 10)), 'p', 'q')
    assert result['verdict'] == 'TRUSTWORTHY' and len(result['disagreements']) == 10
    result = feedback_certificate(FakeClient(annotations=annotations(25, 5)), 'p', 'q')
    assert result['verdict'] == 'NOT_ENOUGH_EVIDENCE' and result['labels_to_settle']
    result = feedback_certificate(FakeClient(annotations=annotations(30, 30)), 'p', 'q')
    assert result['verdict'] == 'NOT_TRUSTWORTHY'


def test_pairs_need_both_kinds_on_a_span():
    rows = annotations(3, 0)
    rows = [r for r in rows if not (r['span_id'] == 's0' and r['annotator_kind'] == 'LLM')]
    assert len(pairs_from_span_annotations(rows, 'q')) == 2


def test_audit_warns_about_one_label_and_tiny_suites():
    assert 'one label only' in audit_labels(['pii'] * 150, 0.9)['warnings'][0]
    small = audit_labels(['a'] * 8 + ['b'] * 8, 0.7)
    assert small['min_correct_to_pass'] == 16
    assert any('perfect score' in w for w in small['warnings'])


def test_an_evaluator_in_one_experiment_only_is_reported():
    a = experiment('a', BASE)
    b = experiment('b', BASE)
    b['evaluation_runs'] = [SimpleNamespace(**{**vars(e), 'name': 'renamed'}) for e in b['evaluation_runs']]
    result = compare_experiments(FakeClient([a, b]), 'a', 'b')
    assert result.only_in == {'correct': 'base', 'renamed': 'candidate'}
    assert 'scored only in the base experiment' in result.markdown()


def judged_project(n=400, seed=0):
    """Spans with two judge runs (disagreeing on some) and a human truth for each."""
    import random

    rng = random.Random(seed)
    rows, truth = [], {}
    for k in range(n):
        span = f's{k}'
        human = 'good' if rng.random() < 0.7 else 'bad'
        judge = human if rng.random() < 0.85 else ('bad' if human == 'good' else 'good')
        second = judge if rng.random() > 0.1 else ('bad' if judge == 'good' else 'good')
        truth[span] = human
        for ident, label in (('run-1', judge), ('run-2', second)):
            rows.append({'span_id': span, 'name': 'q', 'annotator_kind': 'LLM', 'identifier': ident,
                         'result': {'label': label}, 'updated_at': ident})  # fmt: skip
    return rows, truth


class RecordingDatasets:
    def __init__(self):
        self.created = []

    def create_dataset(self, **kwargs):
        frame = kwargs['dataframe']
        # Phoenix refuses a span link column that is also an input column.
        assert kwargs['span_id_key'] not in kwargs['input_keys'], 'span link column overlaps an input column'
        self.created.append(frame)
        return SimpleNamespace(id=f'ds-{len(self.created)}')


def test_plan_then_correct_recovers_the_human_rate():
    pytest = __import__('pytest')
    pytest.importorskip('pandas')
    from phoenix_evidence.phoenix import corrected_rate_from_plan, plan_label_queue

    rows, truth = judged_project()
    client = FakeClient(annotations=rows)
    client.datasets = RecordingDatasets()
    plan = plan_label_queue(client, 'p', 'q', budget=80, seed=3)
    assert plan['dataset'] == 'ds-1' and len(client.datasets.created[0]) == len(plan['chosen'])
    assert plan['judge_unsure_spans'] > 0
    unsure = {s for s in plan['population'] if plan['inclusion'][s] > min(plan['inclusion'].values())}
    assert all(
        plan['inclusion'][s] >= max(plan['inclusion'][t] for t in plan['population'] if t not in unsure) for s in unsure
    )

    # Before any human labels: nothing to estimate, and it says what is left to label.
    out = corrected_rate_from_plan(client, plan, 'good')
    assert out['result'] is None and len(out['still_to_label']) == len(plan['chosen'])

    labelled = rows + [{'span_id': s, 'name': 'q', 'annotator_kind': 'HUMAN', 'result': {'label': truth[s]}}
                       for s in plan['chosen']]  # fmt: skip
    out = corrected_rate_from_plan(FakeClient(annotations=labelled), plan, 'good')
    true_rate = sum(v == 'good' for v in truth.values()) / len(truth)
    assert out['interval'][0] <= true_rate <= out['interval'][1]
    assert out['still_to_label'] == []


def test_human_labels_under_a_separate_name_pair_with_the_judge():
    rows = []
    for k in range(10):
        rows.append(
            {
                'span_id': f's{k}',
                'name': 'q',
                'annotator_kind': 'LLM',
                'identifier': 'judge',
                'result': {'label': 'good'},
            }
        )
        rows.append(
            {
                'span_id': f's{k}',
                'name': 'q_review',
                'annotator_kind': 'HUMAN',
                'result': {'label': 'good' if k < 8 else 'bad'},
            }
        )
    assert pairs_from_span_annotations(rows, 'q') == []  # no HUMAN under the judge's name
    pairs = pairs_from_span_annotations(rows, 'q', human_name='q_review')
    assert len(pairs) == 10 and sum(h == j for [(h, j)] in pairs) == 8
    result = feedback_certificate(FakeClient(annotations=rows), 'p', 'q', human_annotation='q_review')
    assert result['paired_spans'] == 10 and len(result['disagreements']) == 2


def test_one_judge_configuration_is_used_everywhere():
    rows = []
    for k in range(20):
        human = 'good' if k % 2 else 'bad'
        rows.append({'span_id': f's{k}', 'name': 'q', 'annotator_kind': 'HUMAN', 'result': {'label': human}})
        rows.append({'span_id': f's{k}', 'name': 'q', 'annotator_kind': 'LLM', 'identifier': 'strict',
                     'result': {'label': human}, 'updated_at': '1'})  # fmt: skip
        rows.append({'span_id': f's{k}', 'name': 'q', 'annotator_kind': 'LLM', 'identifier': 'lenient',
                     'result': {'label': 'good'}, 'updated_at': '2'})  # fmt: skip
    strict = feedback_certificate(FakeClient(annotations=rows), 'p', 'q', judge_identifier='strict')
    assert strict['disagreements'] == [] and strict['kappa'] == 1.0
    latest = feedback_certificate(FakeClient(annotations=rows), 'p', 'q')  # the lenient one is newer
    disagreeing = sum(1 for [(h, j)] in pairs_from_span_annotations(rows, 'q') if h != j)
    assert len(latest['disagreements']) == disagreeing == 10


def test_review_2_corrected_rate_refuses_what_would_bias_it():
    pytest = __import__('pytest')
    pytest.importorskip('pandas')
    from phoenix_evidence.phoenix import corrected_rate_from_plan

    spans = [f's{k}' for k in range(100)]
    plan = {'project': 'p', 'annotation': 'q', 'population': spans, 'chosen': spans,
            'inclusion': dict.fromkeys(spans, 1.0), 'judge': dict.fromkeys(spans, 'no')}  # fmt: skip
    half = [{'span_id': s, 'name': 'q', 'annotator_kind': 'HUMAN', 'result': {'label': 'yes'}} for s in spans[:50]]
    out = corrected_rate_from_plan(FakeClient(annotations=half), plan, 'yes')
    assert out['result'] is None and '50 chosen spans' in out['refused']  # not 0.5 [0.385, 0.615]

    # The judge's labels are frozen in the plan: losing an annotation later does not shrink the population.
    plan2 = {'project': 'p', 'annotation': 'q', 'population': ['a', 'b'], 'chosen': ['a', 'b'],
             'inclusion': {'a': 1.0, 'b': 1.0}, 'judge': {'a': 'yes', 'b': 'yes'}}  # fmt: skip
    rows = [{'span_id': 'a', 'name': 'q', 'annotator_kind': 'HUMAN', 'result': {'label': 'yes'}},
            {'span_id': 'b', 'name': 'q', 'annotator_kind': 'HUMAN', 'result': {'label': 'no'}}]  # fmt: skip
    out = corrected_rate_from_plan(FakeClient(annotations=rows), plan2, 'yes')
    assert out['spans'] == 2 and out['estimate'] == 0.5


def test_review_2_several_reviewers_are_counted_the_same_everywhere():
    rows = [
        {'span_id': 's', 'name': 'q', 'annotator_kind': 'LLM', 'identifier': 'j', 'result': {'label': 'yes'}},
        {'span_id': 's', 'name': 'q', 'annotator_kind': 'HUMAN', 'result': {'label': 'yes'}},
        {'span_id': 's', 'name': 'q', 'annotator_kind': 'HUMAN', 'result': {'label': 'no'}},
    ]
    result = feedback_certificate(FakeClient(annotations=rows), 'p', 'q')
    assert len(result['disagreements']) == 1  # the 'no' reviewer, matching accuracy 0.5


def test_review_2_latest_compares_instants_not_strings():
    from phoenix_evidence.phoenix import judge_labels

    rows = [
        {
            'span_id': 's',
            'name': 'q',
            'annotator_kind': 'LLM',
            'result': {'label': 'old'},
            'updated_at': '2026-01-01T10:00:00+02:00',
        },
        {
            'span_id': 's',
            'name': 'q',
            'annotator_kind': 'LLM',
            'result': {'label': 'new'},
            'updated_at': '2026-01-01T09:00:00+00:00',
        },
    ]
    assert judge_labels(rows, 'q')[0] == {'s': 'new'}


def test_compare_writes_the_github_job_summary(monkeypatch, tmp_path):
    client = FakeClient([experiment('a', BASE), experiment('b', FRAGILE)])
    monkeypatch.setattr('phoenix_evidence.cli._client', lambda url: client)
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    assert cli(['compare', 'a', 'b', '--fail-on-regression']) == 1
    text = summary.read_text()
    assert '| task_error |' in text and 'worse' in text


def test_compare_names_the_experiments_and_falls_back_to_ids():
    client = FakeClient([experiment('a', BASE), experiment('b', FRAGILE)])
    assert compare_experiments(client, 'a', 'b').markdown().startswith('**b** vs **a**')  # no get: ids
    names = {'a': {'name': 'baseline'}, 'b': {'name': 'fragile'}}
    client.experiments.get = lambda experiment_id: names[experiment_id]
    assert compare_experiments(client, 'a', 'b').markdown().startswith('**fragile (b)** vs **baseline (a)**')


def test_canary_reads_experiments_and_counts_crashes_as_flips(monkeypatch, tmp_path):
    flipped = {k: ('fail' if v == 'pass' else 'pass') if int(k) % 4 == 0 else v for k, v in BASE.items()}
    client = FakeClient([experiment('ref', BASE), experiment('same', BASE), experiment('crashy', FRAGILE),
                         *(experiment(f'drift{d}', flipped) for d in range(3))])  # fmt: skip
    monkeypatch.setattr('phoenix_evidence.cli._client', lambda url: client)
    args = ['canary', 'ref', 'same', '--evaluator', 'correct', '--allowed', '0.05', '--fail-on-drift']
    assert cli(args) == 0
    out = tmp_path / 'c.json'
    assert cli([*args[:3], 'crashy', *args[3:], '--json', str(out)]) == 0  # 10 crashes in 100: not yet
    assert json.loads(out.read_text())['looks'][1]['flips'] == 10
    assert cli([*args[:3], 'drift0', 'drift1', 'drift2', *args[3:]]) == 1  # 25% flips, three checks


def test_doctor_reads_splits_and_finds_leakage(monkeypatch):
    long = ' '.join(f'word{k}' for k in range(50))
    rows = [{'id': 'e1', 'input': {'q': long}, 'output': {'label': 'pass'}},
            {'id': 'e2', 'input': {'q': long + ' '}, 'output': {'label': 'pass'}},
            {'id': 'e3', 'input': {'q': 'something else entirely'}, 'output': {}}]  # fmt: skip
    in_split = {'train': {'e1', 'e3'}, 'test': {'e2'}}

    def get_dataset(dataset, splits=None):
        keep = in_split[splits[0]] if splits else {r['id'] for r in rows}
        return SimpleNamespace(examples=[r for r in rows if r['id'] in keep])

    client = SimpleNamespace(datasets=SimpleNamespace(get_dataset=get_dataset))
    monkeypatch.setattr('phoenix_evidence.cli._client', lambda url: client)
    assert cli(['doctor', 'ds', '--splits', 'train,test']) == 0
    assert cli(['doctor', 'ds', '--splits', 'train,test', '--strict']) == 1
    from phoenix_evidence.phoenix import doctor_dataset

    d = doctor_dataset(client, 'ds', splits=['train', 'test'])
    assert d.exact_copies == [['e1', 'e2']] and d.cross_split == [('e1', 'e2', 1.0)] and d.unlabelled == ['e3']


def test_plan_with_judge_probabilities_uses_them_for_doubt_and_value():
    pytest = __import__('pytest')
    pytest.importorskip('pandas')
    import random

    from phoenix_evidence.phoenix import corrected_rate_from_plan, plan_label_queue

    rng = random.Random(5)
    rows, truth = [], {}
    for k in range(400):
        p = rng.betavariate(0.5, 0.5)
        span = f's{k}'
        truth[span] = 'good' if rng.random() < p else 'bad'
        rows.append({'span_id': span, 'name': 'q', 'annotator_kind': 'LLM', 'identifier': 'j',
                     'result': {'label': 'good' if p > 0.5 else 'bad', 'score': p}, 'updated_at': '1'})  # fmt: skip
    client = FakeClient(annotations=rows)
    client.datasets = RecordingDatasets()
    plan = plan_label_queue(client, 'p', 'q', budget=100, seed=1, judge_probability=True)
    scores = {r['span_id']: r['result']['score'] for r in rows}
    assert plan['judge_probability'] == {s: scores[s] for s in plan['population']}
    unsure, sure = (
        max(plan['population'], key=lambda s: scores[s] * (1 - scores[s])),
        min(plan['population'], key=lambda s: scores[s] * (1 - scores[s])),
    )
    assert plan['inclusion'][unsure] > plan['inclusion'][sure]
    labelled = rows + [{'span_id': s, 'name': 'q', 'annotator_kind': 'HUMAN', 'result': {'label': truth[s]}}
                       for s in plan['chosen']]  # fmt: skip
    out = corrected_rate_from_plan(FakeClient(annotations=labelled), plan, 'good')
    assert out['judge_rate'] == pytest.approx(sum(plan['judge_probability'].values()) / 400)  # the value is p
    true_rate = sum(v == 'good' for v in truth.values()) / 400
    assert out['interval'][0] <= true_rate <= out['interval'][1]
    bad = [dict(rows[0], result={'label': 'good', 'score': 3.0})]
    with pytest.raises(ValueError):
        plan_label_queue(FakeClient(annotations=bad), 'p', 'q', budget=1, judge_probability=True, create_dataset=False)


def test_cli_sequential_compare_decides_the_regression(monkeypatch, tmp_path):
    # 10 crashes in 100 is shown by the one-shot test (p = 0.002) but not yet by the sequential one
    # (evidence 39.4 of 40 at alpha 0.05 split over two metrics): the price of being free to peek.
    client = FakeClient([experiment('a', BASE), experiment('b', FRAGILE)])
    monkeypatch.setattr('phoenix_evidence.cli._client', lambda url: client)
    assert cli(['compare', 'a', 'b', '--sequential', '--fail-on-regression']) == 0
    worse = {str(i): 'pass' if i < 84 else ('crash' if i < 99 else 'fail') for i in range(100)}  # 15 crashes
    client = FakeClient([experiment('a', BASE), experiment('b', worse)])
    monkeypatch.setattr('phoenix_evidence.cli._client', lambda url: client)
    out = tmp_path / 's.json'
    assert cli(['compare', 'a', 'b', '--sequential', '--fail-on-regression', '--json', str(out)]) == 1
    report = json.loads(out.read_text())['metrics']
    assert report['task_error']['decision'] == 'candidate worse' and report['task_error']['worse'] == 15
    assert report['correct']['decision'] is None  # crashes counted as the worst score: no win shown


def test_an_unreachable_server_is_one_line_not_a_traceback(monkeypatch, capsys):
    from phoenix_evidence.cli import main_exit

    class ConnectError(Exception):
        pass

    def unreachable(url):
        raise ConnectError('[Errno 61] Connection refused')

    monkeypatch.setattr('phoenix_evidence.cli._client', unreachable)
    monkeypatch.setattr('sys.argv', ['phoenix-evidence', 'compare', 'a', 'b'])
    with __import__('pytest').raises(SystemExit) as stop:
        main_exit()
    assert stop.value.code == 2 and 'cannot reach Phoenix' in capsys.readouterr().err


def test_sequential_reports_a_metric_only_one_side_scored(monkeypatch, capsys):
    # Review 4: such a metric was dropped silently and the Bonferroni divisor shrank.
    from phoenix_evidence.phoenix import sequential_compare_experiments

    a, b = experiment('a', BASE), experiment('b', BASE)
    b['evaluation_runs'] = b['evaluation_runs'] + [
        SimpleNamespace(experiment_run_id=r['id'], name='extra', error=None, result={'score': 1.0})
        for r in b['task_runs']
    ]
    report = sequential_compare_experiments(FakeClient([a, b]), 'a', 'b')
    assert report.only_in == {'extra': 'candidate'} and report.alpha_per_metric == 0.05 / 3
    monkeypatch.setattr('phoenix_evidence.cli._client', lambda url: FakeClient([a, b]))
    cli(['compare', 'a', 'b', '--sequential'])
    assert 'extra: scored only in the candidate; not tested' in capsys.readouterr().out


def test_a_batch_look_decides_on_the_current_evidence_only():
    # Review 4: replaying a batch in an arbitrary order adds looks that never happened.
    from phoenix_evidence._sequential import SequentialComparison

    pairs = [(0, 1)] * 12 + [(1, 0)] * 6  # a streak first, then losses
    streamed = SequentialComparison().extend(pairs)
    batch = SequentialComparison().look(pairs)
    assert streamed.decision == 'candidate better'  # the early streak crossed in the replay
    assert batch.decision is None  # 12 vs 6 as one look is not enough
    with __import__('pytest').raises(ValueError):
        SequentialComparison().add(float('nan'), 1.0)
