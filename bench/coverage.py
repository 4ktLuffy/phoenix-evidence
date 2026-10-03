"""Does every interval and test in phoenix_evidence keep its promise? Simulated, no model calls.

    uv run python bench/coverage.py            # writes results/coverage.json and .txt

Each check draws data where the truth is known, then counts how often the method is wrong.
Negative controls run the same draws through the naive method Phoenix-style gates use (repetitions
treated as independent, a point estimate against the bar) and must come out red, or the
simulation could not detect a broken method.
"""

from __future__ import annotations

import json
import random
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_evidence import agreement, compare, decide_rate, rate_interval, wilson  # noqa: E402
from phoenix_evidence._agreement import cohen_kappa  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / 'results'
TRIALS = 2000


def draw_examples(rng: random.Random, n: int, reps: int, p: float, concentration: float) -> list[list[bool]]:
    """Each example has its own pass probability ~ Beta with mean p; reps are judged at that probability.

    Lower `concentration` means examples differ more, so repetitions of one example are more alike.
    """
    if concentration == float('inf'):
        return [[rng.random() < p for _ in range(reps)] for _ in range(n)]
    a, b = p * concentration, (1 - p) * concentration
    return [[rng.random() < q for _ in range(reps)] for q in (rng.betavariate(a, b) for _ in range(n))]


def rate_coverage(args: tuple[int, int, float, float, int]) -> dict[str, float]:
    n, reps, p, conc, seed = args
    rng = random.Random(seed)
    ours = naive = 0
    for _ in range(TRIALS):
        ex = draw_examples(rng, n, reps, p, conc)
        lo, hi = rate_interval(ex)
        ours += lo <= p <= hi
        flat = [x for e in ex for x in e]
        lo, hi = wilson(sum(flat), len(flat))
        naive += lo <= p <= hi
    return {'n': n, 'reps': reps, 'p': p, 'concentration': conc, 'ours': ours / TRIALS, 'naive_iid': naive / TRIALS}


def false_pass(args: tuple[int, int, float, float, int]) -> dict[str, float]:
    """True accuracy just below the bar: every PASS is wrong. Promise: at most 2.5%."""
    n, reps, bar, conc, seed = args
    rng = random.Random(seed)
    p = bar - 0.01
    ours = point = 0
    for _ in range(TRIALS):
        ex = draw_examples(rng, n, reps, p, conc)
        ours += decide_rate(ex, bar).verdict.value == 'PASS'
        flat = [x for e in ex for x in e]
        point += sum(flat) / len(flat) >= bar
    return {'n': n, 'reps': reps, 'bar': bar, 'true': p, 'ours_false_pass': ours / TRIALS,
            'point_estimate_false_pass': point / TRIALS}  # fmt: skip


def compare_null(args: tuple[int, int, float, float, int]) -> dict[str, float]:
    """A and B identical in distribution: every detected difference is a false alarm. Promise: 5%."""
    n, reps, p, conc, seed = args
    rng = random.Random(seed)
    alarms = covered = naive = 0
    trials = TRIALS // 4
    for t in range(trials):
        qs = [rng.betavariate(p * conc, (1 - p) * conc) for _ in range(n)]
        a = {str(i): [rng.random() < q for _ in range(reps)] for i, q in enumerate(qs)}
        b = {str(i): [rng.random() < q for _ in range(reps)] for i, q in enumerate(qs)}
        c = compare(a, b, seed=t, bootstrap=1000)
        alarms += c.direction.value != 'NO_DETECTABLE_DIFFERENCE'
        covered += c.interval[0] <= 0 <= c.interval[1]
        ra = sum(x for v in a.values() for x in v) / (n * reps)
        rb = sum(x for v in b.values() for x in v) / (n * reps)
        naive += abs(rb - ra) >= 0.05  # "5 points better" read off two dashboards
    return {'n': n, 'reps': reps, 'p': p, 'false_alarm': alarms / trials, 'ci_covers_zero': covered / trials,
            'naive_5pt_difference': naive / trials}  # fmt: skip


