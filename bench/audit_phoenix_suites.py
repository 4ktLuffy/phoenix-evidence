"""What can Phoenix's own evaluator benchmark suites decide? No model calls.

    uv run python bench/audit_phoenix_suites.py   # reads bench/phoenix_suites/suites.json

For each suite in js/benchmarks/evals-benchmarks (cases, labels and gates read from the suite
files by `bench/phoenix_suites/extract.mjs`):

1. constant judge: what a judge that always gives the most common label scores on accuracy and
   macro F1, and whether it passes the suite's gates;
2. today's accuracy gate alone (a single number against the bar): how often it passes a judge
   whose true accuracy is 5 points below the bar, and how often it fails one 5 points above;
3. a gate on an exact interval: the fewest correct answers that pass, and how many cases the
   suite would need for a judge 5 points above the bar to pass 80% of the time;
4. today's whole suite gate (accuracy and, where present, macro F1, both required): how often it
   passes the same judge, right on each case with probability 5 points below the accuracy bar
   and wrong to another label otherwise (simulated, since F1 has no closed form);
5. a realistic judge (97% accurate, as in Arize's Jev post): how often the exact gate passes it,
   and whether the suite can tell two such judges apart (paired, 4% of examples discordant);
6. the Jev post's pooled 517 examples: the smallest judge-vs-judge difference they detect.

Writes results/phoenix_suites_audit.json and .md.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_evidence import (  # noqa: E402
    constant_judge,
    detectable_difference,
    examples_to_pass,
    paired_examples_needed,
    pass_probability,
)
from phoenix_evidence._gate import min_successes_to_pass  # noqa: E402
from phoenix_evidence._intervals import _binomial_cdf  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'results'
GAP = 0.05
SIMS = 5_000
DISCORDANT = 0.04  # share of examples on which two ~97% judges disagree
JEV_EXAMPLES = 517


def macro_f1(truth: list[str], predicted: list[str]) -> float:
    """Macro F1 over the classes seen in either list, as Phoenix's evaluator computes it."""
    classes = sorted(set(truth) | set(predicted))
    f1s = []
    for c in classes:
        tp = sum(t == c and p == c for t, p in zip(truth, predicted, strict=True))
        fp = sum(t != c and p == c for t, p in zip(truth, predicted, strict=True))
        fn = sum(t == c and p != c for t, p in zip(truth, predicted, strict=True))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s)


def point_gate_pass(n: int, true_rate: float, bar: float) -> float:
    """Chance that the observed accuracy is at least the bar (Phoenix: average >= threshold)."""
    k = next((k for k in range(n + 1) if k / n >= bar - 1e-12), n + 1)
    return 1.0 - _binomial_cdf(k - 1, n, true_rate)


def suite_gate_pass(truth: list[str], accuracy: float, gates: dict[str, float], rng: random.Random) -> float:
    """Chance that every gate passes for a judge right on each case with probability `accuracy`."""
    labels = sorted(set(truth))
    if len(labels) < 2:
        labels.append('<another label>')  # a one-label suite: a wrong answer is still possible
    hits = 0
    for _ in range(SIMS):
        pred = [t if rng.random() < accuracy else rng.choice([x for x in labels if x != t]) for t in truth]
        acc_ok = sum(p == t for p, t in zip(pred, truth, strict=True)) / len(truth) >= gates['accuracy'] - 1e-12
        f1_ok = 'f1' not in gates or macro_f1(truth, pred) >= gates['f1'] - 1e-12
        hits += acc_ok and f1_ok
    return hits / SIMS


