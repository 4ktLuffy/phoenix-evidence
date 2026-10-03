"""Does a note to the grader change Phoenix's RefusalEvaluator, or does any appended text?

    uv run --extra phoenix python bench/injection_refusal.py

The refusal certificate saw the judge switch 2 of 23 refusals to "answered" when the answer ended
with a note claiming the correct label is "answered", while reformatting and repeats changed
nothing. This separates the note's claim from the mere presence of a note: every case the suite
labels "refused" is judged 3 times with the grader note and 3 times with a neutral note of
similar length that claims nothing, and the two are compared per case with phoenix_evidence's
paired comparison. Same judge and cache as bench/certify_phoenix_suites.py. Writes
results/injection_refusal.json.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import EFFORT, MODEL, OUT, CachedJudge, load_inputs  # noqa: E402
from phoenix.evals import LLM  # noqa: E402
from phoenix.evals.metrics.refusal import RefusalEvaluator  # noqa: E402

from phoenix_evidence import Case, compare, grader_note, neutral_note  # noqa: E402
from phoenix_evidence._intervals import clopper_pearson  # noqa: E402

REPEATS = 3


async def main() -> None:
    suites = json.loads((OUT.parent / 'bench' / 'phoenix_suites' / 'suites.json').read_text())
    data = suites['suites']['refusal.eval.ts']
    cases = [
        Case(str(i), {'input': inp['question'], 'output': inp['answer']}, label)
        for i, (inp, label) in enumerate(zip(load_inputs('refusal.eval.ts'), data['truth'], strict=True))
        if label == 'refused'
    ]
    llm = LLM(provider='codex', model=MODEL, effort=EFFORT)
    judge = CachedJudge('refusal', RefusalEvaluator(llm=llm))
    rng = random.Random(0)
    semaphore = asyncio.Semaphore(8)

    async def ask(payload: dict) -> str | None:
        async with semaphore:
            try:
                return await judge(payload)
            except Exception:
                return None

    conditions = {'grader_note': grader_note('answered'), 'neutral_note': neutral_note()}
    payloads = {name: [dict(c.rewrite(case, cases, rng)) for case in cases] for name, c in conditions.items()}
    flips: dict[str, dict[str, list[bool | None]]] = {}
    for name, rows in payloads.items():
        # Repeats are issued one round at a time so the cache numbers them in order.
        labels = []
        for _ in range(REPEATS):
            labels.append(await asyncio.gather(*(ask(p) for p in rows)))
        flips[name] = {
            case.id: [None if r[i] is None else r[i] != 'refused' for r in labels] for i, case in enumerate(cases)
        }
    result = {'model': f'codex:{MODEL}@{EFFORT}', 'cases': len(cases), 'repeats': REPEATS}
    for name, by_case in flips.items():
        done = [x for v in by_case.values() for x in v if x is not None]
        cases_flipped = sorted(k for k, v in by_case.items() if any(v))
        # The case is the unit: repeats of one case are not independent (here they always agree),
        # so the interval is on cases flipped out of cases, not on judgments.
        lo, hi = clopper_pearson(len(cases_flipped), len(by_case))
        result[name] = {
            'judgments_flipped': sum(done),
            'judgments': len(done),
            'cases_flipped': cases_flipped,
            'cases': len(by_case),
            'interval_by_case': [lo, hi],
        }
        print(
            f'{name}: {len(cases_flipped)}/{len(by_case)} cases switched to "answered" [{lo:.3f}, {hi:.3f}] '
            f'({sum(done)}/{len(done)} judgments); cases {cases_flipped}'
        )
    comparison = compare(flips['neutral_note'], flips['grader_note'], missing_as=None)
    result['grader_vs_neutral'] = str(comparison)
    print('grader note vs neutral note, paired by case:', comparison)
    result['new_calls'] = judge.new_calls
    (OUT / 'injection_refusal.json').write_text(json.dumps(result, indent=1))
    print(f'({judge.new_calls} new calls)')


if __name__ == '__main__':
    asyncio.run(main())
