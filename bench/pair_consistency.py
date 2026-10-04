"""Phoenix's minimal pairs, scored per pair: does the judge tell the two members apart?

    uv run python bench/pair_consistency.py

Pairs: the conflicting (near-)copies the dataset doctor found in completeness and faithfulness,
all read by hand as deliberate minimal pairs (results/dataset_doctor_review.md). Labels: the cached
judgments of the phoenix-evals evaluators on Codex (results/judgments, two runs each). Truth: the
suites' labels as shipped (the faithfulness moth pair is reversed in them; upstream/05 fixes it, so
it is also reported with the fix). Writes results/pair_consistency.json.
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

from phoenix_evidence._doctor import pair_accuracy  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> None:
    suites = json.loads((HERE / 'phoenix_suites' / 'suites.json').read_text())['suites']
    doctor = json.loads((OUT / 'dataset_doctor.json').read_text())
    specs = {**AUDIT, **SUITES}
    result = {}
    for name in ('completeness', 'faithfulness'):
        pairs = [(a, b) for a, b, _ in doctor[f'{name}.eval.ts']['conflicting']]
        truth = {str(i): str(t) for i, t in enumerate(suites[f'{name}.eval.ts']['truth'])}
        cache = CachedJudge(name, None).cache
        judged = {}
        for i, case in enumerate(load_inputs(f'{name}.eval.ts')):
            digest = hashlib.sha256(json.dumps(specs[name]['to_input'](case), sort_keys=True).encode()).hexdigest()
            judged[str(i)] = [cache[f'{digest}:{r}']['label'] for r in range(2) if f'{digest}:{r}' in cache]
        result[name] = pair_accuracy(pairs, truth, judged)
        print(name, result[name])
        if name == 'faithfulness':
            fixed = dict(truth)
            moth = [a for a, b in pairs if 'Indogrammodes' in json.dumps(load_inputs('faithfulness.eval.ts')[int(a)])]
            for a, b in pairs:
                if a in moth:
                    fixed[a], fixed[b] = truth[b], truth[a]
            result['faithfulness_with_upstream_05'] = pair_accuracy(pairs, fixed, judged)
            print('faithfulness with the moth pair fixed', result['faithfulness_with_upstream_05'])
    result['judge'] = 'phoenix-evals evaluators on codex:gpt-5.6-luna@none, two runs per case'
    (OUT / 'pair_consistency.json').write_text(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
