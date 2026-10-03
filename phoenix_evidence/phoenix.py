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

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from phoenix_evidence._agreement import Pair
from phoenix_evidence._certify import Case, Certificate
from phoenix_evidence._compare import Comparison, Direction, compare, holm
from phoenix_evidence._gate import constant_judge, min_successes_to_pass
from phoenix_evidence._power import examples_to_pass, pass_probability


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


# --- Experiments ----------------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)


def experiment_scores(client: Any, experiment_id: str) -> dict[str, dict[str, list[float | None]]]:
    """Every evaluator's scores in a Phoenix experiment: name -> dataset example -> one per repetition.

    A run that errored, or whose evaluation errored or is missing, gives None for that evaluator,
    so a version cannot look better by failing on the hard examples. Evaluators that only ever
    record a label (no score) are left out; one that only ever errored is kept, with every run
    missing. `task_error` (1 when the task itself errored) is added.
    """
    ran = client.experiments.get_experiment(experiment_id=experiment_id)
    runs = _get(ran, 'task_runs') or []
    evals = _get(ran, 'evaluation_runs') or []
    by_run: dict[str, dict[str, float | None]] = defaultdict(dict)
    names: set[str] = set()
    for ev in evals:
        result = _get(ev, 'result') or {}
        score = _get(result, 'score')
        name = _get(ev, 'name')
        if score is not None or _get(ev, 'error'):
            # An evaluator that only ever errored still counts: every run is then missing a score.
            names.add(name)
        by_run[_get(ev, 'experiment_run_id')][name] = None if _get(ev, 'error') or score is None else float(score)
    out: dict[str, dict[str, list[float | None]]] = defaultdict(lambda: defaultdict(list))
    for run in sorted(runs, key=lambda r: (_get(r, 'dataset_example_id'), _get(r, 'repetition_number') or 1)):
        example = str(_get(run, 'dataset_example_id'))
        errored = bool(_get(run, 'error'))
        out['task_error'][example].append(1.0 if errored else 0.0)
        for name in names:
            out[name][example].append(None if errored else by_run.get(_get(run, 'id'), {}).get(name))
    return {name: dict(v) for name, v in out.items()}


@dataclass
class ExperimentComparison:
    base: str
    candidate: str
    by_metric: dict[str, Comparison]
    survives_holm: dict[str, bool]
    lower_is_better: frozenset[str]
    only_in: dict[str, str] = field(default_factory=dict)  # evaluator -> 'base' | 'candidate'

    def regressions(self) -> list[str]:
        """Metrics where the candidate is shown worse, after correcting for the number of metrics."""
        out = []
        for name, c in self.by_metric.items():
            worse = Direction.BETTER if name in self.lower_is_better else Direction.WORSE
            if c.direction is worse and self.survives_holm.get(name):
                out.append(name)
        return out

    def improvements(self) -> list[str]:
        out = []
        for name, c in self.by_metric.items():
            better = Direction.WORSE if name in self.lower_is_better else Direction.BETTER
            if c.direction is better and self.survives_holm.get(name):
                out.append(name)
        return out

    def rows(self) -> list[dict[str, Any]]:
        rows = []
        for name, c in sorted(self.by_metric.items()):
            if name in self.lower_is_better:
                good = c.difference < 0
            else:
                good = c.difference > 0
            shown = c.direction is not Direction.NO_DETECTABLE_DIFFERENCE and self.survives_holm.get(name)
            verdict = ('better' if good else 'worse') if shown else 'no detectable difference'
            rows.append({
                'metric': name, 'base': c.mean_a, 'candidate': c.mean_b, 'difference': c.difference,
                'interval': c.interval, 'p': c.p_value, 'verdict': verdict, 'examples': c.examples,
                'missing_base': c.missing_a, 'missing_candidate': c.missing_b,
                'detectable': c.detectable, 'needed_for_observed': c.needed_for_observed, 'notes': c.notes,
            })  # fmt: skip
        return rows

    def markdown(self) -> str:
        lines = [
            f'**{self.candidate}** vs **{self.base}** (paired on shared examples; a run with no score counts as the worst score seen; '
            f'Holm-corrected across {len(self.by_metric)} metrics)',
            '',
            '| metric | base | candidate | difference [95%] | p | verdict | smallest detectable | examples needed |',
            '|---|---|---|---|---|---|---|---|',
        ]
        for r in self.rows():
            lo, hi = r['interval']
            det = 'none at this size' if r['detectable'] is None else f'{r["detectable"]:.3f}'
            need = '—' if r['needed_for_observed'] is None else str(r['needed_for_observed'])
            lines.append(
                f'| {r["metric"]} | {r["base"]:.3f} | {r["candidate"]:.3f} | {r["difference"]:+.3f} '
                f'[{lo:+.3f}, {hi:+.3f}] | {r["p"]:.3g} | {r["verdict"]} | {det} | {need} |'
            )
        for name, side in sorted(self.only_in.items()):
            lines.append(f'\n`{name}` was scored only in the {side} experiment, so it is not compared.')
        return '\n'.join(lines)


