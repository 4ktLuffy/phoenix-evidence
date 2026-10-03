"""Do the commands hold up at production size against a live Phoenix? No model calls.

    PHOENIX_BASE_URL=http://localhost:6006 uv run --extra phoenix python bench/scale_test.py

1. Two experiments on a 3,000-example dataset, 2 repetitions each (12,000 runs, two evaluators).
   The candidate is right on 1.5 points more of the examples; `compare` must find it (the truth
   is known), and is timed.
2. A project of 5,000 spans, each labelled by a judge (twice, under two identifiers, disagreeing
   on 6% of spans) and by a human, agreeing on 91%. `certify-feedback`, `plan-labels` and
   `corrected-rate` are timed, and the corrected rate is checked against the true human rate.

Writes results/scale_test.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phoenix.client import Client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from phoenix_evidence.phoenix import (  # noqa: E402
    compare_experiments,
    corrected_rate_from_plan,
    feedback_certificate,
    plan_label_queue,
)

OUT = Path(__file__).resolve().parent.parent / 'results'
BASE_URL = os.environ.get('PHOENIX_BASE_URL', 'http://localhost:6006')
N_EXAMPLES, N_SPANS = 3000, 5000


def rank(i: int) -> float:
    return int(hashlib.sha256(str(i).encode()).hexdigest()[:8], 16) / 2**32


def main() -> None:
    client = Client(base_url=BASE_URL)
    tag = uuid.uuid4().hex[:6]
    result: dict = {}

    dataset = client.datasets.create_dataset(
        name=f'scale-{tag}', inputs=[{'i': i} for i in range(N_EXAMPLES)], outputs=[{'i': i} for i in range(N_EXAMPLES)]
    )
    ids = {}
    for name, cut in (('base', 0.80), ('candidate', 0.815)):

        def task(input, cut=cut):  # noqa: A002, ANN001, ANN202
            return {'right': rank(input['i']) < cut}

        def correct(output) -> float:  # noqa: ANN001
            return float(output['right'])

        def short(output) -> float:  # noqa: ANN001
            return 1.0

        started = time.time()
        ran = client.experiments.run_experiment(
            dataset=dataset,
            task=task,
            evaluators=[correct, short],
            experiment_name=name,
            repetitions=2,
            print_summary=False,
        )
        ids[name] = ran['experiment_id']
        result[f'run_{name}_seconds'] = round(time.time() - started, 1)
    started = time.time()
    comparison = compare_experiments(client, ids['base'], ids['candidate'])
    result['compare_seconds'] = round(time.time() - started, 1)
    result['compare_rows'] = comparison.rows()
    result['compare_improvements'] = comparison.improvements()

    project = f'scale-bot-{tag}'
    rng = random.Random(0)
    now = datetime.now(timezone.utc)
    span_ids = [uuid.uuid4().hex[:16] for _ in range(N_SPANS)]
    for start in range(0, N_SPANS, 1000):
        trace = uuid.uuid4().hex
        client.spans.log_spans(
            project_identifier=project,
            spans=[
                {'name': 'reply', 'context': {'trace_id': trace, 'span_id': s}, 'span_kind': 'LLM',
                 'start_time': (now + timedelta(milliseconds=k)).isoformat(),
                 'end_time': (now + timedelta(milliseconds=k + 1)).isoformat(), 'status_code': 'OK', 'attributes': {}}
                for k, s in enumerate(span_ids[start : start + 1000], start=start)
            ],
        )  # fmt: skip
    time.sleep(5)
    human_pass = 0
    rows = []
    for s in span_ids:
        human = 'helpful' if rng.random() < 0.74 else 'unhelpful'
        human_pass += human == 'helpful'
        judge = human if rng.random() < 0.91 else ('unhelpful' if human == 'helpful' else 'helpful')
        second = judge if rng.random() > 0.06 else ('unhelpful' if judge == 'helpful' else 'helpful')
        rows.append((s, human, judge, second))
    started = time.time()
    batch = []
    for s, _human, judge, second in rows:
        batch.append(
            {
                'span_id': s,
                'name': 'helpfulness',
                'annotator_kind': 'LLM',
                'identifier': 'judge-run-1',
                'result': {'label': judge},
            }
        )
        batch.append(
            {
                'span_id': s,
                'name': 'helpfulness',
                'annotator_kind': 'LLM',
                'identifier': 'judge-run-2',
                'result': {'label': second},
            }
        )
    for start in range(0, len(batch), 1000):
        client.spans.log_span_annotations(span_annotations=batch[start : start + 1000], sync=True)
    result['log_judge_annotations_seconds'] = round(time.time() - started, 1)
    truth = human_pass / N_SPANS
    result['true_human_pass_rate'] = truth

    started = time.time()
    plan = plan_label_queue(client, project, 'helpfulness', budget=150, seed=1, create_dataset=True)
    result['plan_seconds'] = round(time.time() - started, 1)
    result['plan_chosen'] = len(plan['chosen'])
    result['plan_unsure_spans'] = plan['judge_unsure_spans']
    human_rows = [{'span_id': s, 'name': 'helpfulness', 'annotator_kind': 'HUMAN', 'result': {'label': h}}
                  for s, h, _, _ in rows if s in set(plan['chosen'])]  # fmt: skip
    client.spans.log_span_annotations(span_annotations=human_rows, sync=True)
    time.sleep(2)
    started = time.time()
    corrected = corrected_rate_from_plan(client, plan, 'helpful')
    result['corrected_seconds'] = round(time.time() - started, 1)
    result['corrected'] = {
        k: corrected[k] for k in ('estimate', 'interval', 'judge_rate', 'human_only', 'labelled', 'spans')
    }
    result['corrected_covers_truth'] = corrected['interval'][0] <= truth <= corrected['interval'][1]

    started = time.time()
    cert = feedback_certificate(client, project, 'helpfulness')
    result['certify_feedback_seconds'] = round(time.time() - started, 1)
    result['certify_feedback'] = {k: cert[k] for k in ('verdict', 'paired_spans', 'kappa', 'kappa_interval')}
    print(json.dumps(result, indent=1, default=str))
    (OUT / 'scale_test.json').write_text(json.dumps(result, indent=1, default=str))


if __name__ == '__main__':
    main()
