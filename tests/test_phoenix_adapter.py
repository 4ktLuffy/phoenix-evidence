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
