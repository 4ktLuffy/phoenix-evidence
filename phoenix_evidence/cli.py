"""`phoenix-evidence`: the questions Phoenix's numbers leave open, answered against any Phoenix server.

    phoenix-evidence compare BASE_EXPERIMENT_ID CANDIDATE_EXPERIMENT_ID [--fail-on-regression] [--sequential]
    phoenix-evidence certify-feedback PROJECT ANNOTATION_NAME [--min-kappa 0.6] [--strict]
    phoenix-evidence audit DATASET --threshold 0.8 [--label-key label]
    phoenix-evidence plan-labels PROJECT ANNOTATION_NAME --budget 60 --out plan.json
    phoenix-evidence corrected-rate plan.json --pass-label helpful
    phoenix-evidence price --traces 10000 --width 0.1 --judge-cost 0.002 --human-cost 0.5 [--disagreement 0.1]
    phoenix-evidence doctor DATASET [--splits train,test] [--threshold 0.8]
    phoenix-evidence canary REFERENCE_EXPERIMENT CHECK_EXPERIMENT... --evaluator NAME --allowed 0.05

The server is the one `phoenix.client.Client()` finds (PHOENIX_BASE_URL, PHOENIX_API_KEY), or
`--url`. Every command takes `--json PATH`. In GitHub Actions, `compare` also writes its table to
the job summary. Exit status: 1 when `compare --fail-on-regression` finds a regression, or
`certify-feedback` finds the judge NOT_TRUSTWORTHY (with `--strict`, also NOT_ENOUGH_EVIDENCE),
or `canary --fail-on-drift` shows drift.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _client(url: str | None) -> Any:
    from phoenix.client import Client

    return Client(base_url=url) if url else Client()


def _dump(path: str | None, data: Any) -> None:
    if path:
        Path(path).write_text(json.dumps(data, indent=1, default=str))


def _compare(args: argparse.Namespace) -> int:
    from phoenix_evidence.phoenix import compare_experiments

    lower = ['task_error', *(m for m in (args.lower_is_better or '').split(',') if m)]
    if args.sequential:
        return _compare_sequential(args, lower)
    result = compare_experiments(_client(args.url), args.base, args.candidate, args.alpha, lower)
    table = result.markdown()
    print(table)
    regressions, improvements = result.regressions(), result.improvements()
    print()
    print(
        f'regressions: {", ".join(regressions) or "none shown"}; improvements: {", ".join(improvements) or "none shown"}'
    )
    for r in result.rows():
        for note in r['notes']:
            print(f'  {r["metric"]}: {note}')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write(table + '\n')
    _dump(args.json, {'rows': result.rows(), 'regressions': regressions, 'improvements': improvements})
    return 1 if args.fail_on_regression and regressions else 0


def _compare_sequential(args: argparse.Namespace, lower: list[str]) -> int:
    from phoenix_evidence.phoenix import sequential_compare_experiments

    report = sequential_compare_experiments(_client(args.url), args.base, args.candidate, args.alpha, lower)
    lines = [f'{name}: {seq}' for name, seq in report.metrics.items()]
    lines += [f'{name}: scored only in the {side}; not tested' for name, side in report.only_in.items()]
    lines.append(f'(each metric at alpha {report.alpha_per_metric:.4g}: {args.alpha:g} over '
                 f'{len(report.metrics) + len(report.only_in)} metrics)')  # fmt: skip
    text = '\n'.join(lines)
    print(text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as f:
            f.write('```\n' + text + '\n```\n')
    regressions = [n for n, s in report.metrics.items() if s.decision == 'candidate worse']
    _dump(args.json, {'metrics': {n: {'pairs': s.pairs, 'better': s.better, 'worse': s.worse, 'ties': s.ties,
                                      'evidence': s.evidence, 'decision': s.decision}
                                  for n, s in report.metrics.items()},
                      'only_in': report.only_in, 'alpha_per_metric': report.alpha_per_metric})  # fmt: skip
    return 1 if args.fail_on_regression and regressions else 0


def _certify_feedback(args: argparse.Namespace) -> int:
    from phoenix_evidence.phoenix import feedback_certificate

    result = feedback_certificate(
        _client(args.url),
        args.project,
        args.annotation,
        args.min_kappa,
        args.alpha,
        human_annotation=args.human_annotation,
        judge_identifier=args.judge_identifier,
    )
    print(f'{result["verdict"]}: judge {args.annotation!r} vs human feedback in {args.project!r}')
    print(f'  {result["paired_spans"]} spans carry both labels; {result["spans_with_human_label"]} have a human '
          f'label, {result["spans_with_judge_label"]} a judge label')  # fmt: skip
    if result['human_label_but_no_judge_label']:
        print(f'  {result["human_label_but_no_judge_label"]} spans have a human label and no judge label: if the '
              'judge wrote under the same name and identifier, the human label replaced it')  # fmt: skip
    for line in result['agreement'].splitlines():
        print(f'  {line}')
    if result['labels_to_settle']:
        print(f'  about {result["labels_to_settle"]} spans with both labels would likely settle it')
    if result['disagreements']:
        print(f'  {len(result["disagreements"])} spans where judge and human disagree (first 10):')
        for d in result['disagreements'][:10]:
            print(f'    {d["span_id"]}: human {d["human"]!r}, judge {d["judge"]!r}')
    if args.export_disagreements and result['disagreements']:
        import pandas as pd

        frame = pd.DataFrame(result['disagreements'])
        frame['span'] = frame['span_id']  # the span link column must not double as an input column
        dataset = _client(args.url).datasets.create_dataset(
            name=f'disagreements: {args.project} / {args.annotation}',
            dataframe=frame, input_keys=['span'], output_keys=['human'], metadata_keys=['judge'], span_id_key='span_id',
            dataset_description='Spans where the judge and a human disagree (phoenix-evidence); for tuning the evaluator.',
        )  # fmt: skip
        print(f'  exported {len(frame)} disagreements to Phoenix dataset {dataset.id}')
    _dump(args.json, result)
    bad = {'NOT_TRUSTWORTHY'} | ({'NOT_ENOUGH_EVIDENCE'} if args.strict else set())
    return 1 if result['verdict'] in bad else 0


def _audit(args: argparse.Namespace) -> int:
    from phoenix_evidence.phoenix import audit_labels

    dataset = _client(args.url).datasets.get_dataset(dataset=args.dataset)
    labels = [str((e.get('output') or {}).get(args.label_key)) for e in dataset.examples]
    labels = [label for label in labels if label != 'None']
    result = audit_labels(labels, args.threshold, args.alpha)
    print(f'{args.dataset}: {result["examples"]} labelled examples {result["classes"]}, bar {args.threshold}')
    k = result['min_correct_to_pass']
    print(f'  to pass on an interval a judge needs {k}/{result["examples"]} correct' if k is not None
          else '  no score on this many examples passes on an interval')  # fmt: skip
    for acc, p in result['pass_probability'].items():
        print(f'  a judge that is right {float(acc):.0%} of the time passes with probability {p:.0%}')
    for acc, n in result['examples_needed'].items():
        print(f'  examples for a {float(acc):.0%} judge to pass 80% of the time: {n}')
    for w in result['warnings']:
        print(f'  warning: {w}')
    _dump(args.json, result)
    return 0


def _plan_labels(args: argparse.Namespace) -> int:
    from phoenix_evidence.phoenix import plan_label_queue

    plan = plan_label_queue(
        _client(args.url),
        args.project,
        args.annotation,
        args.budget,
        seed=args.seed,
        human_annotation=args.human_annotation,
        judge_identifier=args.judge_identifier,
        judge_probability=args.judge_probability,
    )
    Path(args.out).write_text(json.dumps(plan, indent=1))
    print(f'{len(plan["chosen"])} of {len(plan["population"])} judged spans chosen for human labels '
          f'({plan["judge_unsure_spans"]} spans where the judge was unsure are favoured); plan saved to {args.out}')  # fmt: skip
    if plan['dataset']:
        print(
            f'  label queue: Phoenix dataset {plan["dataset"]}, linked to the spans; label {plan["human_annotation"]!r} on each'
        )
    print('  label the chosen spans, not others: the correction is only unbiased for this draw')
    return 0


def _corrected_rate(args: argparse.Namespace) -> int:
    from phoenix_evidence.phoenix import corrected_rate_from_plan

    plan = json.loads(Path(args.plan).read_text())
    out = corrected_rate_from_plan(_client(args.url), plan, args.pass_label, human_annotation=args.human_annotation)
    print(f'{plan["project"]} / {plan["annotation"]}: {out["labelled"]} of {out["chosen"]} chosen spans labelled')
    if out.get('refused'):
        print(f'  no estimate: {out["refused"]}')
    if out.get('unplanned_human_labels'):
        print(f'  {len(out["unplanned_human_labels"])} human labels on spans the plan did not choose are not used')
    if out.get('result'):
        print(f'  pass rate ({args.pass_label!r}): {out["result"]}')
    _dump(args.json, out)
    return 0


def _price(args: argparse.Namespace) -> int:
    from phoenix_evidence._price import price_of_certainty

    p = price_of_certainty(args.traces, args.width, args.judge_cost, args.human_cost, args.pass_rate,
                           args.disagreement, args.alpha)  # fmt: skip
    print(p)
    _dump(args.json, {'human_only': vars(p.human_only), 'corrected': vars(p.corrected),
                      'break_even_human_cost': p.break_even_human_cost})  # fmt: skip
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from phoenix_evidence.phoenix import doctor_dataset

    splits = [x for x in (args.splits or '').split(',') if x]
    d = doctor_dataset(_client(args.url), args.dataset, args.label_key, splits, args.threshold, args.similar)
    print(d)
    for a, b, sim in d.conflicting:
        print(f'  different labels: {a} / {b} (similarity {sim})')
    for a, b, sim in d.cross_split:
        print(f'  across splits: {a} / {b} (similarity {sim})')
    _dump(args.json, {'problems': d.problems(), 'exact_copies': d.exact_copies, 'near_copies': d.near_copies,
                      'conflicting': d.conflicting, 'cross_split': d.cross_split,
                      'in_several_splits': d.in_several_splits, 'unlabelled': d.unlabelled, 'labels': d.labels})  # fmt: skip
    return 1 if args.strict and d.problems() else 0


def _canary(args: argparse.Namespace) -> int:
    from phoenix_evidence.phoenix import judge_canary

    report = judge_canary(_client(args.url), args.reference, args.checks, args.evaluator, args.allowed, args.alpha)
    for look in report.looks:
        mark = '  DRIFT' if look.drifted else ''
        print(f'{look.label}: {look.flips} flips in {look.checks}; evidence {look.evidence:.2f}{mark}')
    print(report)
    _dump(args.json, {'allowed': report.allowed, 'alpha': report.alpha, 'drifted': report.drifted,
                      'looks': [vars(look) for look in report.looks]})  # fmt: skip
    return 1 if args.fail_on_drift and report.drifted else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='phoenix-evidence', description=__doc__.split('\n\n')[0])
    parser.add_argument('--url', help='Phoenix base URL (default: PHOENIX_BASE_URL or the client default)')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('compare', help='is the candidate experiment really better than the base?')
    p.add_argument('base')
    p.add_argument('candidate')
    p.add_argument('--alpha', type=float, default=0.05)
    p.add_argument('--lower-is-better', help='comma-separated evaluator names where a lower score is better')
    p.add_argument('--fail-on-regression', action='store_true')
    p.add_argument(
        '--sequential',
        action='store_true',
        help='decide as soon as the evidence allows; safe to rerun while the experiments are still running',
    )
    p.add_argument('--json')
    p.set_defaults(run=_compare)

    p = sub.add_parser('certify-feedback', help="can this judge be trusted, against the project's human feedback?")
    p.add_argument('project')
    p.add_argument('annotation')
    p.add_argument('--min-kappa', type=float, default=0.6)
    p.add_argument('--alpha', type=float, default=0.05)
    p.add_argument('--strict', action='store_true', help='exit 1 on NOT_ENOUGH_EVIDENCE too')
    p.add_argument(
        '--export-disagreements', action='store_true', help='save them as a Phoenix dataset linked to the spans'
    )
    p.add_argument('--json')
    p.add_argument(
        '--human-annotation',
        help="the name humans label under, if not the judge's (labelling under the judge's own name in Phoenix's span panel overwrites the judge's annotation)",
    )
    p.add_argument(
        '--judge-identifier',
        help='the judge configuration to use (its annotation identifier); default: the latest judge label of any configuration',
    )
    p.set_defaults(run=_certify_feedback)

    p = sub.add_parser('plan-labels', help='choose which judged spans humans should label next')
    p.add_argument('project')
    p.add_argument('annotation')
    p.add_argument('--budget', type=int, required=True, help='expected number of human labels')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--out', default='label-plan.json')
    p.add_argument(
        '--human-annotation',
        help="the name humans label under, if not the judge's (labelling under the judge's own name in Phoenix's span panel overwrites the judge's annotation)",
    )
    p.add_argument(
        '--judge-identifier',
        help='the judge configuration to use (its annotation identifier); default: the latest judge label of any configuration',
    )
    p.add_argument(
        '--judge-probability',
        action='store_true',
        help="read the judge's annotation score as its probability of a pass: used to choose spans and in the corrected rate",
    )
    p.set_defaults(run=_plan_labels)

    p = sub.add_parser('corrected-rate', help="the judge's pass rate, corrected with the planned human labels")
    p.add_argument('plan')
    p.add_argument('--pass-label', required=True, help='the label that counts as a pass')
    p.add_argument('--json')
    p.add_argument(
        '--human-annotation',
        help="the name humans label under, if not the judge's (labelling under the judge's own name in Phoenix's span panel overwrites the judge's annotation)",
    )
    p.set_defaults(run=_corrected_rate)

    p = sub.add_parser('price', help='cheapest mix of judge calls and human labels for a given interval width')
    p.add_argument('--traces', type=int, required=True)
    p.add_argument('--width', type=float, required=True, help='full width of the interval, e.g. 0.1 for +/-0.05')
    p.add_argument('--judge-cost', type=float, required=True, help='cost of one judge call')
    p.add_argument('--human-cost', type=float, required=True, help='cost of one human label')
    p.add_argument('--pass-rate', type=float, default=0.5, help='expected pass rate (0.5 is the worst case)')
    p.add_argument('--disagreement', type=float, default=0.1,
                   help='how often judge and human differ (certify-feedback measures it)')  # fmt: skip
    p.add_argument('--alpha', type=float, default=0.05)
    p.add_argument('--json')
    p.set_defaults(run=_price, url=None)

    p = sub.add_parser('doctor', help='copies, conflicting labels and split leakage in a labelled dataset')
    p.add_argument('dataset')
    p.add_argument('--label-key', default='label')
    p.add_argument('--splits', help='comma-separated split names to check for leakage between')
    p.add_argument('--threshold', type=float, help='the pass bar a judge must clear on this dataset')
    p.add_argument('--similar', type=float, default=0.8, help='word 3-gram Jaccard similarity for a near-copy')
    p.add_argument('--strict', action='store_true', help='exit 1 when any problem is found')
    p.add_argument('--json')
    p.set_defaults(run=_doctor)

    p = sub.add_parser('canary', help='has the judge drifted? safe to run on every new check')
    p.add_argument('reference', help='experiment holding the frozen judge labels')
    p.add_argument('checks', nargs='+', help='later experiments that re-ran the judge, oldest first')
    p.add_argument('--evaluator', required=True, help='the judge evaluator name in those experiments')
    p.add_argument('--allowed', type=float, required=True,
                   help="flip rate that is not drift; the judge's own repeat-flip rate is a floor")  # fmt: skip
    p.add_argument('--alpha', type=float, default=0.05)
    p.add_argument('--fail-on-drift', action='store_true')
    p.add_argument('--json')
    p.set_defaults(run=_canary)

    p = sub.add_parser('audit', help='what can this labelled dataset decide about a judge?')
    p.add_argument('dataset')
    p.add_argument('--threshold', type=float, required=True)
    p.add_argument('--label-key', default='label')
    p.add_argument('--alpha', type=float, default=0.05)
    p.add_argument('--json')
    p.set_defaults(run=_audit)

    args = parser.parse_args(argv)
    return int(args.run(args))


def main_exit() -> None:
    try:
        sys.exit(main())
    except ValueError as e:  # refusals and bad input: say why; the traceback on request
        if os.environ.get('PHOENIX_EVIDENCE_DEBUG'):
            raise
        print(f'phoenix-evidence: {e} (set PHOENIX_EVIDENCE_DEBUG=1 for the traceback)', file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        if type(e).__name__ in {'ConnectError', 'ConnectTimeout'}:
            print(f'phoenix-evidence: cannot reach Phoenix ({e}). Is the server running? '
                  'Pass --url or set PHOENIX_BASE_URL.', file=sys.stderr)  # fmt: skip
            sys.exit(2)
        raise
