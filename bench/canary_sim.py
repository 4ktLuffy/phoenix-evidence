"""Does the drift canary keep its false-alarm rate under daily looks, and how fast does it catch drift?

    uv run python bench/canary_sim.py

A frozen set of 50 examples is re-scored once a day for 90 days. Examples differ in how often the
judge flips on them (flip rates drawn from Beta(0.5, 9.5), mean 0.05 = the allowed rate, the worst
case for the null). No drift: the false-alarm rate over the 90 days must stay at or below alpha =
0.05. The negative control is the naive check a team would write: every day, an exact one-sided
binomial test of all flips so far against the allowed rate at 5%; it must exceed alpha, or the
simulation could not tell the two apart. Drift: from day 30, every example's flip rate rises by
`shift`; measured: the share of runs that alarm by day 90, and the median days from drift to alarm.
Also: a null where every example flips at exactly the allowed rate, and the uniform prior for
comparison with the default one. Writes results/canary_sim.json.
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_evidence._canary import canary  # noqa: E402
from phoenix_evidence._intervals import _binomial_cdf  # noqa: E402

N, DAYS, ALLOWED, ALPHA, RUNS, DRIFT_DAY = 50, 90, 0.05, 0.05, 2000, 30
OUT = Path(__file__).resolve().parent.parent / 'results' / 'canary_sim.json'


def naive_alarm_day(daily: list[int]) -> int | None:
    flips = 0
    for day, k in enumerate(daily):
        flips += k
        n = N * (day + 1)
        if 1 - _binomial_cdf(flips - 1, n, ALLOWED) <= ALPHA:  # P(X >= flips) under the allowed rate
            return day
    return None


def run(shift: float, seed: int, prior: tuple[float, float] | None = None, same_rates: bool = False) -> dict:
    rng = random.Random(seed)
    canary_days, naive_days = [], []
    for _ in range(RUNS):
        rates = [ALLOWED] * N if same_rates else [rng.betavariate(0.5, 9.5) for _ in range(N)]
        mean = sum(rates) / N
        rates = [min(r * ALLOWED / mean, 1.0) for r in rates]  # average exactly the allowed rate
        daily = []
        for day in range(DAYS):
            bump = shift if day >= DRIFT_DAY else 0.0
            daily.append(sum(rng.random() < min(r + bump, 1.0) for r in rates))
        report = canary([(str(d), N, k) for d, k in enumerate(daily)], ALLOWED, ALPHA, prior)
        alarm = report.first_alarm
        canary_days.append(int(alarm.label) if alarm else None)
        naive_days.append(naive_alarm_day(daily))

    def summary(days: list[int | None]) -> dict:
        hits = [d for d in days if d is not None]
        out = {'alarm_by_day_90': round(len(hits) / RUNS, 4)}
        if shift:
            late = [d - DRIFT_DAY for d in hits if d >= DRIFT_DAY]
            out['false_alarm_before_drift'] = round(sum(1 for d in hits if d < DRIFT_DAY) / RUNS, 4)
            out['median_days_to_alarm'] = statistics.median(late) if late else None
        return out

    return {
        'shift': shift,
        'prior': prior or 'default',
        'same_rates': same_rates,
        'canary': summary(canary_days),
        'naive_daily_test': summary(naive_days),
    }


def main() -> None:
    rows = [run(shift, seed) for seed, shift in enumerate([0.0, 0.03, 0.05, 0.10, 0.20])]
    rows.append(run(0.0, 10, same_rates=True))  # every example flips at exactly the allowed rate
    rows += [run(shift, 20 + seed, prior=(1.0, 1.0)) for seed, shift in enumerate([0.0, 0.03, 0.05])]  # uniform prior
    for r in rows:
        print(r, flush=True)
    OUT.write_text(json.dumps({
        'design': {'examples_per_day': N, 'days': DAYS, 'allowed': ALLOWED, 'alpha': ALPHA, 'runs': RUNS,
                   'drift_day': DRIFT_DAY, 'example_flip_rates': 'Beta(0.5, 9.5) scaled to mean 0.05'},
        'rows': rows,
    }, indent=1))  # fmt: skip


if __name__ == '__main__':
    main()
