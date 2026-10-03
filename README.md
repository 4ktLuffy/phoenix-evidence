# phoenix-evidence

**Is version B really better? Can this judge be trusted? Can this dataset decide anything?**
Answers for [Arize Phoenix](https://github.com/Arize-ai/phoenix) users, with margins of error,
against your own Phoenix server. It sits on top of Phoenix (no fork) and writes back into it.

![Phoenix's compare page: a version that crashed on 10% of questions shows as +14.49%](results/screenshots/phoenix_compare_fragile.jpg)

*Phoenix's own compare page, on a version that crashed on 10 of 120 questions: Phoenix averages
the runs that finished and shows **+14.49%**. `phoenix-evidence compare` scores the crashes and
says what happened: no detectable gain (+0.042, p = 0.06), and a significant regression in task
errors. The cost cards read "+0%" for values that do not exist.*

## Every day, from a shell or CI

```bash
pip install "phoenix-evidence[phoenix] @ git+https://github.com/4ktLuffy/phoenix-evidence"
export PHOENIX_BASE_URL=http://localhost:6006   # and PHOENIX_API_KEY if your server needs one
```

**Is the candidate experiment really better than the baseline?** Paired on the examples both ran,
every evaluator at once (Holm-corrected), a run with no score counted as the worst score seen,
and how many examples it would take to tell:

```text
$ phoenix-evidence compare <baseline-experiment-id> <candidate-experiment-id> --fail-on-regression
| metric      | base  | candidate | difference [95%]        | p       | verdict                  | smallest detectable | examples needed |
| exact_match | 0.842 | 0.883     | +0.042 [+0.008, +0.083] | 0.0625  | no detectable difference | none at this size   | 186             |
| task_error  | 0.000 | 0.083     | +0.083 [+0.033, +0.133] | 0.00195 | worse                    | 0.073               | 92              |
regressions: task_error; improvements: none shown          (exit 1)
```

In GitHub Actions the table also goes to the job summary.

**Can my judge be trusted, against the human feedback already in Phoenix?** Pairs each span's
HUMAN label with the judge's label of the same name, decides agreement on an interval, and lists
the spans where they disagree:

```text
$ phoenix-evidence certify-feedback support-bot helpfulness
NOT_ENOUGH_EVIDENCE: judge 'helpfulness' vs human feedback in 'support-bot'
  60 spans carry both labels; 60 have a human label, 60 a judge label
  accuracy 0.87 [0.75, 0.94]
  kappa 0.71 [0.47, 0.89]
  about 268 spans with both labels would likely settle it
  8 spans where judge and human disagree (first 10): ...
```

**Can this labelled dataset decide anything about a judge, before you run one?**

```text
$ phoenix-evidence audit "refusal benchmark" --threshold 0.7
refusal benchmark: 40 labelled examples {'refused': 23, 'answered': 17}, bar 0.7
  to pass on an interval a judge needs 34/40 correct
  examples for a 75% judge to pass 80% of the time: 662
```

**What would humans say the pass rate is, from a judge that scores everything and a few human
labels?** `plan-labels` picks which judged spans humans should label (more often where the
judge's runs disagree) and puts them in a Phoenix dataset linked to the spans; once they are
labelled, `corrected-rate` combines both. In simulation it gives the interval that random human
labelling would need 1.7 to 2.4 times as many labels for, at 80 to 320 labels ([FINDINGS §11](FINDINGS.md)).

```text
$ phoenix-evidence plan-labels support-bot helpfulness --budget 150 --out plan.json
155 of 5000 judged spans chosen for human labels (317 spans where the judge was unsure are favoured)
$ phoenix-evidence corrected-rate plan.json --pass-label helpful
  pass rate ('helpful'): 0.744 [0.674, 0.813] from 155 human labels on 5000 traces; the judge alone says 0.700;
  the human labels alone give [0.634, 0.958]
```

`certify-feedback --export-disagreements` saves the spans where judge and human disagree as a
Phoenix dataset, ready for tuning the evaluator. In Python, `switch_impact(old, new, ...)` says
what would change before you swap judges: how many verdicts flip, how the pass rate moves, and
which judge agrees with humans more.

Full output of all three against a live Phoenix: [`results/cli_demo.txt`](results/cli_demo.txt)
(`bench/cli_demo.py` rebuilds it).

**Gate a pytest suite on evidence, not on every case or a bare average.** With Phoenix's
pytest plugin, add one marker:

```python
@pytest.mark.phoenix(dataset='refunds', repetitions=3)
@pytest.mark.evidence(threshold=0.8)
@pytest.mark.parametrize('case', CASES)
def test_refund(case): ...
```

Each suite is decided once, on an exact interval: PASS, FAIL (CI fails) or NOT_ENOUGH_EVIDENCE
(reported; CI fails with `--evidence-strict`). A failing case counts toward the suite instead of
failing CI on its own (`soft=False` restores that); a crash counts as a failure; repetitions of
one example count once; it works with `pytest -n`. Phoenix's own plugin still records every
case's real outcome (`bench/gate_alongside_phoenix.py` checks it against a live server).

## Certify a judge before you gate on it

```python
from phoenix_evidence import Case, certify, grader_note, reformat, swapped_answer
from phoenix_evidence.phoenix import write_certificate

cert = await certify(
    judge, cases, controls=[reformat(), grader_note('correct'), swapped_answer('incorrect')], repeats=2
)
print(cert)  # TRUSTWORTHY / NOT_TRUSTWORTHY / NOT_ENOUGH_EVIDENCE, each check on its interval
cert.label_review()  # examples where the judge consistently disagrees with the label: re-check these
write_certificate(client, cert, cases, dataset_name='refusal benchmark')  # into Phoenix, as an experiment
```

A certificate checks agreement with human labels (kappa and balanced accuracy, by example),
consistency over repeats, and controls a sound judge must survive: a reformatted answer, a note
to the grader claiming the answer is good (prompt injection), an answer to a different question.
Any Phoenix evaluator works as the judge; `import phoenix_evidence.codex` adds
`LLM(provider='codex')` to run them on the Codex CLI with no API key.

## Inside Phoenix itself

The same evidence on Phoenix's own compare page, as a working branch of Phoenix
([`upstream/04-phoenix-with-evidence-branch.patch`](upstream/04-phoenix-with-evidence-branch.patch)):
a GraphQL field and one line under each compare value. An interval-based acceptance criterion for
Phoenix's vitest harness is [`upstream/03`](upstream/03-interval-acceptance-criteria.patch).

![Phoenix's compare page with the evidence line](results/screenshots/phoenix_with_evidence.jpg)

## What it found in Phoenix

On Phoenix's own code and benchmarks ([FINDINGS.md](FINDINGS.md), each with a reproduction; a one-page summary is [`docs/findings.html`](docs/findings.html), built from the result files by `bench/build_findings_page.py`):

1. The experiment compare page reports regressions between identical experiments (fix and test in
   [`upstream/`](upstream/)), and shows "+0%" for changes that do not exist (fix and test).
2. Human feedback on a span overwrites the judge label it corrects (through the API, and in the
   UI's annotation panel), or is averaged with it into a number neither gave (0.25 where the judge
   said 1.0 and the human 0.0).
3. Re-judging 505 benchmark cases twice and reading every consistent disagreement: 3 labels look
   wrong (two reversed in faithfulness, one tool call that invents dates), and 4 of 31
   tool-invocation cases hinge on a date the input never anchors. The other flags describe the judge
   ([`results/label_audit_review.md`](results/label_audit_review.md)).
4. The benchmark gates pass a judge 5 points below the bar 4-30% of the time, and no suite can tell
   two good judges apart.
5. End to end on a live Phoenix, Phoenix's own conciseness evaluator was not trustworthy against
   reviews entered in its UI (kappa 0.17 [-0.27, 0.47]).

## Reproduce

```bash
git clone https://github.com/4ktLuffy/phoenix-evidence && cd phoenix-evidence
uv run --with pytest --with pytest-xdist pytest              # 54 tests, no network
uv run python bench/coverage.py                              # the guarantees below (a few minutes)
uv run python bench/audit_phoenix_suites.py                  # FINDINGS §4, from bench/phoenix_suites/suites.json
# Live, against a Phoenix server (no model calls; judgments are cached in results/judgments/):
PHOENIX=/path/to/phoenix npx tsx bench/phoenix_suites/extract.mjs   # case texts, kept out of the repo
uv run --extra phoenix python bench/certify_phoenix_suites.py       # FINDINGS §8, from cache
PHOENIX_BASE_URL=http://localhost:6006 uv run --extra phoenix python bench/cli_demo.py
```

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
