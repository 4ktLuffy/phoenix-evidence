# Label audit: a person's reading of each flagged case

`bench/label_audit.py` flags a case when Phoenix's own evaluator (on Codex, gpt-5.6-luna, no
reasoning) gives the same answer on both repeats and the suite's label says otherwise. A flag is
a candidate, not a finding. Each one below was read against the evaluator's rubric and given one
of three readings:

- **label looks wrong**: the suite's label contradicts its own rubric or context;
- **judge too lenient / too strict**: the label follows the rubric and the judge does not;
- **ambiguous**: a careful reader could defend either label.

## faithfulness (16 cases; from bench/certify_phoenix_suites.py)

| case | label | judge | reading |
|---|---|---|---|
| 12 | faithful | unfaithful | **label looks wrong**: "Crambidae" is the family; the context names Indogrammodes as the genus |
| 13 | unfaithful | faithful | **label looks wrong**: the answer states exactly what the context says |
| 10 | faithful | unfaithful | ambiguous: the context describes Leconte's career without naming him |
| 15 | unfaithful | faithful | ambiguous: "notorious" is a fair paraphrase of the context's controversies |

## completeness (45 cases)

No flags.

## correctness (80 cases)

The rubric asks for answers that are "accurate and complete", with no "incomplete or partial
answers" or "ambiguous or misleading language".

| case | category | label | judge | reading |
|---|---|---|---|---|
| 1 | factual_accuracy | incorrect | correct | judge too lenient: "give or take a few degrees" is the misleading hedge the rubric excludes |
| 15 | completeness | incorrect | correct | ambiguous: short but accurate; the rubric asks for completeness but also to focus on correctness rather than verbosity (reading changed after review 2) |
| 51 | ambiguous_language | incorrect | correct | judge too lenient: "...and stuff" is the ambiguous language the rubric excludes |
| 57 | partial_correctness | incorrect | correct | judge too lenient: 343 m/s without its conditions (dry air, about 20 °C) is a partial answer |
| 20 | logical_consistency | correct | incorrect | ambiguous: rejecting the false premise is consistent with reality, not with the hypothetical (review 2 leans "label wrong") |

Three of the correctness flags describe the judge: it under-applies the rubric's clauses on
hedged, vague and partial answers. That is what a certificate should say before anyone gates on it.

## hallucination (37 cases)

The rubric exempts "uncontroversial, widely-known general knowledge — common facts" from the
grounding check (its rule 4).

| case | category | label | judge | reading |
|---|---|---|---|---|
| 29 | general_knowledge | grounded | hallucinated | judge too strict: "Paris is the capital of France" is the common fact rule 4 exempts |

## pii_detection.synthetic (40 cases)

No flags: the judge agreed with all 40 labels on both repeats.

## retrieval_relevance (33 cases)

| case | category | label | judge | reading |
|---|---|---|---|---|
| 18 | sql | relevant | irrelevant | judge too strict: a query result (`[{"n": 7, "revenue": 842.15}]`) need not restate the customer and month it was filtered by |

## tool_invocation (31 cases)

All five flags are calls labelled correct whose dates the conversation does not support. The
judge marks each incorrect.

| case | category | the date the call assumed | reading |
|---|---|---|---|
| 18 | correct_single_tool | "tomorrow" -> 2024-01-16 | **benchmark design**: no current date in the input |
| 21 | correct_multi_tool | no dates given -> 2024-02-01/03/05 | **label looks wrong**: the call invents three travel dates the user never gave; a current date would not supply them (reading changed after review 2) |
| 23 | multi_turn_context | "February 15th" -> 2024-02-15 | **benchmark design**: year assumed |
| 28 | full_tool_list_json | "next Tuesday" -> 2024-01-23 | **benchmark design**: no current date in the input |
| 30 | filtered_human_readable | "February 1st" -> 2024-02-01 | **benchmark design**: year assumed |

4 of the suite's 31 cases (13%) hinge on a date the conversation never anchors, so a careful
judge and the suite disagree by design. Adding a "Current date: ..." line to those inputs, or a
rubric rule for relative dates, would make them decidable. Case 21 is different: its dates are
invented outright.

## tool_response_handling (51 cases)

| case | category | label | judge | reading |
|---|---|---|---|---|
| 31 | improper_transformation | incorrect | correct | judge too lenient: the label is right, because "by car" is invented and the rubric forbids unsupported details; only the failure-mode tag is wrong, since 42,195 m is 42 km and 2,400 s is 40 minutes (`tool_response_handling.eval.ts:497-507`; reading changed after review 2) |
| 8 | correct_transformation | correct | incorrect | judge too strict: it objects to "current" for a rate the tool timestamped and the answer dates |

## toxicity (58 cases)

No flags: the judge agreed with all 58 labels on both repeats.

## user_friction (40 cases)

| case | category | label | judge | reading |
|---|---|---|---|---|
| 7 | retry | friction | no_friction | judge too lenient: the suite treats a retry after a failure as friction (its category), and the judge does not |

## conciseness (34) and refusal (40)

No flags (from the certificates in FINDINGS section 8).

## Totals

12 suites, 505 cases, each judged twice by its own evaluator. 19 flags, read one by one (an
independent second reader, review 2 in `results/review/codex_review_2.md`, changed three readings):

| reading | flags |
|---|---|
| label looks wrong | 3 (faithfulness 12 and 13; tool_invocation 21) |
| benchmark design (no date in the input to anchor a relative date) | 4 (tool_invocation 18, 23, 28, 30) |
| judge too lenient | 5 (correctness 1, 51, 57; user_friction 7; tool_response_handling 31) |
| judge too strict | 3 (hallucination 29; retrieval_relevance 18; tool_response_handling 8) |
| ambiguous | 4 (faithfulness 10 and 15; correctness 15 and 20) |
