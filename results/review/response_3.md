# Response to the third review (results/review/codex_review_3.md, sonnet_review_3.md)

Codex ran out of credits during the review, after reproducing the defects below; Claude Sonnet (low
effort) reviewed the remaining areas and found no defects, with four wording points. Every item:

| # | Finding (reviewer) | Change | Guarded by |
|---|---|---|---|
| 1 | canary Beta tail underflows from 15,000 clean checks; evidence reads 0 (Codex) | tail computed in logs throughout; matches Codex's closed form log(19/(n+19)) to 12 digits. It only underflowed far below the allowed rate, so no alarm decision changed | `tests/test_canary.py::test_log_tail_matches_the_plain_formula_where_it_does_not_underflow`, `::test_drift_after_a_long_clean_history_is_still_caught` |
| 2 | canary adapter compared scores: a label change with the same score was no flip (Codex) | compares labels, scores only when there are none (`experiment_judgments`) | `tests/test_review_3.py::test_canary_compares_labels_not_only_scores` |
| 3 | a check on a hand-picked subset alarmed at once (Codex) | an example a check skipped counts as a flip: every check covers the frozen set | `::test_canary_counts_a_skipped_example_as_a_flip` |
| 4 | replaying one check accumulated its noise into a false alarm (Codex) | repeated check ids, or the reference as a check, are refused | `::test_canary_refuses_a_replayed_check` |
| 5 | price bisection on non-monotone Clopper-Pearson widths: 62 where 41 works (Codex) | scan up for the first n; bisection kept only for the monotone corrected width | `::test_price_finds_the_first_label_count_that_works` |
| 6 | jury divides by zero on anti-correlated errors (Codex) | no effective number when the formula does not apply; said in the summary | `::test_jury_of_judges_that_fail_on_different_cases` |
| 7 | doctor normalised '1.0' and '1,0' to one text (Codex) | numbers keep inner punctuation. Knock-on: Phoenix's suites now show 12 contrast pairs, not 13 (completeness 2/35 at 0.797); docs updated | `::test_doctor_keeps_numbers_apart` |
| 8 | pair accuracy counted case accuracy over unpaired repetitions (Codex) | both figures use the same paired repetitions | `::test_pair_accuracy_scores_only_paired_repetitions` |
| 9 | clipped corrected-rate estimate biased near 0 (0.11 for a truth of 0) (Codex) | clipping kept for the displayed value and documented; `raw_estimate` (unbiased) added to the result and to `corrected-rate`'s output | `::test_raw_estimate_is_unbiased_where_the_clipped_one_is_not` |
| 10 | patch 07 deleted HUMAN annotations too (Codex) | only CODE and LLM annotations of the replaced run are deleted | Phoenix `test_replacing_an_errored_run_removes_evaluations_of_the_failed_output` now checks a HUMAN annotation survives (SQLite and Postgres) |
| 11 | the delete queues no event (Sonnet, unverified) | the route now emits Phoenix's existing, until now unused, `ExperimentRunAnnotationDeleteEvent` with the deleted ids; the generic handler accepts it | Phoenix unit tests (25 passed on each database), client integration 74 passed |
| - | patch 06: "one-sided pattern ... 1 in 16" mixes one- and two-sided (Sonnet) | "5 of 5 the same way, in either direction, happens by chance 1 time in 16" | |
| - | patch 06 and FINDINGS 16: say the 25/46/89 bars are the two-sided 95% lower bound (Sonnet) | stated in both | |
| - | "~110 labels per class for a 90% judge, most of the time" is 79% power (Sonnet) | now "about 120 for 85% of the time (110 gives about 80%)", computed with `pass_probability` | |
| - | client integration counts unverified by Sonnet | rerun after all changes: 74 passed, 1 skipped | |

Not changed: evaluator trace spans of a deleted annotation stay in the experiment's trace project
without an annotation pointing at them (Sonnet, cosmetic). We did not check how Phoenix's UI treats
such spans; it is noted in FINDINGS 14 for the maintainers to judge.
