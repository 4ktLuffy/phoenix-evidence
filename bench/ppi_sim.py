"""Does the corrected pass rate keep its promise, and how many human labels does planning save? No model calls.

    uv run python bench/ppi_sim.py      # writes results/ppi_sim.json and .txt

Each trial draws 2,000 production traces. Humans would pass 76% of them (each trace passes with
probability 0.76). The judge passes 97% of what humans pass and 35% of what they fail, so it
reports about 82%, and it is unsure (changes its answer on a repeat) on 60% of the traces it gets
wrong and 8% of those it gets right. With the same number of human labels, four estimates of the
human pass rate over the 2,000:

- judge alone: the judge's rate with a binomial interval (the negative control: it must miss);
- human labels alone: a uniform random sample, exact interval;
- corrected, uniform sample (PPI++);
- corrected, planned sample: labels drawn more often where the judge was unsure (active PPI).

Reports how often each interval covers the truth and how wide it is, and how many uniform human
labels would give the planned interval's width.
"""

from __future__ import annotations

import json
import random
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_evidence._intervals import clopper_pearson, wilson  # noqa: E402
from phoenix_evidence._ppi import corrected_rate, plan_labels  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / 'results'
N, P_TRUE, PASS_IF_PASS, PASS_IF_FAIL = 2000, 0.76, 0.97, 0.35
UNSURE_IF_WRONG, UNSURE_IF_RIGHT = 0.60, 0.08
TRIALS = 400


def population(rng: random.Random) -> tuple[list[int], list[int], list[float]]:
    human, judge, unsure = [], [], []
    for _ in range(N):
        y = int(rng.random() < P_TRUE)
        f = int(rng.random() < (PASS_IF_PASS if y else PASS_IF_FAIL))
        unsure.append(float(rng.random() < (UNSURE_IF_WRONG if f != y else UNSURE_IF_RIGHT)))
        human.append(y)
        judge.append(f)
    return human, judge, unsure


def one(args: tuple[int, int]) -> dict[str, list[float]]:
    budget, seed = args
    rng = random.Random(seed)
    out: dict[str, list[float]] = {k: [] for k in ('judge', 'human', 'ppi', 'active')}
    widths: dict[str, list[float]] = {k: [] for k in out}
    for t in range(TRIALS):
        y, f, u = population(rng)
        truth = sum(y) / N
        lo, hi = wilson(sum(f), N)
        out['judge'].append(lo <= truth <= hi)
        widths['judge'].append(hi - lo)
        sample = rng.sample(range(N), budget)
        lo, hi = clopper_pearson(sum(y[i] for i in sample), budget)
        out['human'].append(lo <= truth <= hi)
        widths['human'].append(hi - lo)
        r = corrected_rate(f, {i: y[i] for i in sample})
        out['ppi'].append(r.interval[0] <= truth <= r.interval[1])
        widths['ppi'].append(r.interval[1] - r.interval[0])
        chosen, pi = plan_labels(u, budget, seed=seed * 1000 + t)
        if not chosen:
            continue
        r = corrected_rate(f, {i: y[i] for i in chosen}, inclusion=pi)
        out['active'].append(r.interval[0] <= truth <= r.interval[1])
        widths['active'].append(r.interval[1] - r.interval[0])
    return {
        'budget': budget,
        **{f'{k}_coverage': sum(v) / len(v) for k, v in out.items()},
        **{f'{k}_width': sum(v) / len(v) for k, v in widths.items()},
    }


def main() -> None:
    budgets = [40, 80, 160, 320]
    with Pool() as pool:
        rows = pool.map(one, [(b, 7000 + b) for b in budgets])
    # Uniform human labels needed for the planned interval's width: width scales as 1/sqrt(n).
    for r in rows:
        r['human_labels_for_same_width'] = round(r['budget'] * (r['human_width'] / r['active_width']) ** 2)
    OUT.mkdir(exist_ok=True)
    (OUT / 'ppi_sim.json').write_text(json.dumps(rows, indent=1))
    keys = list(rows[0])
    lines = [' | '.join(keys)] + [
        ' | '.join(f'{r[k]:.3f}' if isinstance(r[k], float) else str(r[k]) for k in keys) for r in rows
    ]
    (OUT / 'ppi_sim.txt').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
