Reviewer: Claude Sonnet (low effort)

## Verdict
The sequential math is correct and the doc numbers match the JSON. No blocker. Real issues: (1) `sequential_compare_experiments` silently drops metrics present in only one experiment, and the Bonferroni divisor then shrinks. (2) It claims to read "in dataset order" but sorts by example id, so each rerun feeds the test a different order. (3) `main_exit` turns any ValueError, including programming errors, into a one-line message with no traceback. (4) The `fixed_n_80` comparison is approximate and favours the fixed test slightly. Patch 08 is correct. The canary numbers reproduce.

## Claims
| claim | status | command + trimmed output |
|---|---|---|
| Mixture LR is the Beta(a,a) beta-binomial LR against a fair coin; martingale | CONFIRMED | Read `_sequential.py:log_evidence` = log B(a+k,a+n-k)/B(a,a) + n log 2. Exact marginal likelihood ratio, so a nonnegative martingale. Tie-only stream: evidence 0.51/0.18/0.06 at n=10/100/1000, so it never crosses 20 on ties. |
| False decision <= alpha under any looks | CONFIRMED (sim) | 3000 runs x 300 fair-coin looks: 0.034 decided. Matches the 2.4-2.9% in the JSON. |
| All ties gives no decision | CONFIRMED | `extend([(1,1)]*50)` gives evidence 1.00, no decision. |
| lower_is_better | CONFIRMED | `higher_is_better=False`, `.extend([(1,0)]*6)`: evidence 39.4 at 0/10 vs 10/0 symmetrical, direction correct. |
| decided_at sticky, direction label can't be wrong-signed on a tie | CONFIRMED | Evidence at better==worse is below 1 in every size tried, so the tie branch (`'candidate worse'`) is unreachable. |
| NaN score | OVERCLAIM-ish | `add(nan, 1)`: counted as a tie (ties=1). A NaN is silently "no evidence", not an error. |
| `sequential_compare_experiments` can't silently drop a metric | WRONG | See Bug 1. |
| `fixed_n_80` is a fair comparison | OVERCLAIM | See Bug 4. |
| Section 17 numbers (Codex 3/168 = 1.8%; Haiku 22 and 10; self 10.7%; 9.5% over both; evidence 2.3 of 20) | CONFIRMED | Recomputed from `results/judgments/*.jsonl`: `168 3 22 10 18` (n, codex repeat flips, Haiku1 vs Codex, Haiku2 vs Codex, Haiku1 vs Haiku2). 32/336 = 9.5%; 18/168 = 10.7%. JSON final evidence 2.258. |
| Post-hoc sensitivity labelled as post hoc | CONFIRMED | Script comment and FINDINGS both say "Post hoc, for guidance only". JSON: 2% alarms at "Haiku, part 2" (112 Haiku re-scores), 3% and 4% at part 3, 5% none. |
| §19 "Codex and Haiku err on different cases, worth 1.73 independent judges" | OVERCLAIM (mild) | JSON: correlation 0.157, effective_judges 1.73, but majority accuracy 0.851 against 0.940 for Codex alone, and Haiku accuracy 0.893. "Do better" is about decorrelation, not accuracy. The sentence's gain-for-a-third-vote caveat covers it. |
| Patch 08 (tuple handling) | CONFIRMED | Phoenix test file: `140 passed`. Probe: (0.8,True) and (True,0.8) give 0.8/'True'; (1,True) and (True,1) give 1/'True'; (True,) gives 1.0/'True'; (False,) gives 0.0/'False'; (0.5,0.7) gives 0.7/None (last number wins, as before); (True,0.8,False) gives 0.8/'True'; (True,'good') gives 1.0/'good'. |
| Doc numbers (§21, README) vs `sequential_sim.json` | CONFIRMED | 28.7% naive, 2.9% (a=2), 2.4-2.9% across priors, wrong-direction max 0.0007, medians 830/240/110, fixed 1020/260/100, demo evidence 39.4 of 40 (alpha 0.05/2 -> 40). All match. |
| Repo tests | CONFIRMED | `pytest -q`: 100 passed, 2 skipped. |

## Bugs
1. `phoenix_evidence/phoenix.py` `sequential_compare_experiments` (`names = sorted(set(base) & set(candidate))`), medium. A metric scored in only one experiment is dropped with no note. `compare_experiments` returns `only_in`; the sequential path returns nothing about it and the CLI prints nothing. Bonferroni then divides by the intersection size, so alpha per metric changes silently. Pairing was correct in the paths I read (examples intersect, missing score replaced by the worst, repeats averaged). Related: `if b and c` skips an example with an empty list without reporting it. Fix: return or print the dropped metrics and the divisor, or fix the divisor to the union.
2. Same function, `sorted(set(base[name]) & set(candidate[name]))`, medium (statistical, subtle). The docstring says "in dataset order", but it sorts by example id string. While experiments are running, each call sees a different set of finished examples in a different order, and a new example can land mid-sequence. Ville's guarantee holds for a fixed arrival order, not for a re-ordered stream across reruns, so the "rerun any time" validity claim is not strictly supported. In addition, `worst` (the missing-as-worst imputation) is recomputed per call from the examples seen so far, so earlier pairs change between looks. Fix: document the caveat, or order by completion time and freeze the imputation value.
3. `cli.py:343-354` `main_exit`, low-medium. `except ValueError` prints only `str(e)` and exits 2 for any ValueError. `grep -c ValueError phoenix_evidence/*.py` shows 22 raise sites. A ValueError from a genuine bug (a bad index parse or unpacking, for example) is shown as "phoenix-evidence: <msg>" with no traceback, which loses information. Suggested fix: use a dedicated `UserError(ValueError)` for refusals, or print the traceback when `PHOENIX_EVIDENCE_DEBUG` is set. The ConnectError branch re-raises everything else, so only the ValueError branch is affected.
4. `bench/sequential_sim.py:fixed_n_80`, low. It uses D = round(0.2 n) discordant pairs as if fixed, while the sim draws D ~ Binomial, and it steps n in tens. That slightly overstates fixed-test power, so the fixed sizes are slightly small. Also, the sequential medians are conditional on being decided and right: at q=0.6 only 84% decide by 2000, so that median is censored and optimistic. The text "close to the fixed size" is fair at q=0.7 and 0.8 (240 vs 260, 110 vs 100). At q=0.6 it should be flagged: 830 vs 1020, with 16% undecided at 2000.

## Doc corrections
- FINDINGS §21: say that metrics absent from one experiment are not tested, and that the divisor is the number of metrics in both. Change "in dataset order" to "by example id", or fix Bug 2.
- FINDINGS §21 median sentence: note that the medians are for runs that decided, and that 16% at q=0.6 did not decide by 2,000.
- FINDINGS §19 / README item 10: "Two different models do better" should say "decorrelate more" (majority accuracy 0.851 against 0.940 single). README "flips 9.5%" mixes passes: the first pass was 13%, the second 6%.
- Patch 08 (cosmetic, not a bug): `(True, False)` gives score 0.0 with label 'True' (first bool label kept, last bool score). This was the same before the patch.
