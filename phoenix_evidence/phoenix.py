"""Read human labels from Phoenix and write certificates back into it.

Two places in Phoenix hold human labels a judge can be checked against:

- span annotations with `annotator_kind == 'HUMAN'` (feedback on production traces), paired with
  the judge's LLM annotation of the same name on the same span: `pairs_from_span_annotations`;
- a dataset whose examples carry the human label in their output: `cases_from_dataset`.

`write_certificate` stores a certificate as a Phoenix experiment on the labelled dataset: the
experiment's metadata carries the verdict and every check, each run carries the judge's label for
one repetition, and each run is annotated with the human label (HUMAN), whether the judge agreed
(CODE), and how the controls built from that example came out (CODE). It opens in Phoenix's own
experiment views, next to the runs it summarises.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from phoenix_evidence._agreement import Pair
from phoenix_evidence._certify import Case, Certificate


def pairs_from_span_annotations(annotations: Iterable[Mapping[str, Any]], name: str) -> list[list[Pair]]:
    """Group HUMAN and LLM annotations named `name` by span: one list of (human, judge) pairs per span.

    `annotations` is what `client.spans.get_span_annotations(...)` returns. A span counts only when
    it has both kinds; several humans on one span give several pairs, which are resampled together.
    The latest LLM label per span is used, as Phoenix's own summaries do.
    """
    human: dict[str, list[str]] = defaultdict(list)
    judge: dict[str, tuple[str, str]] = {}
    for a in annotations:
        if a.get('name') != name:
            continue
        label = (a.get('result') or {}).get('label')
        if label is None:
            continue
        span = a['span_id']
        if a.get('annotator_kind') == 'HUMAN':
            human[span].append(str(label))
        elif a.get('annotator_kind') == 'LLM':
            stamp = str(a.get('updated_at') or a.get('created_at') or '')
            if span not in judge or stamp >= judge[span][0]:
                judge[span] = (stamp, str(label))
    return [[(h, judge[span][1]) for h in labels] for span, labels in sorted(human.items()) if span in judge]


def cases_from_dataset(
    dataset: Any, label_key: str = 'label', input_map: Mapping[str, str] | None = None
) -> list[Case]:
    """Cases from a Phoenix dataset whose example outputs hold the human label under `label_key`.

    `input_map` renames example input keys to the evaluator's input names, e.g. {'question': 'input'}.
    """
    cases = []
    for example in dataset.examples:
        label = (example.get('output') or {}).get(label_key)
        if label is None:
            continue
        raw = example.get('input') or {}
        payload = {(input_map or {}).get(k, k): v for k, v in raw.items()}
        cases.append(Case(str(example['id']), payload, str(label)))
    return cases


def write_certificate(
    client: Any,
    certificate: Certificate,
    cases: Sequence[Case],
    *,
    dataset_name: str,
    experiment_name: str | None = None,
) -> dict[str, str]:
    """Upload the labelled cases as a dataset and the certificate as an experiment on it.

    Returns the dataset id, experiment id and the experiment's URL in Phoenix.
    """
    dataset = client.datasets.create_dataset(
        name=dataset_name,
        inputs=[dict(c.input) for c in cases],
        outputs=[{'label': c.human_label} for c in cases],
        metadata=[{'case_id': c.id} for c in cases],
        dataset_description='Human-labelled cases a judge was certified on (phoenix-evidence).',
    )
    originals = [r for r in certificate.records if r['kind'] == 'original']
    repetitions = max((len(r['judge']) for r in originals), default=1)
    summary = certificate.summary()
    experiment = client.experiments.create(
        dataset_id=dataset.id,
        experiment_name=experiment_name or f'certify {certificate.judge_name}',
        experiment_description=str(certificate).splitlines()[0],
        experiment_metadata={'phoenix_evidence_certificate': summary},
        repetitions=repetitions,
    )
    experiment_id = experiment['id'] if isinstance(experiment, Mapping) else experiment.id
    example_ids = {c.id: ex['id'] for c, ex in zip(cases, dataset.examples, strict=True)}
    controls_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in certificate.records:
        if r['kind'] != 'original':
            controls_by_case[r['case']].append(r)
    now = datetime.now(timezone.utc)
    for record in originals:
        for rep, label in enumerate(record['judge'], start=1):
            run = client.experiments.log_run(
                experiment_id=experiment_id,
                dataset_example_id=example_ids[record['case']],
                output={'label': label},
                start_time=now,
                end_time=now,
                repetition_number=rep,
                error=None if label is not None else 'judge call failed',
            )
            client.experiments.log_evaluation(
                experiment_run_id=run['id'], name='human_label', annotator_kind='HUMAN', label=record['human']
            )
            if label is not None:
                agree = label == record['human']
                client.experiments.log_evaluation(
                    experiment_run_id=run['id'], name='agrees_with_human', label=str(agree).lower(), score=float(agree)
                )
            if rep == 1:
                for control in controls_by_case.get(record['case'], []):
                    ok = control['judge'] == control['expected']
                    client.experiments.log_evaluation(
                        experiment_run_id=run['id'],
                        name=f'control:{control["kind"]}',
                        label='held' if ok else 'violated',
                        score=float(ok),
                        explanation=f'expected {control["expected"]!r}, judge said {control["judge"]!r}',
                    )
    return {
        'dataset_id': dataset.id,
        'experiment_id': experiment_id,
        'url': client.experiments.get_experiment_url(dataset.id, experiment_id),
    }
