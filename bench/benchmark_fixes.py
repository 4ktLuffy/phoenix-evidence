"""Do the benchmark-data fixes (upstream/05) resolve the audit's flags? Re-judges only the changed cases.

    uv run --extra phoenix python bench/benchmark_fixes.py

Reads the case texts from the patched suites (results/scratch/suites.inputs.patched.json, written
by bench/phoenix_suites/extract.mjs run against a Phoenix checkout with upstream/05 applied) and
the original ones (bench/phoenix_suites/suites.inputs.json), and for every case that changed,
judges the new text twice with the suite's own evaluator on Codex (same model and settings as the
label audit). Before: the cached verdicts on the original text. After: the new verdicts. Labels
come from bench/phoenix_suites/suites.json; upstream/05 changes texts, not label order.
Writes results/benchmark_fixes.json.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import EFFORT, MODEL, OUT, CachedJudge  # noqa: E402
from label_audit import AUDIT  # noqa: E402
from phoenix.evals import LLM  # noqa: E402

HERE = Path(__file__).resolve().parent


def cached_labels(judge: CachedJudge, payload: dict) -> list[str | None]:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return [judge.cache[f'{digest}:{n}']['label'] for n in range(2) if f'{digest}:{n}' in judge.cache]


async def main() -> None:
    suites = json.loads((HERE / 'phoenix_suites' / 'suites.json').read_text())['suites']
    before = json.loads((HERE / 'phoenix_suites' / 'suites.inputs.json').read_text())['inputs']
    after = json.loads((OUT / 'scratch' / 'suites.inputs.patched.json').read_text())['inputs']
    llm = LLM(provider='codex', model=MODEL, effort=EFFORT)
    rows = []
    for suite_file, cases in after.items():
        name = suite_file.removesuffix('.eval.ts')
        changed = [i for i, (x, y) in enumerate(zip(before[suite_file], cases, strict=True)) if x != y]
        if not changed:
            continue
        spec = AUDIT[name]
        judge = CachedJudge(name, spec['evaluator'](llm=llm))
        for i in changed:
            old_payload, new_payload = spec['to_input'](before[suite_file][i]), spec['to_input'](cases[i])
            new = []
            for _ in range(2):
                try:
                    new.append(await judge(new_payload))
                except Exception:
                    new.append(None)
            label = suites[suite_file]['truth'][i]
            old = cached_labels(judge, old_payload)
            rows.append({
                'suite': name, 'case': i, 'label': label, 'before': old, 'after': new,
                'flagged_before': len(set(old)) == 1 and old[0] != label if len(old) == 2 else None,
                'flagged_after': len(set(new)) == 1 and new[0] != label,
            })  # fmt: skip
            print(f'{name} {i}: label {label}; before {old}; after {new}', flush=True)
    result = {'model': f'codex:{MODEL}@{EFFORT}', 'rows': rows,
              'flagged_before': sum(1 for r in rows if r['flagged_before']),
              'flagged_after': sum(1 for r in rows if r['flagged_after'])}  # fmt: skip
    (OUT / 'benchmark_fixes.json').write_text(json.dumps(result, indent=1))
    print(
        f'flagged before: {result["flagged_before"]}, after: {result["flagged_after"]} (of {len(rows)} changed cases)'
    )


if __name__ == '__main__':
    asyncio.run(main())
