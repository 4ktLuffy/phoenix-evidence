"""Price of certainty with the judge disagreement measured on Phoenix's suites.

    uv run python bench/price_of_certainty.py

Disagreement: Codex (phoenix-evals evaluators, no reasoning) disagreed with the suites' labels on
25 of 505 cases (results/judgments; see bench/planner_sensitivity.py), about 5%; 15% is shown for a
weaker judge. 10,000 traces, interval +/-0.05 (width 0.1), pass rate 0.5 (worst case). Costs are
inputs, not measurements: a judge call at 0.002 and human labels from 0.05 to 5.00 per label.
Writes results/price_of_certainty.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_evidence._price import price_of_certainty  # noqa: E402

rows = []
for d in (25 / 505, 0.15):
    for human_cost in (0.05, 0.5, 5.0):
        p = price_of_certainty(10_000, 0.1, judge_cost=0.002, human_cost=human_cost, disagreement=d)
        rows.append({'disagreement': round(d, 3), 'human_cost': human_cost, 'human_only_labels': p.human_only.labels,
                     'human_only_cost': p.human_only.cost, 'corrected_labels': p.corrected.labels,
                     'corrected_cost': p.corrected.cost, 'cheapest': p.cheapest.name,
                     'break_even_human_cost': p.break_even_human_cost})  # fmt: skip
        print(rows[-1])
out = Path(__file__).resolve().parent.parent / 'results' / 'price_of_certainty.json'
out.write_text(json.dumps({'traces': 10_000, 'width': 0.1, 'judge_cost': 0.002, 'rows': rows}, indent=1))
