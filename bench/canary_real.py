"""The drift canary on real judge labels: a repeat of the same judge, then a changed judge.

    uv run --extra phoenix python bench/canary_real.py

Frozen set: every case of Phoenix's benchmark suites that the label audit and the certificates
judged (results/judgments), with the label from the judge's first run (Codex gpt-5.6-luna, no
reasoning). Check 1, "same judge, another day": the judge's second run on the same cases, already
cached. Checks 2-4, "after a config change": the same model with reasoning effort switched from
none to low, run once over the frozen set in a random order and read as three checks of a third
each, like a canary that re-scores part of the set every day. Allowed flip rate: 5%, fixed before
this ran (about twice the repeat-flip rate measured in the label audit). Writes
results/canary_real.json.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import OUT, SUITES, CachedJudge, load_inputs  # noqa: E402
from label_audit import AUDIT  # noqa: E402
from phoenix.evals import LLM  # noqa: E402

from phoenix_evidence._canary import canary, count_flips  # noqa: E402

ALLOWED, MODEL, NEW_EFFORT = 0.05, 'gpt-5.6-luna', 'low'


def digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def main() -> None:
    specs = {**AUDIT, **SUITES}
    frozen, repeat, items = {}, {}, []
    for name, spec in sorted(specs.items()):
        cache = CachedJudge(name, None).cache
        for i, case in enumerate(load_inputs(f'{name}.eval.ts')):
            payload = spec['to_input'](case)
            first, second = cache.get(f'{digest(payload)}:0'), cache.get(f'{digest(payload)}:1')
            if first is None or first['label'] is None:
                continue
            key = f'{name}/{i}'
            frozen[key] = first['label']
            repeat[key] = [second['label'] if second else None] if second else []
            items.append((key, name, payload))
    repeat = {k: v for k, v in repeat.items() if v}
    print(f'frozen set: {len(frozen)} cases from {len(specs)} suites; {len(repeat)} with a cached second run')

    llm = LLM(provider='codex', model=MODEL, effort=NEW_EFFORT)
    judges = {name: CachedJudge(f'{name}.{NEW_EFFORT}', specs[name]['evaluator'](llm=llm),
                                model=f'codex:{MODEL}@{NEW_EFFORT}') for name in specs}  # fmt: skip
    semaphore = asyncio.Semaphore(8)

    async def ask(name: str, payload: dict) -> str | None:
        async with semaphore:
            try:
                return await judges[name](payload)
            except Exception:
                return None

    random.Random(0).shuffle(items)
    labels = await asyncio.gather(*(ask(name, payload) for _, name, payload in items))
    changed = {key: [label] for (key, _, _), label in zip(items, labels, strict=True)}
    print(f'{sum(j.new_calls for j in judges.values())} new calls')

    thirds = [items[k::3] for k in range(3)]
    looks = [('same judge, second run', *count_flips(frozen, repeat))]
    for k, part in enumerate(thirds):
        looks.append(
            (f'effort {NEW_EFFORT}, part {k + 1}', *count_flips(frozen, {key: changed[key] for key, _, _ in part}))
        )
    report = canary(looks, ALLOWED)
    for look in report.looks:
        print(f'{look.label}: {look.flips}/{look.checks}; evidence {look.evidence:.3g}; drifted {look.drifted}')
    print(report)
    errors = sum(1 for v in changed.values() if v[0] is None)
    by_suite: dict[str, list[int]] = {}
    for key, _, _ in items:
        name = key.split('/')[0]
        row = by_suite.setdefault(name, [0, 0, 0])
        row[0] += 1
        row[1] += repeat.get(key, [frozen[key]])[0] != frozen[key]
        row[2] += changed[key][0] != frozen[key]
    (OUT / 'canary_real.json').write_text(json.dumps({
        'reference': f'codex:{MODEL}@none, first run', 'changed_judge': f'codex:{MODEL}@{NEW_EFFORT}',
        'allowed': ALLOWED, 'alpha': report.alpha, 'cases': len(frozen), 'errors_in_changed_run': errors,
        'looks': [vars(look) for look in report.looks], 'drifted': report.drifted, 'summary': str(report),
        'by_suite': {k: {'cases': v[0], 'repeat_flips': v[1], 'changed_flips': v[2]} for k, v in by_suite.items()},
    }, indent=1))  # fmt: skip


if __name__ == '__main__':
    asyncio.run(main())
