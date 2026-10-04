"""End to end on a live Phoenix: a traced app, Phoenix's own evaluator as the online judge, and the tool on top.

    PHOENIX_BASE_URL=http://localhost:6006 uv run --extra phoenix python bench/e2e_support_bot.py traffic
    PHOENIX_BASE_URL=http://localhost:6006 uv run --extra phoenix python bench/e2e_support_bot.py judge

`traffic`: one Codex call writes 40 replies from a support assistant for a fictional note-taking
app ("Quill Notes"), some concise and some padded, and each becomes a traced LLM span (input and
output attributes) in the project `quill-support`.

`judge`: Phoenix's `ConcisenessEvaluator`, unchanged, judges every span twice on Codex with no
reasoning, logged as LLM annotations under two identifiers (as repeated online-eval runs write
them), and once with low reasoning under a third, for the judge-switch comparison.

Human labels are then entered in Phoenix's annotation UI on the spans `plan-labels` chooses, and
`certify-feedback`, `corrected-rate` and `switch_impact` run on what Phoenix stores. Judgments
are cached in results/judgments/e2e_*.jsonl. Writes results/e2e_traffic.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import CachedJudge  # noqa: E402
from phoenix.client import Client  # noqa: E402
from phoenix.evals import LLM  # noqa: E402
from phoenix.evals.metrics.conciseness import ConcisenessEvaluator  # noqa: E402

import phoenix_evidence.codex  # noqa: E402,F401

OUT = Path(__file__).resolve().parent.parent / 'results'
BASE_URL = os.environ.get('PHOENIX_BASE_URL', 'http://localhost:6006')
PROJECT = 'quill-support'
PROMPT = """Write 40 realistic customer-support exchanges for "Quill Notes", a fictional note-taking app.
Each has a short customer question (sync, export, sharing, billing, offline mode, tags, search,
account deletion, attachments, keyboard shortcuts...) and the support assistant's reply.
Make about half the replies concise and direct, and the rest padded in realistic ways: greetings
and sign-offs, apologies, restating the question, hedging, unrequested tips, or saying the same
thing twice. Vary length and tone. Do not label which is which.
Return JSON: {"exchanges": [{"question": "...", "reply": "..."}, ...]} with exactly 40 items."""
SCHEMA = {
    'type': 'object',
    'properties': {
        'exchanges': {
            'type': 'array',
            'items': {'type': 'object', 'properties': {'question': {'type': 'string'}, 'reply': {'type': 'string'}}},
        }
    },
}


def traffic() -> None:
    llm = LLM(provider='codex', model='gpt-5.6-luna', effort='low')
    data = llm.generate_object(prompt=PROMPT, schema=SCHEMA)
    exchanges = data['exchanges']
    client = Client(base_url=BASE_URL)
    now = datetime.now(timezone.utc)
    spans = []
    for k, ex in enumerate(exchanges):
        spans.append({
            'name': 'support_reply', 'span_kind': 'LLM', 'status_code': 'OK',
            'context': {'trace_id': uuid.uuid4().hex, 'span_id': uuid.uuid4().hex[:16]},
            'start_time': (now + timedelta(seconds=k)).isoformat(), 'end_time': (now + timedelta(seconds=k, milliseconds=900)).isoformat(),
            'attributes': {'input.value': ex['question'], 'output.value': ex['reply'], 'llm.model_name': 'quill-support-bot'},
        })  # fmt: skip
    client.spans.log_spans(project_identifier=PROJECT, spans=spans)
    record = [{'span_id': s['context']['span_id'], **ex} for s, ex in zip(spans, exchanges, strict=True)]
    (OUT / 'e2e_traffic.json').write_text(
        json.dumps({'generator': 'codex:gpt-5.6-luna@low', 'exchanges': record}, indent=1)
    )
    print(f'{len(record)} traced replies in project {PROJECT!r}')


async def judge() -> None:
    record = json.loads((OUT / 'e2e_traffic.json').read_text())['exchanges']
    client = Client(base_url=BASE_URL)
    configs = [
        ('judge-none-run-1', 'none', 'e2e_none'),
        ('judge-none-run-2', 'none', 'e2e_none'),
        ('judge-low', 'low', 'e2e_low'),
    ]
    judges = {
        cache: CachedJudge(
            cache,
            ConcisenessEvaluator(llm=LLM(provider='codex', model='gpt-5.6-luna', effort=effort)),
            model=f'codex:gpt-5.6-luna@{effort}',
        )
        for _, effort, cache in configs
    }
    semaphore = asyncio.Semaphore(8)

    async def ask(cache: str, ex: dict) -> str | None:
        async with semaphore:
            try:
                return await judges[cache]({'input': ex['question'], 'output': ex['reply']})
            except Exception:
                return None

    rows = []
    for identifier, _, cache in configs:
        labels = await asyncio.gather(*(ask(cache, ex) for ex in record))
        for ex, label in zip(record, labels, strict=True):
            if label is not None:
                rows.append({'span_id': ex['span_id'], 'name': 'conciseness', 'annotator_kind': 'LLM',
                             'identifier': identifier, 'result': {'label': label, 'score': float(label == 'concise')}})  # fmt: skip
        print(f'{identifier}: {sum(1 for x in labels if x)} of {len(record)} judged')
    client.spans.log_span_annotations(span_annotations=rows, sync=True)
    print(f'{len(rows)} judge annotations logged; {sum(j.new_calls for j in judges.values())} new calls')


if __name__ == '__main__':
    started = time.time()
    if sys.argv[1:] == ['traffic']:
        traffic()
    elif sys.argv[1:] == ['judge']:
        asyncio.run(judge())
    else:
        raise SystemExit('usage: e2e_support_bot.py traffic|judge')
    print(f'{time.time() - started:.0f}s')
