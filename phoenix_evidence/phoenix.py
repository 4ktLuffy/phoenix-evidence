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

import math
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


def pairs_from_span_annotations(
    annotations: Iterable[Mapping[str, Any]],
    name: str,
    human_name: str | None = None,
    judge_identifier: str | None = None,
) -> list[list[Pair]]:
    """Group HUMAN and LLM annotations by span: one list of (human, judge) pairs per span.

    The judge's labels are the LLM annotations named `name`; the human labels are the HUMAN
    annotations named `human_name` (default: the same name). A separate human name is the safe
    choice in Phoenix today: labelling under the judge's name in the span annotation panel
    rewrites the judge's annotation as a human one (FINDINGS §6).

    `annotations` is what `client.spans.get_span_annotations(...)` returns. A span counts only when
    it has both kinds; several humans on one span give several pairs, which are resampled together.
    The latest LLM label per span is used, as Phoenix's own summaries do.
    """
    annotations = list(annotations)
    judge, _ = judge_labels(annotations, name, judge_identifier)
    human_name = human_name or name
    human: dict[str, list[str]] = defaultdict(list)
    for a in annotations:
        label = (a.get('result') or {}).get('label')
        if label is not None and a.get('annotator_kind') == 'HUMAN' and a.get('name') == human_name:
            human[a['span_id']].append(str(label))
    return [[(h, judge[span]) for h in labels] for span, labels in sorted(human.items()) if span in judge]


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
    return ExperimentComparison(
        _experiment_name(client, base_id), _experiment_name(client, candidate_id), by_metric, survives, lower, only_in
    )


@dataclass
class SequentialReport:
    metrics: dict[str, Any]  # name -> SequentialComparison, judged on everything finished so far
    only_in: dict[str, str] = field(default_factory=dict)  # metric -> 'base' | 'candidate': not tested
    alpha_per_metric: float = 0.05


def sequential_compare_experiments(
    client: Any, base_id: str, candidate_id: str, alpha: float = 0.05, lower_is_better: Iterable[str] = ('task_error',)
) -> SequentialReport:
    """Has the comparison been decided yet, metric by metric? Safe to rerun while both experiments are
    still running.

    Each call judges the examples both have finished as one look: the evidence depends only on how
    many disagreements went each way, so as long as later calls only add examples (and which examples
    finish first does not depend on how they score), every call is one more look at one growing
    sample and Ville's inequality covers them all. A decision is made on the current evidence only,
    never by replaying the examples in some order that was not the real one. Each metric uses alpha
    divided by every metric either experiment scored (Bonferroni); a metric only one side scored is
    reported in `only_in`, not tested. A run without a score counts as the worst possible score when
    the metric's scores lie in [0, 1] (fixed, so it cannot shift between calls), else the worst seen;
    repetitions of an example are averaged.
    """
    from phoenix_evidence._sequential import SequentialComparison

    base, candidate = experiment_scores(client, base_id), experiment_scores(client, candidate_id)
    lower = frozenset(lower_is_better)
    every = set(base) | set(candidate)
    per_metric = alpha / max(len(every), 1)
    report = SequentialReport({}, {n: 'base' if n in base else 'candidate' for n in every - (set(base) & set(candidate))},
                              per_metric)  # fmt: skip
    for name in sorted(set(base) & set(candidate)):
        seen = [x for side in (base[name], candidate[name]) for v in side.values() for x in v if x is not None]
        if all(0 <= x <= 1 for x in seen):
            worst = 1.0 if name in lower else 0.0
        else:
            worst = (max(seen) if name in lower else min(seen)) if seen else 0.0
        seq = SequentialComparison(alpha=per_metric, higher_is_better=name not in lower)
        pairs = []
        for example in sorted(set(base[name]) & set(candidate[name])):
            b, c = base[name][example], candidate[name][example]
            if b and c:
                pairs.append((sum(worst if x is None else x for x in b) / len(b),
                              sum(worst if x is None else x for x in c) / len(c)))  # fmt: skip
        report.metrics[name] = seq.look(pairs)
    return report


