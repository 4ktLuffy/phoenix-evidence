# Response to the second independent review (results/review/codex_review_2.md)

| # | Review finding | Change | Guarded by |
|---|---|---|---|
| 1 | corrected rate biased: the judge's weight was tuned on the same labels | the weight is fixed (default 1, plain PPI) and documented; tuning removed | `tests/test_ppi.py::test_estimate_is_unbiased_by_exact_enumeration` (the review's counterexample, by exact enumeration) |
| 2 | wrong variance for unequal-probability sampling; 0.3% coverage in a valid adversarial design | Horvitz-Thompson design variance, plus two pseudo-disagreements for small samples (one was measured insufficient), Student t; inclusion probabilities below a tenth of the mean are refused, since a group almost never sampled makes the variance unestimable | `bench/ppi_sim.py` (coverage 95.8-100% at every budget and design); `test_almost_never_sampled_traces_are_refused`; `test_a_census_gives_the_exact_rate` |
| 3 | interval ends outside [0, 1]; shapes not validated | both ends clipped; inclusion length, label indices and a zero planner floor refused | `test_interval_ends_stay_in_zero_one`, `test_bad_shapes_are_refused` |
| 4 | unfinished reviews treated as zero gaps | no estimate until every chosen span is labelled, with the count left | `tests/test_phoenix_adapter.py::test_review_2_corrected_rate_refuses_what_would_bias_it` |
| 5 | the population or the judge's labels could change after the draw | the plan freezes the judge's labels; the population is the planned one | same test |
| 6 | several reviewers on a span aggregated differently in different places | certificate: every (human, judge) pair, disagreements listed per pair; corrected rate: the reviewers' share of passes | `test_review_2_several_reviewers_are_counted_the_same_everywhere` |
| 7 | "latest" compared timestamp strings | compared as instants | `test_review_2_latest_compares_instants_not_strings` |
| 8 | Phoenix patch 03: repetitions counted as examples (runner names them `[rep i/N]`) | grouped by example id, else the name without the suffix; the test now uses the runner's real names | `acceptance.test.ts` "counts repetitions of one test once, as the runner names them" (fails on the previous code) |
| 9 | patch 03: a missing score counted as a success when minimizing | a missing score is the worst outcome in the criterion's direction | `acceptance.test.ts` "counts a missing score as the worst outcome when minimizing" (fails on the previous code) |
| 10 | patch 04: a baseline of zeros invented for an evaluator the base never ran | only annotations scored in both experiments are compared | `test_queries.py::test_experiment_annotation_evidence_skips_annotations_one_side_never_scored` (SQLite and Postgres) |
| 11 | patch 04: direction ignored; sample size not scale-free | direction read from the annotation config; worst score and verdict follow it; 0/1 scores use the paired-proportion formula, others a scale-free one | same test; `test_lower_is_better_flips_the_verdict_and_the_worst_score`, `test_examples_needed_does_not_depend_on_the_scale` |
| 12 | xdist: a crashed worker lost its finished outcomes from the report | each outcome rides on its own test report to the controller; reports lost with a crashed worker mark the decision incomplete and fail the run | `tests/test_pytest_plugin.py::test_a_crashed_xdist_worker_marks_the_decision_incomplete` |
| - | demo crashes were 10 of 120, not 12 | corrected in README, FINDINGS, the page and `bench/cli_demo.py` | |
| - | the page said five faithfulness labels were flagged | four were flagged | |
| - | label readings: tool_response 31, tool_invocation 21, correctness 15 | changed as the review argued; totals in `results/label_audit_review.md` | |
| - | §13 certificate and switch numbers come from an oversampled subset | stated in FINDINGS §13 | |
| - | "about twice as many labels" | now 1.7-2.4 times at 80-320 labels, from the corrected simulation, and called an extrapolation by the 1/sqrt(n) rule | |
| - | patch 04 already contains patch 03 | stated in FINDINGS §9 | |
