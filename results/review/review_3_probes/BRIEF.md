# Independent adversarial review 3 — phoenix-evidence, overnight work

You are an independent, skeptical reviewer. Find real defects by RUNNING code, not by opinion.
Rules: do not edit any file outside <review-scratch> (scratch is yours); no package
installs; no network; no model calls; no writes to any Phoenix server (reading http://localhost:6006
with GET is allowed). Do not post or contact anything.

Paths: R = <repo> (python: $R/.venv/bin/python; run
tests with `$R/.venv/bin/python -m pytest -q -p no:cacheprovider` from R).
P = <scratch>/px-main
(a Phoenix checkout with patches applied, venv at $P/.venv). Pristine Phoenix main 9212a42 is at
.../scratchpad/phoenix (has the 05/06/07 edits uncommitted; `git diff` there shows them).

What is new tonight (review all of it; the overnight log is $R/.night/LOG.md, claims to check):
1. Judge drift canary: $R/phoenix_evidence/_canary.py (mixture SPRT, Beta prior truncated above
   the allowed rate; claims: anytime-valid under the composite null including heterogeneous
   per-example flip rates; default prior Beta(1,(1-a)/a)), `judge_canary` in phoenix.py, CLI
   `canary`. Sims: bench/canary_sim.py -> results/canary_sim.json; real: bench/canary_real.py ->
   results/canary_real.json. Is the supermartingale argument right? Is the false-alarm claim
   right? Is the incomplete-beta tail numerically safe at large n? Does count_flips/the adapter
   treat errors/repetitions/missing examples correctly?
2. Dataset doctor + pair accuracy: _doctor.py, `doctor_dataset`, CLI `doctor`;
   bench/dataset_doctor.py, bench/pair_consistency.py, results/dataset_doctor_review.md.
3. Price of certainty: _price.py, CLI `price`; does it match what corrected_rate/clopper_pearson
   report? Monotonicity assumption in the binary search?
4. Effective judges: _jury.py, bench/effective_judges.py.
5. Planner changes: _ppi.py plan_labels default floor 0.2 -> 1.0; plan_label_queue
   `judge_probability` and corrected_rate_from_plan using probabilities as the judge value
   (is the corrected rate still unbiased/covering when the value is a probability?);
   bench/planner_probabilities.py, planner_sensitivity.py, planner_floor.py; the claim that
   planning itself adds only 1.06-1.3x and the 1.7-2.4x headline is mostly PPI.
6. GitHub Action: $R/action.yml, examples/workflows/phoenix-evidence.yml; compare header now
   shows experiment names (`_experiment_name`). Shell-injection or quoting problems in action.yml?
7. Phoenix patches $R/upstream/05-*.patch (benchmark data), 06-* (assistant skills docs),
   07-resume-stale-evaluations.patch (server deletes annotations of an errored run it replaces on
   resume; client run-count and resume_evaluation warnings). For 07: is deleting annotations on
   replacing an errored run correct in all cases (e.g. HUMAN annotations, annotations written
   after the error, concurrent writers)? Does it break anything else? Do the tests prove it?
   Check each patch applies to a pristine `git archive HEAD` of the pristine clone.
8. Instrument fix: bench/certify_phoenix_suites.py CachedJudge now records a model string;
   results/judgments/e2e_low.jsonl rows relabelled @low.

Output: write your full review to <review-scratch>/codex_review_3.md in this format:
a one-paragraph verdict; a "Claims" table (claim | CONFIRMED/WRONG/OVERCLAIM/UNVERIFIED | command
+ trimmed output); a numbered "Bugs" list, each with file:line, a minimal reproduction you ran
and its output, and severity; "Doc corrections". Be concrete. Prefer few solid findings over many
speculative ones. Your final message should be the same content.
