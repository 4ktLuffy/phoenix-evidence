# Response to the fourth review (results/review/sonnet_review_4.md)

Reviewer: Claude Sonnet, low effort (Codex had run out of credits; Henos asked for Haiku or Sonnet
instead). Scope: what was added after review 3: `compare --sequential`, the Codex-to-Haiku canary
run, `upstream/08`, the CLI's error handling.

| # | Finding | Change | Guarded by |
|---|---|---|---|
| 1 | `sequential_compare_experiments` dropped metrics only one experiment scored, silently, and the Bonferroni divisor shrank | such metrics are reported (`only_in`, and a line in the CLI output) and the divisor counts every metric either side scored | `tests/test_phoenix_adapter.py::test_sequential_reports_a_metric_only_one_side_scored` |
| 2 | each call replayed the finished examples in id order, an order that never happened, and could decide at a prefix; the worst-score imputation came from the data seen so far | the adapter makes one look per call on the counts (the evidence depends only on them), via `SequentialComparison.look`; a missing score is the fixed worst possible score when scores lie in [0, 1]; the docstring and FINDINGS say why reruns are covered | `::test_a_batch_look_decides_on_the_current_evidence_only` (a streak that crosses in a replay does not decide as one look) |
| 3 | `main_exit` turned every ValueError, including a programming error, into one line | the line now says how to get the traceback, and `PHOENIX_EVIDENCE_DEBUG=1` re-raises | |
| 4 | `fixed_n_80` fixes the disagreement count at its mean (flatters the fixed test); medians are over runs that decided | both stated in FINDINGS §21, with the 16% undecided at q = 0.6 | |
| - | NaN scores counted as ties | `add`/`look` refuse a NaN | `::test_a_batch_look_decides_on_the_current_evidence_only` |
| - | "two different models do better" | now "decorrelate far more", with the two-judge majority's 0.851 against 0.940 stated | |
| - | README's 9.5% mixed the two Haiku passes | now 13% and 6%, per pass | |
| - | patch 08: `(True, False)` scored 0.0 with label "True" | the first bool decides score and label | Phoenix test, parametrized, 141 passed |

Confirmed by the review, unchanged: the mixture likelihood ratio and its martingale property; the
false-decision rates; patch 08 for every order of numbers and bools; every number in FINDINGS §17,
§21 and the README's sequential block, recomputed from the cached judgments and results.
