"""How many independent judges are repeats and configurations of one model worth?

    uv run --extra phoenix python bench/effective_judges.py

Three judges on the 505 cases of Phoenix's suites that the label audit judged, all cached in
results/judgments: Codex gpt-5.6-luna with no reasoning (run 1 and run 2) and with low reasoning
(bench/canary_real.py). Truth: the suites' labels as shipped. Reports the correlation of their
errors, the effective number of judges, and majority-vote accuracy against the best single one.
Writes results/effective_judges.json.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import OUT, SUITES, CachedJudge, load_inputs  # noqa: E402
from label_audit import AUDIT  # noqa: E402

from phoenix_evidence._jury import jury  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> None:
    suites = json.loads((HERE / 'phoenix_suites' / 'suites.json').read_text())['suites']
    specs = {**AUDIT, **SUITES}
    rows: list[list[str | None]] = [[], [], []]
    truth: list[str] = []
    for name, spec in sorted(specs.items()):
        none, low = CachedJudge(name, None).cache, CachedJudge(f'{name}.low', None).cache
        for i, case in enumerate(load_inputs(f'{name}.eval.ts')):
            d = hashlib.sha256(json.dumps(spec['to_input'](case), sort_keys=True).encode()).hexdigest()
            first = none.get(f'{d}:0')
            if first is None or first['label'] is None or f'{d}:0' not in low:
                continue
            truth.append(str(suites[f'{name}.eval.ts']['truth'][i]))
            for row, cache, key in ((rows[0], none, f'{d}:0'), (rows[1], none, f'{d}:1'), (rows[2], low, f'{d}:0')):
                row.append(cache[key]['label'] if key in cache else None)
    result = {}
    for label, which in (('two runs, no reasoning', [0, 1]), ('no reasoning + low reasoning', [0, 2]),
                         ('all three', [0, 1, 2])):  # fmt: skip
        j = jury([rows[k] for k in which], truth)
        print(f'{label}: {j}')
        result[label] = {**vars(j), 'summary': str(j)}
    result['judges'] = ['codex:gpt-5.6-luna@none run 1', 'codex:gpt-5.6-luna@none run 2', 'codex:gpt-5.6-luna@low']
    (OUT / 'effective_judges.json').write_text(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
