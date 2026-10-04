"""The drift canary on a real judge change: Codex's labels frozen, then the judge swapped for Haiku.

    uv run --extra phoenix python bench/canary_model_switch.py

The positive control the first canary run lacked (bench/canary_real.py only had a change that
turned out to be within noise). Cases: Phoenix's correctness, hallucination and
tool_response_handling suites, 168 cases. Frozen labels: Codex gpt-5.6-luna with no reasoning, first
run (results/judgments). Check 1: the same judge's second run (cached). Checks 2-4: Claude Haiku 4.5
on the exact prompts Phoenix's evaluators send (bench/render_prompts.py), each case judged by a
Claude Code subagent (the `claude` CLI's login had expired, so Haiku ran as four subagents of 42
cases each, recorded as such), read as three checks of 56 cases; checks 5-7: a second, fresh Haiku
pass (four new subagents) read the same way. Allowed flip rate 5%, as before.

Imports the Haiku labels from results/scratch/haiku/labels_*.jsonl into
results/judgments/<suite>.haiku.jsonl (cache format, model recorded) on first run; afterwards it
reads only the committed cache. Also reports each judge's agreement with the suites' labels and
the two judges' error correlation (`jury`). Writes results/canary_model_switch.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import OUT  # noqa: E402

from phoenix_evidence._canary import canary, count_flips  # noqa: E402
from phoenix_evidence._jury import jury  # noqa: E402

HERE = Path(__file__).resolve().parent
SUITES = ('correctness', 'hallucination', 'tool_response_handling')
HAIKU = 'claude-haiku-4-5 (Claude Code subagent, exact Phoenix evaluator prompt)'
ALLOWED = 0.05


def cache(name: str) -> dict[str, dict]:
    path = OUT / 'judgments' / f'{name}.jsonl'
    return {r['key']: r for r in map(json.loads, path.read_text().splitlines())} if path.exists() else {}


def import_haiku() -> None:
    prompts = {
        f'{r["suite"]}/{r["case"]}': r
        for r in map(json.loads, (OUT / 'scratch' / 'prompts.jsonl').read_text().splitlines())
    }
    rows: dict[str, list[dict]] = {s: [] for s in SUITES}
    for repeat, pattern in ((0, 'labels_*.jsonl'), (1, 'pass2_labels_*.jsonl')):
        for path in sorted((OUT / 'scratch' / 'haiku').glob(pattern)):
            for line in path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    p = prompts[r['id']]
                    rows[p['suite']].append({'key': f'{p["key"]}:{repeat}', 'case': p['case'], 'label': r['label'],
                                             'explanation': r['explanation'], 'error': None, 'model': HAIKU})  # fmt: skip
    for suite, items in rows.items():
        items.sort(key=lambda r: (r['key'][-1], r['case']))
        (OUT / 'judgments' / f'{suite}.haiku.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in items))


def main() -> None:
    if not all((OUT / 'judgments' / f'{s}.haiku.jsonl').exists() for s in SUITES):
        import_haiku()
    suites = json.loads((HERE / 'phoenix_suites' / 'suites.json').read_text())['suites']
    frozen, repeat, haiku, haiku2, truth, codex0 = {}, {}, {}, {}, {}, {}
    for suite in SUITES:
        codex, h = cache(suite), cache(f'{suite}.haiku')
        for row in h.values():
            key, n = row['key'].rsplit(':', 1)
            if n != '0':
                continue
            first, second = codex.get(f'{key}:0'), codex.get(f'{key}:1')
            if first is None or first['label'] is None:
                continue
            case = f'{suite}/{row["case"]}'
            frozen[case] = codex0[case] = first['label']
            repeat[case] = [second['label']] if second else [None]
            haiku[case] = [row['label']]
            second_haiku = h.get(f'{key}:1')
            haiku2[case] = [second_haiku['label'] if second_haiku else None]
            truth[case] = str(suites[f'{suite}.eval.ts']['truth'][row['case']])
    cases = sorted(frozen)
    thirds = [cases[k::3] for k in range(3)]
    looks = [('Codex, second run', *count_flips(frozen, repeat))]
    looks += [
        (f'Haiku, part {k + 1}', *count_flips(frozen, {c: haiku[c] for c in part})) for k, part in enumerate(thirds)
    ]
    looks += [
        (f'Haiku again, part {k + 1}', *count_flips(frozen, {c: haiku2[c] for c in part}))
        for k, part in enumerate(thirds)
    ]
    report = canary(looks, ALLOWED)
    for look in report.looks:
        print(f'{look.label}: {look.flips}/{look.checks}; evidence {look.evidence:.3g}; drifted {look.drifted}')
    print(report)
    acc = {name: sum(labels[c] == truth[c] for c in cases) / len(cases)
           for name, labels in (('codex', codex0), ('haiku', {c: haiku[c][0] for c in cases}))}  # fmt: skip
    j = jury([[codex0[c] for c in cases], [haiku[c][0] for c in cases]], [truth[c] for c in cases])
    print(f'agreement with the suites: Codex {acc["codex"]:.3f}, Haiku {acc["haiku"]:.3f}; {j}')
    haiku_self = sum(1 for c in cases if haiku2[c][0] != haiku[c][0]) / len(cases)
    print(f'Haiku against itself (second pass): {haiku_self:.3f} flips')
    by_suite = {s: {'cases': sum(1 for c in cases if c.startswith(s + '/')),
                    'flips_vs_codex': sum(1 for c in cases if c.startswith(s + '/') and haiku[c][0] != frozen[c])}
                for s in SUITES}  # fmt: skip
    (OUT / 'canary_model_switch.json').write_text(json.dumps({
        'frozen': 'codex:gpt-5.6-luna@none, first run', 'new_judge': HAIKU, 'allowed': ALLOWED, 'cases': len(cases),
        'looks': [vars(x) for x in report.looks], 'drifted': report.drifted, 'summary': str(report),
        'first_alarm': report.first_alarm.label if report.first_alarm else None,
        # Post hoc, not the pre-registered result: how the call depends on the allowed rate.
        'post_hoc_allowed_sensitivity': {
            str(a): {'drifted': (r := canary(looks, a)).drifted, 'first_alarm': r.first_alarm.label if r.first_alarm else None}
            for a in (0.02, 0.03, 0.04, 0.05)
        },
        'agreement_with_suite_labels': acc, 'haiku_self_flip_rate': haiku_self, 'jury': {**vars(j), 'summary': str(j)}, 'by_suite': by_suite,
    }, indent=1))  # fmt: skip


if __name__ == '__main__':
    main()
