# Independent adversarial review 3 (partial: Codex ran out of credits)

2026-10-04. Reviewer: Codex (codex-cli 0.153.4, default model), brief in
[`review_3_probes/BRIEF.md`](review_3_probes/BRIEF.md). Codex reran the tests, wrote probes and
reproduced defects, then stopped with "Your workspace is out of credits" before writing its report
(79,040 tokens used). This file records what it found, in its own words where it gave them, and
the outputs of its probe scripts. Three of the scripts (`final_checks.py`, `probes.py`,
`resume_probe.py`) were written by Codex and run by us after it stopped; they make no model calls.
The review was completed by Claude Sonnet at low effort, per the project's rule for when Codex runs
out: [`sonnet_review_3.md`](sonnet_review_3.md). Our response to both: [`response_3.md`](response_3.md).

## Codex's own progress notes (verbatim)

> The package tests pass: 84 passed, 2 skipped. The canary's heterogeneous-rate argument works for
> independent, complete batches whose conditional average flip rate is bounded. I'm checking whether
> the adapter enforces those conditions, and probing numerical stability, price-search rounding, and
> annotation deletion.

> I've reproduced three concrete defects: the canary's beta tail underflows after 15,000 zero-flip
> observations; the price search returns 62 labels when 41 already meets the target; and
> complementary judges crash the jury calculation. All three patches apply to pristine commit
> `9212a42`. I'm now testing whether patch 07 deletes human labels and whether replaying a canary
> check can produce a false alarm.

## Probe outputs (on the code as it was at review time)

`offline_checks.py` (run by Codex):

```text
ADAPTER changed Look(label='changed', checks=100, flips=0, ...)            # every label A -> B, same score: 0 flips
ADAPTER partial Look(label='partial', checks=5, flips=5, ..., evidence=199.3, drifted=True)
ADAPTER missing Look(label='missing', checks=1, flips=0, ...)
REPLAY Look(label='oneflip', checks=10, flips=1, total_checks=190, total_flips=19, evidence=20.8, drifted=True)
PRICE Plan(name='human labels only', labels=62, ...) width41 0.08604 width62 0.08621
MATCH dataset_doctor True / MATCH pair_consistency True / MATCH effective_judges True
E2E 40 ['codex:gpt-5.6-luna@low']
CANARY_SIM {'alarm_by_day_90': 0.0155} / {'alarm_by_day_90': 0.017}
```

`probes.py` (written by Codex, run by us after the canary tail fix, so `TAIL` shows the fixed values
against Codex's closed form log(19 / (n + 19)) for zero flips; before the fix they were -inf from
n = 15,000):

```text
TAIL [(1000, -3.98214, -3.98214), (10000, -6.26780, -6.26780), (15000, -6.67263, -6.67263), (100000, -8.56868, -8.56868)]
PARTIAL_NULL 5 flips in 5 re-scored examples over 1 checks ... DRIFT
MISSING (1, 0)
JURY ZeroDivisionError division by zero
PAIR {'pairs': 1, 'pair_judgments': 1, 'case_accuracy': 0.667, 'pair_accuracy': 1.0, ...}
DOCTOR 2 examples: 1 example is an exact copy of another ...; 1 pair of (near-)copies with different labels   # '1.0' vs '1,0'
PRICE {'p': 0.01, 'target': 0.08755, 'got': 62, 'expected': 41, ...}
CLIPPED_BIAS 0.10997 truth 0 empty_probability 0.00098
```

`resume_probe.py` (written by Codex, run by us on patch 07 as it was): the create-run route, on an
errored run with a HUMAN and a CODE annotation, replaced by a successful run:

```text
BEFORE [('human_label', 'HUMAN'), ('exact', 'CODE')]
AFTER []
OUTPUT {'task_output': 'B'}
```

`final_checks.py` (written by Codex, run by us): the action's shell body with an injection payload
in every input:

```text
ACTION 0 injected False literal payload occurrences 4
NAME baseline (123)
PRICE_HEADLINE 402 107 0.0678
REAL_CANARY_RECOMPUTE 0.0306 False
FLOOR 0.1333 0.2667 2.0
PPI_PROB uniform / hard label: coverage 0.985, width 0.1718; sqrt(p(1-p)) / probability: coverage 0.985, width 0.1404, saved 1.5
```

## Defects, as reproduced

1. Canary: the Beta tail underflows after 15,000 clean checks; the evidence reads exactly 0.
2. Price: bisection on Clopper-Pearson widths, which are not monotone in n: 62 labels where 41 works.
3. Jury: perfectly anti-correlated errors divide by zero.
4. Canary adapter: compares scores, so a judge that changed every label but not the score shows no flips.
5. Canary adapter: a check that re-scores a hand-picked subset (5 of 100, all flipped) alarms at once.
6. Canary adapter: passing one check experiment many times accumulates its noise into a false alarm.
7. Doctor: '1.0' and '1,0' normalise to the same text.
8. Pair accuracy: uneven repetitions give a case accuracy over a different set than the pair accuracy.
9. Corrected rate: the clipped estimate is biased near 0 (0.11 against a truth of 0).
10. Patch 07 deletes HUMAN annotations on the replaced run along with evaluator ones.

Confirmed by Codex: tests pass; the canary argument holds for independent, complete batches; the
saved doctor, pair and jury results reproduce exactly; patches 05, 06 and 07 apply to 9212a42; the
action is not injectable; the e2e relabel is in place; the canary false-alarm figures reproduce.