def compare_power(args: tuple[int, float, float, int]) -> dict[str, float]:
    """B really is better by `delta` on a share of examples: how often is it detected?"""
    n, p, delta, seed = args
    rng = random.Random(seed)
    hits = covered = 0
    trials = TRIALS // 4
    for t in range(trials):
        a = {str(i): [rng.random() < p] for i in range(n)}
        b = {k: [v[0] or rng.random() < delta / (1 - p)] for k, v in a.items()}
        c = compare(a, b, seed=t, bootstrap=1000)
        hits += c.direction.value == 'B_BETTER'
        covered += c.interval[0] <= delta <= c.interval[1]
    return {'n': n, 'p': p, 'true_delta': delta, 'detected': hits / trials, 'ci_covers_truth': covered / trials}


def population_kappa(p_pass: float, flip: float) -> float:
    judge_pass = p_pass * (1 - flip) + (1 - p_pass) * flip
    chance = p_pass * judge_pass + (1 - p_pass) * (1 - judge_pass)
    return ((1 - flip) - chance) / (1 - chance)


def kappa_coverage(args: tuple[int, float, float, int]) -> dict[str, float]:
    """A judge that flips each human label with probability `flip`; its kappa is known exactly."""
    n, p_pass, flip, seed = args
    rng = random.Random(seed)
    truth = population_kappa(p_pass, flip)
    covered = above = trials = 0
    for _ in range(TRIALS // 4):
        by_example = []
        for _ in range(n):
            h = 'pass' if rng.random() < p_pass else 'fail'
            j = h if rng.random() >= flip else ('fail' if h == 'pass' else 'pass')
            by_example.append([(h, j)])
        if cohen_kappa([p for e in by_example for p in e]) is None:
            continue
        trials += 1
        lo, hi = agreement(by_example, resamples=500, seed=seed).kappa_interval
        covered += lo <= truth <= hi
        above += lo > truth
    return {'n': n, 'p_pass': p_pass, 'flip': flip, 'true_kappa': round(truth, 3),
            'coverage': covered / max(trials, 1), 'lower_bound_above_truth': above / max(trials, 1)}  # fmt: skip


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rate_jobs = [(n, reps, p, conc, 1000 + i)
                 for i, (n, reps, p, conc) in enumerate(
                     (n, reps, p, conc) for n in (16, 40, 80) for reps in (1, 3, 5) for p in (0.7, 0.9)
                     for conc in (float('inf'), 2.0))]  # fmt: skip
    gate_jobs = [(n, reps, bar, 2.0, 2000 + i) for i, (n, reps, bar) in enumerate(
        (n, reps, bar) for n in (16, 40, 150) for reps in (1, 3) for bar in (0.7, 0.8, 0.9))]  # fmt: skip
    null_jobs = [
        (n, reps, 0.7, 2.0, 3000 + i) for i, (n, reps) in enumerate((n, r) for n in (16, 40, 100) for r in (1, 3))
    ]
    power_jobs = [(n, 0.7, 0.10, 4000 + i) for i, n in enumerate((40, 100, 200, 400))]
    kappa_jobs = [(n, p, f, 5000 + i) for i, (n, p, f) in enumerate(
        (n, p, f) for n in (20, 40, 100) for p in (0.5, 0.85) for f in (0.05, 0.15))]  # fmt: skip
    with Pool() as pool:
        results = {
            'rate_interval_coverage (promise >= 0.95)': pool.map(rate_coverage, rate_jobs),
            'gate_false_pass_just_below_bar (promise <= 0.025)': pool.map(false_pass, gate_jobs),
            'compare_under_null (promise false_alarm <= 0.05)': pool.map(compare_null, null_jobs),
            'compare_power_and_coverage': pool.map(compare_power, power_jobs),
            'kappa_interval_coverage (target >= 0.95)': pool.map(kappa_coverage, kappa_jobs),
        }
    (OUT / 'coverage.json').write_text(json.dumps(results, indent=1))
    lines = []
    for title, rows in results.items():
        lines.append(f'\n## {title}')
        keys = list(rows[0])
        lines.append(' | '.join(keys))
        for r in rows:
            lines.append(' | '.join(f'{r[k]:.3f}' if isinstance(r[k], float) else str(r[k]) for k in keys))
    text = '\n'.join(lines)
    (OUT / 'coverage.txt').write_text(text.strip() + '\n')
    print(text)


if __name__ == '__main__':
    main()
