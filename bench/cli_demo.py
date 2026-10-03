"""The `phoenix-evidence` commands against a live Phoenix, next to what Phoenix itself shows. No model calls.

    PHOENIX_BASE_URL=http://localhost:6006 uv run --extra phoenix python bench/cli_demo.py

Builds, in a running Phoenix, the three situations the commands are for, with deterministic tasks
so the truth is known:

1. compare: a 120-question dataset and three experiments scored by an exact-match evaluator:
   `baseline` (right on 96), `tweak` (right on 4 more: a real but small gain), and `fragile`
   (right on the baseline's 96 plus 6 more, but it raises on 12 of the questions the baseline got
   wrong, so Phoenix averages it over the 108 runs that finished);
2. certify-feedback: a project of 60 traced answers, each labelled by an LLM judge (under its own
   identifier) and by a human, agreeing on 52;
3. audit: the refusal benchmark dataset written by bench/write_back_demo.py, if present.

Prints Phoenix's own experiment means (the numbers on its compare page) and each command's output.
Writes results/cli_demo.txt.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from phoenix.client import Client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from phoenix_evidence.cli import main as cli  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / 'results'
BASE_URL = os.environ.get('PHOENIX_BASE_URL', 'http://localhost:6006')
TAG = uuid.uuid4().hex[:6]


def rank(i: int) -> float:
    """A fixed pseudo-random position in [0, 1) per question, so 'hard' questions are the same in every run."""
    return int(hashlib.sha256(str(i).encode()).hexdigest()[:8], 16) / 2**32


def answer(i: int) -> int:
    return i * 7 + 3


def task_for(name: str):  # noqa: ANN201
    def task(input):  # noqa: A002, ANN001, ANN202
        i = input['i']
        r = rank(i)
        if name == 'baseline':
            right = r < 0.8
        elif name == 'tweak':
            right = r < 0.8 + 4 / 120
        else:  # fragile: crashes on part of what the baseline gets wrong, gains a little elsewhere
            if 0.8 <= r < 0.9:
                raise RuntimeError('timeout on a hard question')
            right = r < 0.8 or r >= 0.95
        return {'answer': answer(i) if right else -1}

    return task


def exact_match(output, expected) -> float:  # noqa: ANN001
    return float(output['answer'] == expected['answer'])


GQL = """query ($id: ID!) { node(id: $id) { ... on Experiment { name annotationSummaries { annotationName meanScore count } } } }"""


def phoenix_mean(experiment_id: str) -> str:
    data = httpx.post(f'{BASE_URL}/graphql', json={'query': GQL, 'variables': {'id': experiment_id}}).json()
    node = data['data']['node']
    s = next(a for a in node['annotationSummaries'] if a['annotationName'] == 'exact_match')
    return f'{node["name"]}: Phoenix shows exact_match mean {s["meanScore"]:.3f} over {s["count"]} evaluations'


def run(args: list[str]) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli(['--url', BASE_URL, *args])
    return f'$ phoenix-evidence {" ".join(args)}\n{buf.getvalue()}(exit {code})\n'


def main() -> None:
    client = Client(base_url=BASE_URL)
    lines: list[str] = []

    dataset = client.datasets.create_dataset(
        name=f'arithmetic-{TAG}',
        inputs=[{'i': i} for i in range(120)],
        outputs=[{'answer': answer(i)} for i in range(120)],
    )
    ids = {}
    for name in ('baseline', 'tweak', 'fragile'):
        ran = client.experiments.run_experiment(
            dataset=dataset, task=task_for(name), evaluators=[exact_match], experiment_name=name, print_summary=False
        )
        ids[name] = ran['experiment_id']
    lines += ['## 1. compare', '', *(phoenix_mean(ids[n]) for n in ids), '']
    lines.append(run(['compare', ids['baseline'], ids['tweak']]))
    lines.append(run(['compare', ids['baseline'], ids['fragile'], '--fail-on-regression']))

    project = f'support-bot-{TAG}'
    now = datetime.now(timezone.utc)
    trace = uuid.uuid4().hex
    span_ids = [uuid.uuid4().hex[:16] for _ in range(60)]
    client.spans.log_spans(
        project_identifier=project,
        spans=[
            {'name': 'reply', 'context': {'trace_id': trace, 'span_id': s}, 'span_kind': 'LLM',
             'start_time': (now + timedelta(seconds=k)).isoformat(),
             'end_time': (now + timedelta(seconds=k + 1)).isoformat(), 'status_code': 'OK', 'attributes': {}}
            for k, s in enumerate(span_ids)
        ],
    )  # fmt: skip
    time.sleep(3)
    for k, s in enumerate(span_ids):
        human = 'helpful' if k % 3 else 'unhelpful'
        judge = human if k < 52 else ('unhelpful' if human == 'helpful' else 'helpful')
        client.spans.add_span_annotation(
            span_id=s,
            annotation_name='helpfulness',
            annotator_kind='LLM',
            label=judge,
            identifier='judge-v1',
            sync=True,
        )
        client.spans.add_span_annotation(
            span_id=s, annotation_name='helpfulness', annotator_kind='HUMAN', label=human, sync=True
        )
    time.sleep(2)
    lines += ['## 2. certify-feedback', '', run(['certify-feedback', project, 'helpfulness'])]

    lines += ['## 3. audit', '']
    try:
        lines.append(run(['audit', 'refusal benchmark (phoenix-evidence)', '--threshold', '0.7']))
    except Exception as e:  # the dataset exists only after bench/write_back_demo.py
        lines.append(f'(skipped: {e!r})')
    text = '\n'.join(lines)
    print(text)
    (OUT / 'cli_demo.txt').write_text(text + '\n')


if __name__ == '__main__':
    main()
