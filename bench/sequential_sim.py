"""Stop-when-decided comparisons: error rates under repeated looks, and examples saved.

    uv run python bench/sequential_sim.py

Two versions run on the same examples, one example at a time, checked after every batch of 10. On
each example the candidate agrees with the base 80% of the time; where they differ (20%), the
candidate is the better one with probability q (q = 0.5 is no difference). Up to 2,000 examples,
3,000 runs per setting.

Reported for the sequential test (`SequentialComparison`, three priors) and for the naive habit:
an exact two-sided sign test after every batch, stopping at the first p < 0.05. Measured: the
share of runs that declare a winner when there is none (must stay at or below 5%), the share that
declare the wrong winner, the share decided by 2,000, and the median examples to a decision. For
scale, the fixed-size exact sign test with 80% power at the same q (`examples_fixed_80`), found by
search with the same discordance. Writes results/sequential_sim.json.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_evidence._intervals import _binomial_cdf  # noqa: E402
from phoenix_evidence._sequential import log_evidence  # noqa: E402

DISCORDANT, MAX_N, BATCH, RUNS, ALPHA = 0.2, 2000, 10, 3000, 0.05
OUT = Path(__file__).resolve().parent.parent / 'results' / 'sequential_sim.json'


def sign_p(b: int, w: int) -> float:
    n = b + w
    if n == 0:
        return 1.0
    k = min(b, w)
    return min(1.0, 2 * _binomial_cdf(k, n, 0.5))


def run(q: float, seed: int, priors: list[float]) -> dict:
    rng = random.Random(seed)
    threshold = math.log(1 / ALPHA)
    results = {f'sequential a={a}': [] for a in priors} | {'naive sign test every batch': []}
    for _ in range(RUNS):
        b = w = 0
        decided: dict[str, tuple[int, str] | None] = dict.fromkeys(results)
        for n in range(1, MAX_N + 1):
            if rng.random() < DISCORDANT:
                if rng.random() < q:
                    b += 1
                else:
                    w += 1
            if n % BATCH:
                continue
            for a in priors:
                key = f'sequential a={a}'
                if decided[key] is None and log_evidence(b, w, a) >= threshold:
                    decided[key] = (n, 'better' if b > w else 'worse')
            key = 'naive sign test every batch'
            if decided[key] is None and sign_p(b, w) < ALPHA:
                decided[key] = (n, 'better' if b > w else 'worse')
            if all(v is not None for v in decided.values()):
                break
        for key, v in decided.items():
            results[key].append(v)
    out = {'q': q}
    for key, runs in results.items():
        hits = [r for r in runs if r is not None]
        row = {'decided_by_2000': round(len(hits) / RUNS, 4)}
        if q == 0.5:
            row['false_decision'] = row.pop('decided_by_2000')
        else:
            row['wrong_direction'] = round(sum(1 for r in hits if r[1] == 'worse') / RUNS, 4)
            right = [r[0] for r in hits if r[1] == 'better']
            row['median_examples'] = statistics.median(right) if right else None
        out[key] = row
    return out


def fixed_n_80(q: float) -> int | None:
    """Smallest n where an exact two-sided sign test at 0.05 has 80% power (by simulation-free sum)."""
    for n in range(10, 20001, 10):
        # discordant count D ~ Binomial(n, 0.2); given D, wins ~ Binomial(D, q). Normal approximation
        # for D's spread is enough for scale: use D = round(0.2 n).
        d = round(DISCORDANT * n)
        crit = next((k for k in range(d + 1) if 2 * (1 - _binomial_cdf(k - 1, d, 0.5)) < ALPHA), None)
        if crit is None:
            continue
        power = 1 - _binomial_cdf(crit - 1, d, q)
        if power >= 0.8:
            return n
    return None


def main() -> None:
    priors = [0.5, 2.0, 10.0]
    rows = []
    for k, q in enumerate([0.5, 0.6, 0.7, 0.8]):
        row = run(q, seed=k, priors=priors)
        if q != 0.5:
            row['examples_fixed_80'] = fixed_n_80(q)
        print(row, flush=True)
        rows.append(row)
    design = {'discordant': DISCORDANT, 'max_examples': MAX_N, 'look_every': BATCH, 'runs': RUNS, 'alpha': ALPHA}
    OUT.write_text(json.dumps({'design': design, 'rows': rows}, indent=1))


if __name__ == '__main__':
    main()