def _experiment_name(client: Any, experiment_id: str) -> str:
    """'name (id)' for display, or the id alone when the server cannot say."""
    try:
        name = _get(client.experiments.get(experiment_id=experiment_id), 'name')
    except Exception:
        return experiment_id
    return f'{name} ({experiment_id})' if name else experiment_id


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
    client: Any,
    project: str,
    annotation_name: str,
    min_kappa: float = 0.6,
    alpha: float = 0.05,
    limit: int = 10_000,
    human_annotation: str | None = None,
    judge_identifier: str | None = None,
) -> dict[str, Any]:
    """Judge-vs-human agreement from the annotations already on a project's spans.

    Pairs each span's HUMAN label with its LLM label of the same name (both survive only when the
    judge writes under its own identifier: see FINDINGS §6), decides agreement on an interval, and
    lists the spans where they disagree, for review.
    """
    from phoenix_evidence._agreement import agreement
    from phoenix_evidence._certify import _labels_to_settle

    spans = client.spans.get_spans(project_identifier=project, limit=limit)
    human_name = human_annotation or annotation_name
    annotations = client.spans.get_span_annotations(
        spans=spans, project_identifier=project, include_annotation_names=sorted({annotation_name, human_name})
    )
    pairs = pairs_from_span_annotations(annotations, annotation_name, human_name, judge_identifier)
    judge, _ = judge_labels(annotations, annotation_name, judge_identifier)
    human_by_span: dict[str, list[str]] = defaultdict(list)
    for a in annotations:
        label = (a.get('result') or {}).get('label')
        if label is not None and a.get('annotator_kind') == 'HUMAN' and a.get('name') == human_name:
            human_by_span[a['span_id']].append(str(label))
    human = set(human_by_span)
    judged = set(judge)
    result = agreement(pairs, alpha=alpha)
    if result.kappa is None:
        verdict = 'NOT_ENOUGH_EVIDENCE'
    else:
        lo, hi = result.kappa_interval
        verdict = 'TRUSTWORTHY' if lo >= min_kappa else 'NOT_TRUSTWORTHY' if hi < min_kappa else 'NOT_ENOUGH_EVIDENCE'
    return {
        'project': project,
        'annotation': annotation_name,
        'human_annotation': human_name,
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
        'judge_identifier': judge_identifier,
        # One entry per disagreeing (human, judge) pair, the same pairs agreement is computed on.
        'disagreements': [
            {'span_id': s, 'human': h, 'judge': judge[s]}
            for s, labels in sorted(human_by_span.items())
            for h in labels
            if s in judge and judge[s] != h
        ],
    }


# --- Corrected pass rate from a planned label queue ------------------------------------------------


