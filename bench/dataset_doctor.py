"""The dataset doctor on Phoenix's own benchmark suites.

    uv run python bench/dataset_doctor.py

Each suite's cases (bench/phoenix_suites/suites.inputs.json, from js/benchmarks/evals-benchmarks)
with their labels (suites.json) and the suite's accuracy bar. Near-copy similarity 0.8 (word 3-gram
Jaccard). Every flagged pair is printed with both texts' first words so a person can decide; the
script decides nothing about whether a conflicting pair is a label error or a deliberate minimal
pair. Writes results/dataset_doctor.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_evidence._doctor import Example, diagnose  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'results' / 'dataset_doctor.json'


def main() -> None:
    suites = json.loads((HERE / 'phoenix_suites' / 'suites.json').read_text())['suites']
    inputs = json.loads((HERE / 'phoenix_suites' / 'suites.inputs.json').read_text())['inputs']
    report = {}
    for name, suite in suites.items():
        cases = inputs[name]
        examples = [
            Example(str(i), case, str(label)) for i, (case, label) in enumerate(zip(cases, suite['truth'], strict=True))
        ]
        bar = next(c['threshold'] for c in suite['criteria'] if c['annotationName'] == 'accuracy')
        d = diagnose(examples, threshold=bar)
        print(f'{name}: {d}')
        for a, b, s in d.conflicting + [p for p in d.near_copies if p not in d.conflicting]:
            tag = 'CONFLICT' if (a, b, s) in d.conflicting else 'near-copy'
            print(f'   {tag} {a} vs {b} (similarity {s}): labels {suite["truth"][int(a)]} / {suite["truth"][int(b)]}')
        report[name] = {'examples': d.examples, 'bar': bar, 'problems': d.problems(), 'exact_copies': d.exact_copies,
                        'near_copies': d.near_copies, 'conflicting': d.conflicting, 'labels': d.labels}  # fmt: skip
    OUT.write_text(json.dumps(report, indent=1, default=str))


if __name__ == '__main__':
    main()
