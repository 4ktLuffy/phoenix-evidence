"""What happens when a human and a judge annotate the same span under the same name? Against a live Phoenix.

    PHOENIX_BASE_URL=http://localhost:6006 uv run --extra phoenix python bench/human_and_judge_annotations.py

Four spans in a fresh project, each first scored 1.0 by an LLM judge (annotation "quality"), then
by a human:

- spans 1-2: the human gives 0.0 with no identifier, as the judge did (the default for both);
- spans 3-4: the judge's annotation carries an identifier ("judge-v1"); the human gives 0.0 with none.

It reads back what Phoenix stored, and the project's annotation summary for "quality" (the number
on the project page), and pairs judge and human labels with phoenix_evidence's
`pairs_from_span_annotations`. Writes results/human_and_judge_annotations.json.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from phoenix.client import Client

from phoenix_evidence.phoenix import pairs_from_span_annotations

OUT = Path(__file__).resolve().parent.parent / 'results'
SUMMARY_QUERY = """
query ($id: ID!, $name: String!) {
  node(id: $id) { ... on Project { spanAnnotationSummary(annotationName: $name) { meanScore count labelFractions { label fraction } } } }
}
"""


def main() -> None:
    base_url = os.environ.get('PHOENIX_BASE_URL', 'http://localhost:6006')
    client = Client(base_url=base_url)
    project = f'human-vs-judge-{uuid.uuid4().hex[:8]}'
    now = datetime.now(timezone.utc)
    trace_id = uuid.uuid4().hex
    span_ids = [uuid.uuid4().hex[:16] for _ in range(4)]
    spans = [
        {
            'name': f'answer-{i}',
            'context': {'trace_id': trace_id, 'span_id': sid},
            'span_kind': 'LLM',
            'start_time': (now + timedelta(seconds=i)).isoformat(),
            'end_time': (now + timedelta(seconds=i + 1)).isoformat(),
            'status_code': 'OK',
            'attributes': {'input.value': f'question {i}', 'output.value': f'answer {i}'},
        }
        for i, sid in enumerate(span_ids)
    ]
    client.spans.log_spans(project_identifier=project, spans=spans)
    time.sleep(3)  # spans are inserted asynchronously
    for i, sid in enumerate(span_ids):
        identifier = None if i < 2 else 'judge-v1'
        client.spans.add_span_annotation(
            span_id=sid, annotation_name='quality', annotator_kind='LLM', label='good', score=1.0,
            identifier=identifier, sync=True,
        )  # fmt: skip
    for sid in span_ids:
        client.spans.add_span_annotation(
            span_id=sid, annotation_name='quality', annotator_kind='HUMAN', label='bad', score=0.0, sync=True
        )
    time.sleep(2)
    stored = client.spans.get_span_annotations(span_ids=span_ids, project_identifier=project)
    rows = [
        {'span': a['span_id'], 'kind': a['annotator_kind'], 'identifier': a.get('identifier'), 'label': a['result']['label'],
         'score': a['result']['score']}
        for a in stored
    ]  # fmt: skip
    project_id = next(p['id'] for p in client.projects.list() if p['name'] == project)
    summary = httpx.post(
        f'{base_url}/graphql', json={'query': SUMMARY_QUERY, 'variables': {'id': project_id, 'name': 'quality'}}
    ).json()
    pairs = pairs_from_span_annotations(stored, 'quality')
    result = {
        'stored_annotations': sorted(rows, key=lambda r: (span_ids.index(r['span']), r['kind'])),
        'spans_1_2_judge_annotation_kept': sum(1 for r in rows if r['kind'] == 'LLM' and span_ids.index(r['span']) < 2),
        'project_summary_for_quality': summary.get('data', summary),
        'judge_vs_human_pairs': pairs,
    }
    print(json.dumps(result, indent=1))
    (OUT / 'human_and_judge_annotations.json').write_text(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