def main() -> None:
    data = json.loads((HERE / 'phoenix_suites' / 'suites.json').read_text())
    rng = random.Random(0)
    rows = []
    for name, suite in sorted(data['suites'].items(), key=lambda kv: len(kv[1]['truth'])):
        truth = [str(t) for t in suite['truth']]
        n = len(truth)
        gates = {c['annotationName']: c['threshold'] for c in suite['criteria']}
        acc_bar = gates['accuracy']
        const = constant_judge(truth, acc_bar)
        const_f1 = macro_f1(truth, [const.label] * n)
        k_min = min_successes_to_pass(n, acc_bar)
        row = {
            'suite': name.removesuffix('.eval.ts'),
            'cases': n,
            'classes': dict(Counter(truth)),
            'gates': gates,
            'constant_judge_accuracy': round(const.accuracy, 3),
            'constant_judge_macro_f1': round(const_f1, 3),
            'constant_judge_passes_all_gates': const.accuracy >= acc_bar
            and ('f1' not in gates or const_f1 >= gates['f1']),
            'point_gate_passes_judge_5pt_below': round(point_gate_pass(n, acc_bar - GAP, acc_bar), 3),
            'point_gate_fails_judge_5pt_above': round(1 - point_gate_pass(n, min(acc_bar + GAP, 1.0), acc_bar), 3),
            'exact_gate_min_correct': k_min,
            'exact_gate_min_accuracy': round(k_min / n, 3) if k_min is not None else None,
            'exact_gate_pass_prob_judge_5pt_above': round(pass_probability(n, min(acc_bar + GAP, 1.0), acc_bar), 3),
            'cases_needed_judge_5pt_above_80pct': examples_to_pass(min(acc_bar + GAP, 0.999), acc_bar),
            'exact_gate_pass_prob_judge_97pct': round(pass_probability(n, 0.97, acc_bar), 3),
            'detectable_judge_vs_judge_difference': detectable_difference(n, DISCORDANT),
        }
        row['suite_gate_passes_judge_5pt_below'] = round(suite_gate_pass(truth, acc_bar - GAP, gates, rng), 3)
        rows.append(row)
        print(name, 'done', flush=True)

    pooled = {
        'examples': JEV_EXAMPLES,
        'discordant_share': 0.039,  # 96.7% vs 99.4% accurate, errors assumed disjoint (the most favourable case)
        'smallest_detectable_difference': round(detectable_difference(JEV_EXAMPLES, 0.039) or float('nan'), 4),
        'examples_needed_2_7_points': paired_examples_needed(0.039, 0.027),
        'examples_needed_1_point': paired_examples_needed(0.039, 0.01),
    }
    OUT.mkdir(exist_ok=True)
    (OUT / 'phoenix_suites_audit.json').write_text(
        json.dumps({'phoenix_commit': data['phoenix_commit'], 'rows': rows, 'jev_pooled': pooled}, indent=1)
    )
    md = [f'Phoenix commit `{data["phoenix_commit"][:9]}`, {len(rows)} suites, {sum(r["cases"] for r in rows)} cases.\n',
          '| suite | cases | gates | constant judge: acc / F1 / passes? | accuracy gate passes a judge 5 pts below | '
          'whole suite gate (acc + F1) passes it | exact gate needs | exact gate passes a judge 5 pts above | '
          'cases needed (80%) | exact gate passes a 97% judge | can tell two 97% judges apart? |',
          '|---|---|---|---|---|---|---|---|---|---|---|']  # fmt: skip
    for r in rows:
        gates = ', '.join(f'{k} ≥ {v}' for k, v in r['gates'].items())
        f1 = r.get('suite_gate_passes_judge_5pt_below')
        k_min = r['exact_gate_min_correct']
        diff = r['detectable_judge_vs_judge_difference']
        constant = '**yes**' if r['constant_judge_passes_all_gates'] else 'no'
        cells = [
            r['suite'],
            r['cases'],
            gates,
            f'{r["constant_judge_accuracy"]:.2f} / {r["constant_judge_macro_f1"]:.2f} / {constant}',
            f'{r["point_gate_passes_judge_5pt_below"]:.0%}',
            '—' if f1 is None else f'{f1:.0%}',
            'impossible' if k_min is None else f'{k_min}/{r["cases"]} ({r["exact_gate_min_accuracy"]:.0%})',
            f'{r["exact_gate_pass_prob_judge_5pt_above"]:.0%}',
            r['cases_needed_judge_5pt_above_80pct'],
            f'{r["exact_gate_pass_prob_judge_97pct"]:.0%}',
            'no' if diff is None else f'{diff:.2f}',
        ]
        md.append('| ' + ' | '.join(str(c) for c in cells) + ' |')
    md.append(
        f"\nPooled, the Jev post's {pooled['examples']} examples detect a judge-vs-judge difference of "
        f'{pooled["smallest_detectable_difference"]:.3f} at 80% power; 1 point needs {pooled["examples_needed_1_point"]} '
        f'examples, 2.7 points (96.7% vs 99.4%) needs {pooled["examples_needed_2_7_points"]}.'
    )
    (OUT / 'phoenix_suites_audit.md').write_text('\n'.join(md) + '\n')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
