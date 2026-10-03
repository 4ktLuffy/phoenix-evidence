"""`phoenix-evidence`: the questions Phoenix's numbers leave open, answered against any Phoenix server.

    phoenix-evidence compare BASE_EXPERIMENT_ID CANDIDATE_EXPERIMENT_ID [--fail-on-regression]
    phoenix-evidence certify-feedback PROJECT ANNOTATION_NAME [--min-kappa 0.6] [--strict]
    phoenix-evidence audit DATASET --threshold 0.8 [--label-key label]

The server is the one `phoenix.client.Client()` finds (PHOENIX_BASE_URL, PHOENIX_API_KEY), or
`--url`. Every command takes `--json PATH`. In GitHub Actions, `compare` also writes its table to
the job summary. Exit status: 1 when `compare --fail-on-regression` finds a regression, or
`certify-feedback` finds the judge NOT_TRUSTWORTHY (with `--strict`, also NOT_ENOUGH_EVIDENCE).
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


def _certify_feedback(args: argparse.Namespace) -> int:
    from phoenix_evidence.phoenix import feedback_certificate

    result = feedback_certificate(_client(args.url), args.project, args.annotation, args.min_kappa, args.alpha)
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
    p.add_argument('--json')
    p.set_defaults(run=_compare)

    p = sub.add_parser('certify-feedback', help="can this judge be trusted, against the project's human feedback?")
    p.add_argument('project')
    p.add_argument('annotation')
    p.add_argument('--min-kappa', type=float, default=0.6)
    p.add_argument('--alpha', type=float, default=0.05)
    p.add_argument('--strict', action='store_true', help='exit 1 on NOT_ENOUGH_EVIDENCE too')
    p.add_argument('--json')
    p.set_defaults(run=_certify_feedback)

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
    sys.exit(main())