def compare_experiments(
    client: Any, base_id: str, candidate_id: str, alpha: float = 0.05, lower_is_better: Iterable[str] = ('task_error',)
) -> ExperimentComparison:
    """Is the candidate experiment really better than the base, metric by metric, or is it noise?"""
    base = experiment_scores(client, base_id)
    candidate = experiment_scores(client, candidate_id)
    lower = frozenset(lower_is_better)
    by_metric = {}
    only_in = {}
    for name in sorted(set(base) | set(candidate)):
        if name not in base or name not in candidate:
            only_in[name] = 'base' if name in base else 'candidate'  # not comparable: said, not dropped
            continue
        seen = [x for side in (base[name], candidate[name]) for v in side.values() for x in v if x is not None]
        # A run without a score counts as the worst score seen for that metric, in its direction.
        worst = (max(seen) if name in lower else min(seen)) if seen else 0.0
        by_metric[name] = compare(base[name], candidate[name], alpha=alpha, missing_as=worst)
    survives = holm({n: c.p_value for n, c in by_metric.items()}, alpha)
    return ExperimentComparison(base_id, candidate_id, by_metric, survives, lower, only_in)


# --- Datasets -------------------------------------------------------------------------------------


def audit_labels(labels: Sequence[str], threshold: float, alpha: float = 0.05) -> dict[str, Any]:
    """What a labelled dataset can decide about a judge, before anyone runs one on it."""
    n = len(labels)
    counts = Counter(labels)
    const = constant_judge(list(labels), threshold)
    k_min = min_successes_to_pass(n, threshold, alpha)
    out: dict[str, Any] = {
        'examples': n,
        'classes': dict(counts),
        'constant_judge_accuracy': const.accuracy,
        'constant_judge_passes': const.passes_gate,
        'min_correct_to_pass': k_min,
        'pass_probability': {f'{a:.2f}': pass_probability(n, a, threshold, alpha) for a in (0.9, 0.95, 0.99) if a > threshold},
        'examples_needed': {f'{a:.2f}': examples_to_pass(a, threshold) for a in (threshold + 0.05, threshold + 0.1) if a < 1},
    }  # fmt: skip
    warnings = []
    if len(counts) < 2:
        warnings.append('one label only: a judge that always gives it scores 100%')
    elif const.passes_gate:
        warnings.append(f'a judge that always answers {const.label!r} passes the bar')
    if k_min is None:
        warnings.append('no score on this many examples clears the bar on an interval')
    elif k_min == n:
        warnings.append('only a perfect score clears the bar on an interval')
    smallest = min(counts.values()) if counts else 0
    if len(counts) >= 2 and smallest < 10:
        warnings.append(f'the smallest class has {smallest} examples: its recall cannot be measured')
    out['warnings'] = warnings
    return out


# --- Human feedback on traces ---------------------------------------------------------------------


def feedback_certificate(
    client: Any, project: str, annotation_name: str, min_kappa: float = 0.6, alpha: float = 0.05, limit: int = 10_000
) -> dict[str, Any]:
    """Judge-vs-human agreement from the annotations already on a project's spans.

    Pairs each span's HUMAN label with its LLM label of the same name (both survive only when the
    judge writes under its own identifier: see FINDINGS §6), decides agreement on an interval, and
    lists the spans where they disagree, for review.
    """
    from phoenix_evidence._agreement import agreement
    from phoenix_evidence._certify import _labels_to_settle

    spans = client.spans.get_spans(project_identifier=project, limit=limit)
    annotations = client.spans.get_span_annotations(
        spans=spans, project_identifier=project, include_annotation_names=[annotation_name]
    )
    pairs = pairs_from_span_annotations(annotations, annotation_name)
    kinds: dict[str, dict[str, str]] = defaultdict(dict)
    for a in annotations:
        label = (a.get('result') or {}).get('label')
        if label is not None:
            kinds[a['span_id']].setdefault(a.get('annotator_kind'), str(label))
    human = {s for s, k in kinds.items() if 'HUMAN' in k}
    judged = {s for s, k in kinds.items() if 'LLM' in k}
    result = agreement(pairs, alpha=alpha)
    if result.kappa is None:
        verdict = 'NOT_ENOUGH_EVIDENCE'
    else:
        lo, hi = result.kappa_interval
        verdict = 'TRUSTWORTHY' if lo >= min_kappa else 'NOT_TRUSTWORTHY' if hi < min_kappa else 'NOT_ENOUGH_EVIDENCE'
    return {
        'project': project,
        'annotation': annotation_name,
        'verdict': verdict,
        'min_kappa': min_kappa,
        'paired_spans': result.examples,
        'spans_with_human_label': len(human),
        'spans_with_judge_label': len(judged),
        'human_label_but_no_judge_label': len(human - judged),
        'kappa': result.kappa,
        'kappa_interval': list(result.kappa_interval),
        'agreement': str(result),
        'labels_to_settle': _labels_to_settle(result, min_kappa, alpha) if verdict == 'NOT_ENOUGH_EVIDENCE' else None,
        'disagreements': [
            {'span_id': s, 'human': k['HUMAN'], 'judge': k['LLM']}
            for s, k in sorted(kinds.items())
            if 'HUMAN' in k and 'LLM' in k and k['HUMAN'] != k['LLM']
        ],
    }
