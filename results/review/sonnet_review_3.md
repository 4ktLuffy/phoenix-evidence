Reviewer: Claude Sonnet (low effort), completing Codex's review after Codex ran out of credits.

## Verdict
No new defects found in the five areas. Patch 05's data edits are internally consistent (weekdays correct, the faithfulness swap is right, case 31 now matches its tag, case 21 now justifies its dates). Every number in patch 06 recomputes exactly. Patch 07's server delete is correctly scoped (non-HUMAN only, per run id) and its server unit test passes and exercises the change. The probability-valued judge keeps the corrected rate unbiased, and coverage stayed at or above 95.9% in my simulation (conservative, never under-covering). The six numbers I spot-checked against results/*.json match. The repo suite is 94 passed, 2 skipped. A few wording or coverage nits are listed at the end. None of them is a bug.

## Claims
| Claim | Status | Command / evidence |
|---|---|---|
| "Today is" weekdays match dates (Jan 10 Wed, Jan 15 Mon, Jan 18 Thu) | CONFIRMED | python datetime: 2024-01-10 Wednesday, 01-15 Monday, 01-18 Thursday |
| Case 21 (dentist) justified: Thu Jan 18, "next Tuesday" gives Jan 23 | CONFIRMED | date(2024,1,23) is Tuesday; the tool call uses 2024-01-23T10:00 |
| Other new "System" dates justify tool calls (Team Sync "tomorrow" gives 01-16; standup "tomorrow" gives 01-16; flights Feb 1/3/5; Austin offsite Feb 15) | CONFIRMED | read tool_invocation.eval.ts in the patched clone; each tool_selection matches |
| Faithfulness swap correct | CONFIRMED | The context says Crambidae is the family, so "Crambidae" is the wrong answer to "which genus". The Indogrammodes answer is right. Now right_answer = genus sentence, unfaithful_answer = "Crambidae" |
| tool_response_handling 31 matches its tag | CONFIRMED | 42195 m is 42.2 km and 2400 s is 40 min; the output now says "4.2 km", which is a real transformation error with failure_mode improper_transformation |
| "25/25, 46/50, 89/100 needed for a rate above 80% at 95%" | CONFIRMED (two-sided 95% interval, lower bound > 0.8) | clopper_pearson(k,n,0.05): min k = 25, 46, 89. One-sided 95% would need 24, 45, 87 |
| "21/25 is 64-95%" | CONFIRMED | cp(21,25,0.05) = (0.639, 0.955) |
| "5 of 5 the same way is 1 in 16 by chance" | CONFIRMED, two-sided | 2/32 = 0.0625. One direction only is 1/32. The text says "even a one-sided pattern" and then "1 in 16"; it means "all five in either direction" |
| "90% judge needs ~110 labels/class, 95% judge ~50" | CONFIRMED, loosely | Exact binomial power with the 95% two-sided CP bound >0.8: p=0.9 at n=110 gives 0.79 and n=120 gives 0.86; p=0.95 at n=50 gives 0.90 |
| Python `correct_estimate`, bootstrap and `proportion_confint(method="beta")` snippets | CONFIRMED by reading | "beta" is Clopper-Pearson two-sided at alpha 0.05. The bootstrap needs numpy arrays, which the surrounding docs already imply |
| Patch 07 unit test passes | CONFIRMED | `px-main: pytest tests/unit/server/api/routers/v1/test_experiments.py -k replacing_an_errored --db sqlite` gives 1 passed |
| Patch 07 server test would fail without the change | CONFIRMED by reasoning, not run | The test posts a CODE annotation and a HUMAN annotation, replaces the run, and asserts only the HUMAN row remains. Without the delete, the CODE row stays |
| Client warning arithmetic | CONFIRMED | actual_runs now counts only runs with no error. total_attempted is summed from the evaluation_tasks actually run, so the "Only X of Y" denominator is what was attempted. The identical edit is in the async client |
| Corrected rate unbiased with probability judge | CONFIRMED | HT estimator is unbiased for any fixed judge values. Simulation (<review-scratch>/sim.py, 2,000 reps, human labels drawn as Bernoulli(q)): bias +0.0016 calibrated, +0.0035 overconfident, -0.0018 anti-correlated at N=200,B=40; at N=60,B=15 bias was 0.0013, 0.0015, 0.0024 |
| Interval valid with probability judge | CONFIRMED (conservative) | Coverage 0.978 calibrated, 0.975 overconfident, 0.959 anti-correlated at N=200,B=40. At N=60,B=15: 0.996, 0.998, 0.986. Gaps are fractional, so the 2 pseudo-disagreements (each worth a gap of 1) over-widen the interval |
| FINDINGS 11 table (80/160/320 labels: 0.196/0.142/99.0%/151, 0.138/0.092/95.8%/357, 0.096/0.059/97.3%/839) | CONFIRMED | results/ppi_sim.txt |
| FINDINGS 11 "1.4x calibrated/overconfident, 1.1 underconfident, up to 1.15 more from planning, coverage >= 94.2%" | CONFIRMED | planner_probabilities.json: uniform/probability 1.34-1.41 and 1.36-1.41, underconfident 1.06-1.11. sqrt design vs uniform probability is up to 1.16 for underconfident. Min coverage 0.942 |
| FINDINGS 11 live: 0.744 [0.674, 0.813], judge 0.700, truth 0.745, human-only [0.634, 0.958], 155 labels, 5,000 spans, 5.5 s | CONFIRMED | results/scale_test.json: 0.7435 (prints 0.744), 0.6996, 0.7446, [0.634, 0.958] |
| FINDINGS 15 "8 flags before, 0 after, 10 cases" | CONFIRMED | benchmark_fixes.json: 10 rows, flagged_before = 8, flagged_after = 0 |
| FINDINGS 18 faithfulness 75% case accuracy, 56% pairs, 37.5% same label | CONFIRMED | pair_consistency.json: 0.75, 0.5625, 0.375 |
| FINDINGS 19 price (402 vs 107 labels, break-even 0.068) and jury (corr 0.77, 1.18, 95.2% vs 95.4%) | CONFIRMED | price_of_certainty.json, effective_judges.json "all three" |
| FINDINGS 17 canary (23.5% vs 1.6%; medians 24/12/5/2; real flips 10 and 11) | CONFIRMED | canary_sim.json, canary_real.json (5+2+4 = 11) |
| Repo test suite | CONFIRMED | `.venv/bin/python -m pytest -q`: 94 passed, 2 skipped |

## Bugs
None found that I could reproduce. I looked for these in patch 07 and found no defect:
- Resumed, errored again: the delete runs on each replacement, so annotations scored on the second failed output are removed too. That is correct.
- Repetitions: annotations hang off the run id, which is per example and repetition, so one repetition's replacement never touches another's.
- Races: both concurrent replacers delete the same non-HUMAN rows, which is idempotent. The delete and the upsert are in the same session, so a failed insert rolls the delete back.

Unverified:
- (low) The delete emits no event; only ExperimentRunInsertEvent is queued after the upsert. If any cached annotation summary exists server-side, it may stay stale until recomputed. I did not look.
- (low) Evaluator trace spans linked from a deleted annotation are left orphaned. This is cosmetic.

## Doc corrections (all minor wording or coverage)
1. 06, the sentence in SKILL.md: "even a one-sided pattern is not yet evidence (5 of 5 the same way happens by chance about 1 time in 16)". 1/16 is the two-sided figure (either direction); one-sided is 1/32. Suggest "5 of 5 in either direction happens by chance 1 time in 16".
2. 06 and FINDINGS 16: "show a rate above 80% at 95%" does not say that the 95% is a two-sided interval. The required counts are 24/45/87 at a one-sided 95%. Suggest "lower end of the 95% two-sided interval above 80%".
3. 06: the "~110 labels per class for a 90% judge" figure gives only about 79% power at n=110 (86% at 120), so "most of the time" is right but only just.
4. Patch 07's integration tests (client resume behaviour) were not run in my pass; I only ran the server unit test. The "74 passed / 716 passed" claim in FINDINGS 14 is therefore UNVERIFIED by me.
