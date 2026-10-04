"""Two identical experiments, each run's trace with two LLM spans, for the compare-page screenshots.

    uv run --extra phoenix python bench/pr_identical_experiments.py http://localhost:6006

Creates a 12-example dataset and two experiments with exactly the same runs: the same output and,
in each run's trace, the same two LLM spans (gpt-4o-mini, 100 prompt + 20 completion tokens each).
Nothing differs, so the compare page should show no run improved or regressed on any metric.
Prints the compare-page URL. Used for the before/after images of the compare-page fix.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from phoenix.client import Client


def main(base_url: str) -> None:
    client = Client(base_url=base_url)
    http = httpx.Client(base_url=base_url, timeout=30)
    name = f'identical-{uuid.uuid4().hex[:6]}'
    dataset = client.datasets.create_dataset(
        name=name, inputs=[{'q': f'question {i}'} for i in range(12)], outputs=[{'a': f'answer {i}'} for i in range(12)]
    )
    examples = list(client.datasets.get_dataset(dataset=dataset.id).examples)
    ids = []
    for label in ('identical A', 'identical B'):
        exp = http.post(f'v1/datasets/{dataset.id}/experiments', json={'name': label, 'repetitions': 1}).json()['data']
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        spans = []
        for k, example in enumerate(examples):
            trace_id = uuid.uuid4().hex
            t0 = start + timedelta(seconds=k)
            for j in range(2):  # two LLM calls in one run
                spans.append({
                    'name': f'llm_call_{j}', 'span_kind': 'LLM', 'status_code': 'OK',
                    'context': {'trace_id': trace_id, 'span_id': uuid.uuid4().hex[:16]},
                    'start_time': (t0 + timedelta(milliseconds=100 * j)).isoformat(),
                    'end_time': (t0 + timedelta(milliseconds=100 * j + 90)).isoformat(),
                    'attributes': {'llm.model_name': 'gpt-4o-mini', 'llm.provider': 'openai', 'llm.system': 'openai',
                                   'llm.token_count.prompt': 100, 'llm.token_count.completion': 20,
                                   'llm.token_count.total': 120},
                })  # fmt: skip
            http.post(f'v1/experiments/{exp["id"]}/runs', json={
                'dataset_example_id': example['id'], 'output': f'answer {k}', 'repetition_number': 1,
                'start_time': t0.isoformat(), 'end_time': (t0 + timedelta(milliseconds=200)).isoformat(),
                'trace_id': trace_id,
            }).raise_for_status()  # fmt: skip
        client.spans.log_spans(project_identifier=exp['project_name'], spans=spans)
        ids.append(exp['id'])
    print(f'{base_url}/datasets/{dataset.id}/compare?experimentId={ids[0]}&experimentId={ids[1]}&view=metrics')


if __name__ == '__main__':
    main(sys.argv[1])
