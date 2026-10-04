"""Planner floor: how far may a noisy uncertainty signal swing the inclusion probabilities?

    uv run python bench/planner_floor.py

Signal: one repeat's disagreement. Two populations: (a) judge probability p ~ Beta(0.5, 0.5), hard
label 1[p > 0.5], human y ~ Bernoulli(p), repeat = two Bernoulli(p) draws differ; (b) ppi_sim's
population with the repeat-flip rates measured on Codex (24% of wrong, 0.8% of right). Budget 100,
500 trials. Labels saved against uniform sampling at the same budget (width-squared ratio).
Writes results/planner_floor.json.
"""

import json
import random
import sys

sys.path.insert(0, '.')  # noqa: E402
from phoenix_evidence._ppi import corrected_rate, plan_labels

N = 2000


def go(signal, floor, budget=100, reps=500, seed=3, ppi_sim_pop=False):
    rng = random.Random(seed)
    widths = []
    cov = []
    for _ in range(reps):
        if ppi_sim_pop:
            y = []
            f = []
            u = []
            for _ in range(N):
                yy = int(rng.random() < 0.76)
                ff = int(rng.random() < (0.97 if yy else 0.35))
                u.append(float(rng.random() < (0.24 if ff != yy else 0.008)))
                y.append(float(yy))
                f.append(float(ff))
        else:
            p = [rng.betavariate(0.5, 0.5) for _ in range(N)]
            y = [float(rng.random() < q) for q in p]
            f = [float(q > 0.5) for q in p]
            u = [0.0] * N if signal == 'uniform' else [float((rng.random() < q) != (rng.random() < q)) for q in p]
        if signal == 'uniform':
            u = [0.0] * N
        ch, pi = plan_labels(u, budget, floor=floor, seed=rng.randrange(2**31))
        r = corrected_rate(f, {i: y[i] for i in ch}, pi)
        widths.append(r.interval[1] - r.interval[0])
        cov.append(r.interval[0] <= sum(y) / N <= r.interval[1])
    return sum(widths) / reps, sum(cov) / reps


OUT = {}
for pop in (False, True):
    base = go('uniform', 0.2, ppi_sim_pop=pop)[0]
    for fl in (0.05, 0.2, 0.5, 1.0, 2.0):
        w, c = go('repeat', fl, ppi_sim_pop=pop)
        OUT.setdefault('ppi_sim, measured rates' if pop else 'beta sampling', []).append(
            {'floor': fl, 'saved_vs_uniform': round((base / w) ** 2, 2), 'coverage': c}
        )
        print(pop, fl, round((base / w) ** 2, 2), c)

open('results/planner_floor.json', 'w').write(json.dumps(OUT, indent=1))
