# Dataset doctor on Phoenix's 13 benchmark suites: reading of the flags

Source: `results/dataset_doctor.json` (`bench/dataset_doctor.py`, word 3-gram Jaccard >= 0.8, with
numbers kept whole since review 3; the first run, which split "1.0" into "1" and "0", also flagged
completeness 2/35 and 33/35, both read below as different questions on a shared table).

- **No exact copies, no near-copies with the same label that inflate a suite** beyond two
  same-label near-copies (completeness 13/20, tool_invocation 27/28), which share most of
  their context but ask different things. Benchmark design, not a problem.
- **12 conflicting pairs, all deliberate minimal pairs, labels correct** (read by hand):
  - completeness 34/35: the same answer with 2017 dropped -> incomplete. 15/17: the seat count
    dropped -> incomplete. 20/30: the interest-expense part dropped -> incomplete. 13/30: share a
    context table; different questions.
  - faithfulness 0/1 ... 14/15: the suite is built as 8 faithful/unfaithful pairs.
- **Real problems, already known:** conciseness passes a judge that always says "verbose"; the
  Nemotron PII suite has one label only.

What this adds: the minimal pairs let a judge be scored per pair (both members right), which is
stricter than per case; see `results/pair_consistency.json`.