def _instant(value: Any) -> float:
    """A timestamp as seconds since the epoch, comparing instants rather than strings (offsets differ)."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return float('-inf')
    else:
        return float('-inf')
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def judge_labels(
    annotations: Iterable[Mapping[str, Any]], name: str, identifier: str | None = None
) -> tuple[dict[str, str], dict[str, float]]:
    """The judge's label per span, and its doubt: 1.0 where its runs disagree on the span.

    With `identifier`, the label is that judge configuration's (Phoenix's online evaluators write
    one identifier per configuration); without it, the latest LLM label of any configuration. The
    doubt always uses every LLM annotation: a span the judge scored more than once (repeated runs,
    or several configurations) is "unsure" when those labels differ.
    """
    latest: dict[str, tuple[float, str]] = {}
    seen: dict[str, set[str]] = defaultdict(set)
    for a in annotations:
        if a.get('name') != name or a.get('annotator_kind') != 'LLM':
            continue
        label = (a.get('result') or {}).get('label')
        if label is None:
            continue
        span = a['span_id']
        seen[span].add(str(label))
        if identifier is not None and (a.get('identifier') or '') != identifier:
            continue
        stamp = _instant(a.get('updated_at') or a.get('created_at'))
        if span not in latest or stamp >= latest[span][0]:
            latest[span] = (stamp, str(label))
    return {s: v[1] for s, v in latest.items()}, {s: float(len(v) > 1) for s, v in seen.items()}


def judge_probabilities(
    annotations: Iterable[Mapping[str, Any]], name: str, identifier: str | None = None
) -> dict[str, float]:
    """The judge's score per span, read as its probability of a pass, picked as `judge_labels` picks
    the label (that identifier's, else the latest LLM annotation). Scores outside [0, 1] are refused."""
    latest: dict[str, tuple[float, float]] = {}
    for a in annotations:
        if a.get('name') != name or a.get('annotator_kind') != 'LLM':
            continue
        score = (a.get('result') or {}).get('score')
        if score is None or (identifier is not None and (a.get('identifier') or '') != identifier):
            continue
        if not 0 <= float(score) <= 1:
            raise ValueError(f'span {a["span_id"]}: score {score} is not a probability')
        stamp = _instant(a.get('updated_at') or a.get('created_at'))
        if a['span_id'] not in latest or stamp >= latest[a['span_id']][0]:
            latest[a['span_id']] = (stamp, float(score))
    return {s: v[1] for s, v in latest.items()}


def plan_label_queue(
    client: Any,
    project: str,
    name: str,
    budget: int,
    seed: int = 0,
    limit: int = 10_000,
    create_dataset: bool = True,
    human_annotation: str | None = None,
    judge_identifier: str | None = None,
    judge_probability: bool = False,
) -> dict[str, Any]:
    """Choose which judged spans humans should label, and put them in a Phoenix dataset linked to the spans.

    Spans where the judge's runs disagree are more likely to be chosen; every span keeps a chance.
    With `judge_probability`, the judge's annotation score is read as its probability of a pass: the
    plan uses sqrt(p(1 - p)) as the doubt and freezes the probabilities, which `corrected_rate_from_plan`
    then uses as the judge's value (bench/planner_probabilities.py: 1.3-1.6 times the labels' worth
    of a hard label with uniform sampling, when the probability is not overconfident).
    The returned plan (save it) records each span's inclusion probability, which `corrected_rate`
    needs: the human labels must come from this draw, not from spans people picked themselves.
    """
    from phoenix_evidence._ppi import plan_labels

    spans = client.spans.get_spans(project_identifier=project, limit=limit)
    annotations = client.spans.get_span_annotations(
        spans=spans, project_identifier=project, include_annotation_names=[name]
    )
    labels, doubt = judge_labels(annotations, name, judge_identifier)
    probability = judge_probabilities(annotations, name, judge_identifier) if judge_probability else None
    if probability is not None:
        labels = {s: v for s, v in labels.items() if s in probability}
        doubt = {s: 2 * math.sqrt(p * (1 - p)) for s, p in probability.items()}
    population = sorted(labels)
    chosen_idx, pi = plan_labels([doubt.get(s, 0.0) for s in population], budget, seed=seed)
    chosen = [population[i] for i in chosen_idx]
    plan = {
        'project': project, 'annotation': name, 'human_annotation': human_annotation or name, 'judge_identifier': judge_identifier, 'seed': seed, 'budget': budget,
        'population': population, 'inclusion': dict(zip(population, pi, strict=True)), 'chosen': chosen,
        'judge': {span: labels[span] for span in population},
        'judge_probability': {span: probability[span] for span in population} if probability is not None else None,
        'judge_unsure_spans': sum(1 for s in population if doubt.get(s)),
        'created_at': datetime.now(timezone.utc).isoformat(), 'dataset': None,
    }  # fmt: skip
    if create_dataset and chosen:
        import pandas as pd

        # The span link column must not double as an input column: Phoenix refuses the overlap.
        frame = pd.DataFrame(
            {
                'span': chosen,
                'span_id': chosen,
                'judge_label': [labels[s] for s in chosen],
                'inclusion': [plan['inclusion'][s] for s in chosen],
            }
        )
        dataset = client.datasets.create_dataset(
            name=f'label queue: {project} / {name} ({plan["created_at"][:19]})',
            dataframe=frame, input_keys=['span'], output_keys=[], metadata_keys=['judge_label', 'inclusion'],
            span_id_key='span_id',
            dataset_description=f'Spans chosen by phoenix-evidence for human labels of {name!r}. Label each span in Phoenix.',
        )  # fmt: skip
        plan['dataset'] = dataset.id
    return plan


def corrected_rate_from_plan(
    client: Any,
    plan: Mapping[str, Any],
    pass_label: str,
    limit: int = 10_000,
    human_annotation: str | None = None,
) -> dict[str, Any]:
    """The pass rate humans would give, from the judge on every planned span and humans on the chosen ones."""
    from phoenix_evidence._ppi import corrected_rate

    project, name = plan['project'], plan['annotation']
    human_name = human_annotation or plan.get('human_annotation') or name
    spans = client.spans.get_spans(project_identifier=project, limit=limit)
    annotations = client.spans.get_span_annotations(
        spans=spans, project_identifier=project, include_annotation_names=sorted({name, human_name})
    )
    # The judge's labels are the ones frozen in the plan: the population and the predictor must not
    # change after the draw (a later edit, or an annotation overwritten in the UI, would bias it).
    labels = plan.get('judge') or judge_labels(annotations, name, plan.get('judge_identifier'))[0]
    population = list(plan['population'])
    missing_judge = [s for s in population if s not in labels]
    # Several reviewers on one span: their share of pass labels is the span's human value.
    votes: dict[str, list[float]] = defaultdict(list)
    for a in annotations:
        label = (a.get('result') or {}).get('label')
        if a.get('name') == human_name and a.get('annotator_kind') == 'HUMAN' and label is not None:
            votes[a['span_id']].append(float(str(label) == pass_label))
    index = {s: i for i, s in enumerate(population)}
    missing = [s for s in plan['chosen'] if s not in votes]
    labelled = {index[s]: sum(votes[s]) / len(votes[s]) for s in plan['chosen'] if s in votes}
    out: dict[str, Any] = {
        'project': project, 'annotation': name, 'pass_label': pass_label, 'spans': len(population),
        'chosen': len(plan['chosen']), 'labelled': len(labelled), 'still_to_label': missing,
        'unplanned_human_labels': sorted(set(votes) - set(plan['chosen'])),
    }  # fmt: skip
    if missing_judge:
        out['result'] = None
        out['refused'] = f'{len(missing_judge)} planned spans have no judge label in the plan'
        return out
    if missing or not labelled:
        # A chosen span without a label is not a zero gap: estimating now would be biased.
        out['result'] = None
        out['refused'] = f'{len(missing)} chosen spans are not labelled yet; label them all, then rerun'
        return out
    probability = plan.get('judge_probability')
    r = corrected_rate(
        [probability[s] if probability else float(labels[s] == pass_label) for s in population],
        labelled,
        inclusion=[plan['inclusion'][s] for s in population],
    )
    out.update(
        estimate=r.estimate, raw_estimate=r.raw_estimate, interval=list(r.interval), judge_rate=r.judge_rate,
        human_only=list(r.human_only), judge_weight=r.weight, result=str(r),
    )  # fmt: skip
    return out


def experiment_judgments(client: Any, experiment_id: str, evaluator: str) -> dict[str, list[Any]]:
    """One evaluator's verdicts in an experiment: example -> one per repetition, the label when the
    evaluator gives one, else its score; None when the run or the evaluation errored or is missing."""
    ran = client.experiments.get_experiment(experiment_id=experiment_id)
    verdict: dict[str, Any] = {}
    for ev in _get(ran, 'evaluation_runs') or []:
        if _get(ev, 'name') != evaluator:
            continue
        result = _get(ev, 'result') or {}
        label, score = _get(result, 'label'), _get(result, 'score')
        verdict[_get(ev, 'experiment_run_id')] = None if _get(ev, 'error') else (label if label is not None else score)
    out: dict[str, list[Any]] = defaultdict(list)
    for run in sorted(
        _get(ran, 'task_runs') or [], key=lambda r: (_get(r, 'dataset_example_id'), _get(r, 'repetition_number') or 1)
    ):
        example = str(_get(run, 'dataset_example_id'))
        out[example].append(None if _get(run, 'error') else verdict.get(_get(run, 'id')))
    return dict(out)


def judge_canary(
    client: Any,
    reference_id: str,
    check_ids: Sequence[str],
    evaluator: str,
    allowed: float,
    alpha: float = 0.05,
) -> Any:
    """Has the judge drifted since `reference_id`? Each check is a later experiment on the same dataset
    that re-ran the judge as `evaluator`; checks are read in the order given (oldest first).

    The frozen verdicts are the reference experiment's first repetition per example (labels when the
    evaluator gives them, else scores); examples with no verdict there are left out. A check must
    re-score the whole frozen set: an example it errored on, or did not run, counts as a flip, so a
    check on a hand-picked subset cannot raise or hide evidence. Each check is used once: replaying
    one experiment would count its noise again.
    """
    from phoenix_evidence._canary import canary, count_flips

    if len(set(check_ids)) != len(check_ids) or reference_id in check_ids:
        raise ValueError('each check must be a different experiment, and not the reference')
    ref = experiment_judgments(client, reference_id, evaluator)
    reference = {ex: runs[0] for ex, runs in ref.items() if runs and runs[0] is not None}
    if not reference:
        raise ValueError(f'the reference experiment has no {evaluator!r} verdicts')
    looks = []
    for check_id in check_ids:
        today = experiment_judgments(client, check_id, evaluator)
        n, k = count_flips(reference, today)
        skipped = [ex for ex in reference if not today.get(ex)]
        looks.append((_experiment_name(client, check_id), n + len(skipped), k + len(skipped)))
    return canary(looks, allowed, alpha)


def doctor_dataset(
    client: Any,
    dataset: str,
    label_key: str = 'label',
    splits: Sequence[str] = (),
    threshold: float | None = None,
    similar: float = 0.8,
) -> Any:
    """Diagnose a Phoenix dataset: copies, conflicting labels, leakage between `splits`, balance.

    Phoenix filters examples by split but does not list an example's splits, so each named split is
    read on its own and the examples are tagged with every split they appear in.
    """
    from phoenix_evidence._doctor import Example, diagnose

    tags: dict[str, list[str]] = defaultdict(list)
    for split in splits:
        for example in client.datasets.get_dataset(dataset=dataset, splits=[split]).examples:
            tags[str(example['id'])].append(split)
    examples = []
    for example in client.datasets.get_dataset(dataset=dataset).examples:
        label = (example.get('output') or {}).get(label_key)
        eid = str(example['id'])
        examples.append(
            Example(eid, example.get('input') or {}, None if label is None else str(label), tuple(tags[eid]))
        )
    return diagnose(examples, similar=similar, threshold=threshold)
