"""How much does planning by repeat disagreement save, with the rates measured on a real judge?

    uv run python bench/planner_sensitivity.py

bench/ppi_sim.py assumed the judge changes its answer on a repeat for 60% of the traces it gets
wrong and 8% of those it gets right. Measured on Codex judging Phoenix's benchmark suites
(results/judgments, two runs per case, against the suites' labels; 505 cases): 6 of 25 wrong
(24%) and 4 of 480 right (0.8%). This reruns ppi_sim's population with each pair of rates and
reports, at each budget, the width of the planned interval against the uniform corrected interval
(the planner's own gain) and against human labels alone (the whole gain), as labels saved
(width-squared ratio). Serial, 400 trials per cell. Writes results/planner_sensitivity.json.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ppi_sim  # noqa: E402

from phoenix_evidence._intervals import clopper_pearson  # noqa: E402
from phoenix_evidence._ppi import corrected_rate, plan_labels  # noqa: E402

RATES = {'assumed in ppi_sim (60% / 8%)': (0.60, 0.08), 'measured on Codex (24% / 0.8%)': (0.24, 0.008)}


def cell(budget: int, seed: int) -> dict[str, float]:
    rng = random.Random(seed)
    w = {'human': [], 'uniform': [], 'planned': []}
    cover = {'planned': []}
    for t in range(400):
        y, f, u = ppi_sim.population(rng)
        truth = sum(y) / ppi_sim.N
        sample = rng.sample(range(ppi_sim.N), budget)
        lo, hi = clopper_pearson(sum(y[i] for i in sample), budget)
        w['human'].append(hi - lo)
        r = corrected_rate(f, {i: y[i] for i in sample})
        w['uniform'].append(r.interval[1] - r.interval[0])
        chosen, pi = plan_labels(u, budget, seed=seed * 1000 + t)
        r = corrected_rate(f, {i: y[i] for i in chosen}, inclusion=pi)
        w['planned'].append(r.interval[1] - r.interval[0])
        cover['planned'].append(r.interval[0] <= truth <= r.interval[1])
    mean = {k: sum(v) / len(v) for k, v in w.items()}
    return {'budget': budget, 'planned_coverage': round(sum(cover['planned']) / 400, 3),
            'saved_vs_uniform_corrected': round((mean['uniform'] / mean['planned']) ** 2, 2),
            'saved_vs_human_only': round((mean['human'] / mean['planned']) ** 2, 2)}  # fmt: skip


def main() -> None:
    out = {}
    for name, (wrong, right) in RATES.items():
        ppi_sim.UNSURE_IF_WRONG, ppi_sim.UNSURE_IF_RIGHT = wrong, right
        out[name] = [cell(b, 9000 + b) for b in (80, 160, 320)]
        for row in out[name]:
            print(name, row, flush=True)
    path = Path(__file__).resolve().parent.parent / 'results' / 'planner_sensitivity.json'
    path.write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
