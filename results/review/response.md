# Response to the independent review (results/review/codex_review.md)

Each problem the review found, what changed, and the test that now guards it.

| # | Review finding | Change | Guarded by |
|---|---|---|---|
| 1 | xdist: 40 failing cases exit 0, even with `--evidence-strict` | workers send outcomes to the controller (`pytest_testnodedown`); only the controller decides and writes the report | `tests/test_pytest_plugin.py::test_xdist_workers_are_decided_together` |
| 2 | teardown error scored as a pass; marker-level skips undefined | teardown error turns a pass into a failure; marker-level skips (incl. `xfail(run=False)`) are left out, as Phoenix's plugin leaves them out, and documented | `test_teardown_error_turns_a_pass_into_a_failure`, `test_marker_level_skips_are_left_out` |
| 3 | `decide_rate` estimate outside its own interval with uneven repeats | estimate is the mean of example shares, the interval's basis | `tests/test_core.py::test_gate_estimate_lies_in_its_interval_when_repeats_are_uneven` |
| 4 | per-class recall by majority vote (50% class shown as 20/20) | recall counts judgments; interval by example share | `test_recall_counts_judgments_not_majority_votes` |
| 5 | sign-flip test described as exact for any zero-mean difference | docs now state the null it is exact for (versions interchangeable per example) | README, `_compare.py` docstring |
| 6 | an example with an empty score list disappears | counted as one missing run | `test_an_example_with_no_scores_counts_as_a_crash` |
| 7 | `examples_to_pass` returns 663, not the first size 662 | coarse search, then back to the first qualifying size | `test_examples_to_pass_returns_the_first_size` |
| 8 | compare-page fix counts examples, the schema says runs | not a regression (both versions group by example); raised as a question for maintainers | FINDINGS §1 |
| 9 | NULL span costs make runs look cheaper | predates the fix; raised as a question for maintainers | FINDINGS §1 |
| 10 | injection intervals over 69 judgments, not 23 cases | intervals by case (2/23 [0.01, 0.28], 0/23 [0.00, 0.15]) | `bench/injection_refusal.py`, FINDINGS §8 |
| — | "15-30%" measured recall, not F1; whole gate not measured | column replaced by the whole suite gate (accuracy and F1 both required): 4-30% | `bench/audit_phoenix_suites.py` |
| — | "about 2,350" used 3% discordance, text said 4% | one point at 3.9%: about 3,060; approximation named | FINDINGS §4 |
| — | "+0%" fix: 0 against 0 still shows +0% | stated | FINDINGS §2 |
| — | "explanation hid it" claims intent | reworded to what a reader of the explanation sees | FINDINGS §8 |
| — | README called simulated guarantees universal | section rewritten: what was simulated, and what is weaker | README |

Not changed: the review found no counterexample to the repeated-judgment interval or the kappa
floor for independent examples; both remain checked by simulation, not proved, as the README says.
