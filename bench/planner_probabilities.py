"""Does a judge's probability make a better label planner than its repeat disagreement?

    uv run python bench/planner_probabilities.py

`plan_labels` sends humans to the traces the judge is least sure of. Two ways to know that:
repeat disagreement (judge each trace twice; did the label change?) and, when the judge gives one,
its probability p, as p(1 - p) or sqrt(p(1 - p)) (Neyman allocation: the gap's spread is
sqrt(p(1 - p)) when p is calibrated). The judge's value in the corrected rate is either its hard
label or p itself.

Population: 2000 traces, judge probability p ~ Beta(0.5, 0.5) (mostly confident), human verdict
y ~ Bernoulli(p) when calibrated, or Bernoulli(sigmoid(2.5 logit p)) when the judge is
underconfident, or Bernoulli(sigmoid(0.4 logit p)) when overconfident. Repeat disagreement: two
draws from Bernoulli(p) differ. Each design is drawn 1000 times at each budget. Reported: coverage
of the realised human pass rate, mean width, and labels saved against uniform sampling with the
hard label (the width-squared ratio, so 2.0 means half the labels for the same width).
Writes results/planner_probabilities.json.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_evidence._ppi import corrected_rate, plan_labels  # noqa: E402

N, REPS = 2000, 1000
OUT = Path(__file__).resolve().parent.parent / 'results' / 'planner_probabilities.json'


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def run(calibration: str, budget: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    slope = {'calibrated': 1.0, 'underconfident': 2.5, 'overconfident': 0.4}[calibration]
    designs: dict[str, list[tuple[bool, float]]] = {}
    for _ in range(REPS):
        p = [rng.betavariate(0.5, 0.5) for _ in range(N)]
        y = [float(rng.random() < sigmoid(slope * logit(q))) for q in p]
        truth = sum(y) / N
        hard = [float(q > 0.5) for q in p]
        repeat = [float((rng.random() < q) != (rng.random() < q)) for q in p]
        signals = {
            'uniform': [0.0] * N,
            'repeat disagreement': repeat,
            'p(1-p)': [q * (1 - q) * 4 for q in p],  # scaled to [0, 1] like the others
            'sqrt(p(1-p))': [math.sqrt(q * (1 - q)) * 2 for q in p],
        }
        for signal, u in signals.items():
            chosen, pi = plan_labels(u, budget, seed=rng.randrange(2**31))
            if not chosen:
                continue
            for value, judge in (('hard label', hard), ('probability', p)):
                r = corrected_rate(judge, {i: y[i] for i in chosen}, pi)
                lo, hi = r.interval
                designs.setdefault(f'{signal} / {value}', []).append((lo <= truth <= hi, hi - lo))
    base = sum(w for _, w in designs['uniform / hard label']) / len(designs['uniform / hard label'])
    rows = []
    for name, results in designs.items():
        width = sum(w for _, w in results) / len(results)
        rows.append({'calibration': calibration, 'budget': budget, 'design': name,
                     'coverage': round(sum(c for c, _ in results) / len(results), 4),
                     'width': round(width, 4), 'labels_saved_vs_uniform_hard': round((base / width) ** 2, 2)})  # fmt: skip
    return rows


def main() -> None:
    rows = []
    for k, (calibration, budget) in enumerate(
        [(c, b) for c in ('calibrated', 'underconfident', 'overconfident') for b in (50, 100, 200)]
    ):
        for row in run(calibration, budget, seed=k):
            print(row, flush=True)
            rows.append(row)
    OUT.write_text(json.dumps({'traces': N, 'reps': REPS, 'rows': rows}, indent=1))


if __name__ == '__main__':
    main()
