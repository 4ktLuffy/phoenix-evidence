"""In-process reproductions of the resume findings (FINDINGS: resume). Run from a Phoenix checkout:

    PYTHONPATH=. .venv/bin/python -m pytest -p tests.conftest -p tests.unit.conftest -c pyproject.toml \
        -s <this file> -p no:randomly

Prints what the client and server do; the assertions live in upstream/07's tests.
"""

import httpx
import phoenix.client.resources.experiments as exps
import pytest
from phoenix.client import AsyncClient


@pytest.fixture(autouse=True)
def _no_otlp(monkeypatch):
    real = exps._get_tracer_bundle
    monkeypatch.setattr(exps, '_get_tracer_bundle', lambda *a, **k: real(None, None, None))


async def test_stale_eval_after_resume(httpx_client: httpx.AsyncClient) -> None:
    client = AsyncClient(http_client=httpx_client)
    ds = await client.datasets.create_dataset(
        name='d1',
        inputs=[{'q': 'a'}, {'q': 'b'}],
        outputs=[{'a': 'A'}, {'a': 'B'}],
    )
    fail = {'on': True}

    def task(input):
        if fail['on'] and input['q'] == 'b':
            raise RuntimeError('boom')
        return input['q'].upper()

    calls = []

    def exact(output, expected):
        calls.append(output)
        return 1.0 if output == expected['a'] else 0.0

    ran = await client.experiments.run_experiment(
        dataset=ds, task=task, evaluators={'exact': exact}, retries=0, print_summary=False
    )
    print('\nevaluator called on outputs:', calls)
    print('task_runs:', [(r['output'], r.get('error')) for r in ran['task_runs']])
    eid = ran['experiment_id']
    exp = await client.experiments.get(experiment_id=eid)
    print('successful_run_count:', exp['successful_run_count'], 'failed_run_count:', exp.get('failed_run_count'))

    fail['on'] = False
    calls.clear()
    await client.experiments.resume_experiment(
        experiment_id=eid, task=task, evaluators={'exact': exact}, print_summary=False
    )
    print('evaluator calls during resume:', calls)

    r = await httpx_client.get(f'v1/experiments/{eid}/json')
    for row in r.json():
        print(
            'AFTER RESUME:',
            row['input'],
            'output=',
            row['output'],
            'error=',
            row.get('error'),
            'annotations=',
            [(a['name'], a['score']) for a in row['annotations']],
        )


async def test_resume_eval_counts(httpx_client: httpx.AsyncClient) -> None:
    client = AsyncClient(http_client=httpx_client)
    ds = await client.datasets.create_dataset(
        name='d2', inputs=[{'q': 'a'}, {'q': 'b'}], outputs=[{'a': 'A'}, {'a': 'B'}]
    )
    flaky = {'on': True}

    def task(input):
        return input['q'].upper()

    def a(output, expected):
        return 1.0

    def b(output, expected):
        if flaky['on'] and output == 'B':
            raise RuntimeError('judge timeout')
        return 1.0

    ran = await client.experiments.run_experiment(
        dataset=ds, task=task, evaluators={'a': a, 'b': b}, retries=0, print_summary=False
    )
    eid = ran['experiment_id']
    flaky['on'] = False
    print('\n--- resume_evaluation (1 missing eval, then succeeds) ---')
    await client.experiments.resume_evaluation(experiment_id=eid, evaluators={'a': a, 'b': b}, retries=0)

    multi_calls = []

    def m(output, expected):
        multi_calls.append(output)
        return [{'name': 'm_precision', 'score': 1.0}, {'name': 'm_recall', 'score': 0.5}]

    await client.experiments.evaluate_experiment(experiment=ran, evaluators={'m': m}, print_summary=False)
    for i in range(2):
        multi_calls.clear()
        await client.experiments.resume_evaluation(experiment_id=eid, evaluators={'m': m}, print_summary=False)
        print(f'resume #{i + 1}: multi-output evaluator re-invoked on {len(multi_calls)} runs')
