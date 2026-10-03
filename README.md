# phoenix-evidence

**Margins of error for the numbers Arize Phoenix shows, and a verdict you can gate on.**

Phoenix tells you a judge scored 0.81, version B is 4 points better, a suite passed its 0.7 gate.
It does not tell you whether 16 cases can show any of that. This package does, on top of Phoenix
(it does not fork it or replace its UI):

- **Certify a judge** against human labels: agreement with a margin of error, controls a sound
  judge must survive (a reformatted answer, a note to the grader claiming the answer is good, an
  answer to a different question), consistency over repeats, and a verdict: TRUSTWORTHY,
  NOT_TRUSTWORTHY or NOT_ENOUGH_EVIDENCE, with how many more labels would likely settle it.
- **Gate CI on evidence**: a pytest plugin for Phoenix's pytest integration that decides each
  suite on an interval, counts crashed runs as failures, and counts repetitions of one example
  once.
- **Compare two experiments honestly**: paired on shared examples, crashes scored instead of
  dropped, with the smallest difference the dataset can detect and the size it would need.
- **Run Phoenix's own evaluators on Codex** (`LLM(provider='codex')`), no API key.

What it found in Phoenix itself, with reproductions and fixes: [FINDINGS.md](FINDINGS.md).

```python
from phoenix_evidence import Case, certify, grader_note, reformat, decide_rate, compare

cert = await certify(judge, cases, controls=[reformat(), grader_note('correct')], repeats=2)
print(cert)  # a verdict, each check on its interval; real ones in FINDINGS.md

decide_rate([[True]] * 13 + [[False]] * 3, threshold=0.7)
# NOT_ENOUGH_EVIDENCE: 0.812 [0.544, 0.960] vs 0.7 on 16 examples   (Phoenix's gate says PASS)

compare(baseline_scores, candidate_scores)
# NO_DETECTABLE_DIFFERENCE: B-A = +0.040 [+0.000, +0.100], p = 0.5; ... needed: 194
```

```python
@pytest.mark.phoenix(dataset='refunds', repetitions=3)
@pytest.mark.evidence(threshold=0.8)
@pytest.mark.parametrize('case', CASES)
def test_refund(case): ...
```

`pytest --evidence-strict` fails the run on NOT_ENOUGH_EVIDENCE as well as FAIL; without it, a
suite too small to decide is reported but does not fail CI. Works with `pytest -n` (xdist): the
workers' outcomes are decided together on the controller.

## How the guarantees were checked

`bench/coverage.py` draws data where the truth is known and counts how often each method is
wrong; `results/coverage.txt` has the numbers. Negative controls run the same draws through the
naive method and must come out red. These are simulations on the distributions listed in the
script (sizes 16-150, pass rates 0.7-0.9, examples that differ and that do not), not proofs for
every distribution.

| Promise | Measured | Naive method on the same draws |
|---|---|---|
| A gate passes a judge 1 point below the bar at most 2.5% of the time | at most 1.9% | 34-57% |
| A comparison of two identical versions reports a difference at most 5% of the time | at most 4.6% | "5 points better" on two dashboards: 12-83% |
| Pass-rate intervals with repeated judgments cover the truth 95% of the time | 99.7-100% | 78-96% |
| Kappa's lower bound sits above the true kappa at most 2.5% of the time | at most 1.8% | |

What is weaker, and said here rather than hidden:

- the comparison's interval on the size of a difference is a bootstrap and is descriptive; it
  covered the truth 89-96% of the time (the decision itself comes from the exact test);
- kappa's two-sided interval covered 94-99% (the lower bound, used to certify, held);
- the comparison's test is exact when the two versions are interchangeable on each example (no
  difference at all), not for every pair of versions whose means happen to be equal;
- intervals assume examples are independent of each other; repetitions of one example are not
  treated as new examples, so the repeated-judgment interval is conservative on purpose (an
  earlier, tighter version was measured at 90% coverage and replaced);
- sample-size planning uses the normal approximation for paired proportions.

An independent review by a second model (Codex), which reran the code and tried to break each
claim, is in [`results/review/codex_review.md`](results/review/codex_review.md); every bug it
found has a test.

## Status

Work in progress. Not affiliated with Arize.
