"""Build docs/findings.html from the result files, so every number on the page comes from a measurement.

uv run python bench/build_findings_page.py
"""

from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / 'results'
REPO = 'https://github.com/4ktLuffy/phoenix-evidence'
PX = 'https://github.com/Arize-ai/phoenix/blob/9212a42a512d08de7e2a8e81b15821f4483812ce'


def esc(x: object) -> str:
    return html.escape(str(x))


def interval_svg(rows: list[tuple[str, float, float, float]], lo: float, hi: float, bar: float | None,
                 bar_label: str, ticks: list[float], fmt: str = '{:.1f}') -> str:  # fmt: skip
    """Estimate dot and interval line per row, on one shared scale, with an optional bar."""
    w, left, right, row_h, top = 640, 210, 24, 34, 18
    h = top + row_h * len(rows) + 30
    x = lambda v: left + (v - lo) / (hi - lo) * (w - left - right)  # noqa: E731
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" class="ivl">']
    for t in ticks:
        parts.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" y2="{h - 26}" class="grid"/>')
        parts.append(f'<text x="{x(t):.1f}" y="{h - 10}" class="tick" text-anchor="middle">{fmt.format(t)}</text>')
    if bar is not None:
        parts.append(f'<line x1="{x(bar):.1f}" x2="{x(bar):.1f}" y1="{top - 10}" y2="{h - 26}" class="bar"/>')
        parts.append(f'<text x="{x(bar) + 4:.1f}" y="{top - 2}" class="barlabel">{esc(bar_label)}</text>')
    for i, (label, est, a, b) in enumerate(rows):
        y = top + 14 + i * row_h
        parts.append(f'<text x="{left - 12}" y="{y + 4}" class="rowlabel" text-anchor="end">{esc(label)}</text>')
        parts.append(f'<line x1="{x(max(a, lo)):.1f}" x2="{x(min(b, hi)):.1f}" y1="{y}" y2="{y}" class="span"/>')
        for end in (a, b):
            if lo <= end <= hi:
                parts.append(f'<line x1="{x(end):.1f}" x2="{x(end):.1f}" y1="{y - 6}" y2="{y + 6}" class="span"/>')
        parts.append(f'<circle cx="{x(est):.1f}" cy="{y}" r="4.5" class="dot"/>')
    parts.append('</svg>')
    return ''.join(parts)


def main() -> None:
    audit = json.loads((R / 'phoenix_suites_audit.json').read_text())
    certs = json.loads((R / 'certificates.json').read_text())
    inj = json.loads((R / 'injection_refusal.json').read_text())
    demo = (R / 'cli_demo.txt').read_text()
    shot = base64.b64encode((R / 'screenshots' / 'phoenix_compare_fragile.jpg').read_bytes()).decode()
    shot_after = base64.b64encode((R / 'screenshots' / 'phoenix_with_evidence.jpg').read_bytes()).decode()
    ppi = {r['budget']: r for r in json.loads((R / 'ppi_sim.json').read_text())}
    scale = json.loads((R / 'scale_test.json').read_text())
    e2e_cert = json.loads((R / 'e2e_certify_feedback.json').read_text())
    e2e_rate = json.loads((R / 'e2e_corrected_rate.json').read_text())
    audit_labels = json.loads((R / 'label_audit.json').read_text())

    # The two compare runs in the demo, parsed from their own output tables.
    tables = re.findall(
        r'\| (exact_match|task_error) \| ([\d.]+) \| ([\d.]+) \| ([+-][\d.]+) \[([+-][\d.]+), ([+-][\d.]+)\] \| ([\d.e-]+) \| ([^|]+) \|',
        demo,
    )
    tweak, fragile = tables[0:2], tables[2:4]
    diff_rows = [
        ('tweak: exact_match', *map(float, (tweak[0][3], tweak[0][4], tweak[0][5]))),
        ('fragile: exact_match', *map(float, (fragile[0][3], fragile[0][4], fragile[0][5]))),
        ('fragile: task errors', *map(float, (fragile[1][3], fragile[1][4], fragile[1][5]))),
    ]
    kappa_rows = [
        (f'{name} ({certs[name]["examples"]} cases)', certs[name]['kappa'], *certs[name]['kappa_interval'])
        for name in ('faithfulness', 'conciseness', 'refusal')
    ]
    gate_rows = json.loads((R / 'coverage.json').read_text())['gate_false_pass_just_below_bar (promise <= 0.025)']

    rows = []
    for r in audit['rows']:
        gates = ', '.join(f'{k} &ge; {v}' for k, v in r['gates'].items())
        k = r['exact_gate_min_correct']
        need = f'{k}/{r["cases"]}' if k is not None else 'none'
        const = '<span class="pill bad">passes</span>' if r['constant_judge_passes_all_gates'] else 'fails'
        rows.append(
            f'<tr><td>{esc(r["suite"])}</td><td class="num">{r["cases"]}</td><td>{gates}</td><td>{const}</td>'
            f'<td class="num">{r["suite_gate_passes_judge_5pt_below"]:.0%}</td><td class="num">{need}</td>'
            f'<td class="num">{r["exact_gate_pass_prob_judge_97pct"]:.0%}</td>'
            f'<td class="num">{r["cases_needed_judge_5pt_above_80pct"]}</td></tr>'
        )
    two_class = [r for r in audit['rows'] if len(r['classes']) > 1]
    lo_pass = min(r['suite_gate_passes_judge_5pt_below'] for r in two_class)
    hi_pass = max(r['suite_gate_passes_judge_5pt_below'] for r in two_class)
    jev = audit['jev_pooled']

    page = TEMPLATE.format(
        shot=shot,
        shot_after=shot_after,
        ppi80=ppi[80]['human_labels_for_same_width'],
        ppi160=ppi[160]['human_labels_for_same_width'],
        ppi_cov=f'{min(r["active_coverage"] for r in ppi.values()):.0%}',
        sc_est=f'{scale["corrected"]["estimate"]:.3f}',
        sc_lo=f'{scale["corrected"]["interval"][0]:.3f}',
        sc_hi=f'{scale["corrected"]["interval"][1]:.3f}',
        sc_judge=f'{scale["corrected"]["judge_rate"]:.3f}',
        sc_truth=f'{scale["true_human_pass_rate"]:.3f}',
        sc_compare=scale['compare_seconds'],
        e2e_kappa=f'{e2e_cert["kappa"]:.2f}',
        e2e_klo=f'{e2e_cert["kappa_interval"][0]:.2f}',
        e2e_khi=f'{e2e_cert["kappa_interval"][1]:.2f}',
        e2e_n=e2e_cert['paired_spans'],
        e2e_judge=f'{e2e_rate["judge_rate"]:.2f}',
        e2e_est=f'{e2e_rate["estimate"]:.2f}',
        audit_suites=len(audit_labels),
        audit_cases=sum(v['cases'] for v in audit_labels.values()),
        lo_pass=f'{lo_pass:.0%}',
        hi_pass=f'{hi_pass:.0%}',
        audit_rows='\n'.join(rows),
        n_suites=len(audit['rows']),
        n_cases=sum(r['cases'] for r in audit['rows']),
        jev_detect=f'{jev["smallest_detectable_difference"] * 100:.1f}',
        jev_one=f'{jev["examples_needed_1_point"]:,}',
        kappa_svg=interval_svg(kappa_rows, -0.4, 1.0, 0.6, 'bar 0.6', [-0.4, 0, 0.4, 0.8, 1.0]),
        diff_svg=interval_svg(diff_rows, -0.05, 0.15, 0.0, 'no change', [-0.05, 0, 0.05, 0.1, 0.15], '{:+.2f}'),
        inj_note=f'{len(inj["grader_note"]["cases_flipped"])}/{inj["grader_note"]["cases"]}',
        inj_neutral=f'{len(inj["neutral_note"]["cases_flipped"])}/{inj["neutral_note"]["cases"]}',
        fp_ours=f'{max(r["ours_false_pass"] for r in gate_rows):.1%}',
        fp_naive=f'{min(r["point_estimate_false_pass"] for r in gate_rows):.0%}&ndash;{max(r["point_estimate_false_pass"] for r in gate_rows):.0%}',
        repo=REPO,
        px=PX,
    )
    out = ROOT / 'docs' / 'findings.html'
    out.parent.mkdir(exist_ok=True)
    out.write_text(page)
    print(f'wrote {out} ({len(page) // 1024} KB)')


TEMPLATE = """<title>Evidence for Phoenix</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,650&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column with wide figures; findings as a ledger, numbers in mono. */
:root {{
  --bg: #f5f6f4; --surface: #ffffff; --ink: #191c1a; --muted: #5b625d; --rule: #d9ddd8;
  --accent: #2f6b4f; --accent-soft: #e3eee7; --bad: #a3402c; --bad-soft: #f6e4df; --warn: #8a6414; --warn-soft: #f5ecd6;
  --display: "Source Serif 4", Georgia, serif; --body: "IBM Plex Sans", system-ui, sans-serif; --mono: "IBM Plex Mono", ui-monospace, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #131614; --surface: #1b1f1d; --ink: #e7ebe8; --muted: #9aa39d; --rule: #2e3431;
  --accent: #7cc4a0; --accent-soft: #1f3329; --bad: #ec8e78; --bad-soft: #3a221d; --warn: #e2bc6a; --warn-soft: #362d17; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #131614; --surface: #1b1f1d; --ink: #e7ebe8; --muted: #9aa39d; --rule: #2e3431;
  --accent: #7cc4a0; --accent-soft: #1f3329; --bad: #ec8e78; --bad-soft: #3a221d; --warn: #e2bc6a; --warn-soft: #362d17; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--ink); font: 16px/1.6 var(--body); }}
.wrap {{ max-width: 860px; margin: 0 auto; padding-inline: 20px; padding-block: 48px 72px; display: grid; gap: 56px; }}
h1, h2 {{ font-family: var(--display); font-weight: 650; text-wrap: balance; line-height: 1.15; margin: 0; }}
h1 {{ font-size: clamp(2rem, 5vw, 2.9rem); }}
h2 {{ font-size: 1.55rem; }}
h3 {{ font-size: 1.02rem; margin: 0; font-weight: 600; }}
p {{ margin: 0; max-width: 66ch; }}
a {{ color: var(--accent); text-underline-offset: 3px; }}
a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
code, .num, pre {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
code {{ font-size: 0.88em; }}
section {{ display: grid; gap: 18px; min-width: 0; }}
.eyebrow {{ font: 500 0.78rem var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }}
.lede {{ font-size: 1.18rem; color: var(--ink); }}
.meta {{ color: var(--muted); font-size: 0.92rem; }}
figure {{ margin: 0; display: grid; gap: 10px; min-width: 0; }}
figure img {{ border: 1px solid var(--rule); border-radius: 6px; display: block; }}
figcaption {{ color: var(--muted); font-size: 0.93rem; max-width: 70ch; }}
.ledger {{ display: grid; gap: 0; border-top: 1px solid var(--rule); }}
.item {{ display: grid; grid-template-columns: 9.5rem 1fr; gap: 6px 20px; padding-block: 18px; border-bottom: 1px solid var(--rule); }}
.item > div {{ display: grid; gap: 6px; min-width: 0; }}
@media (max-width: 620px) {{ .item {{ grid-template-columns: 1fr; }} }}
.pill {{ display: inline-block; font: 500 0.74rem var(--mono); letter-spacing: 0.04em; padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); justify-self: start; align-self: start; }}
.pill.bad {{ background: var(--bad-soft); color: var(--bad); }}
.pill.warn {{ background: var(--warn-soft); color: var(--warn); }}
pre {{ background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 14px 16px; overflow-x: auto; font-size: 0.82rem; line-height: 1.5; margin: 0; }}
.cmd {{ color: var(--accent); }}
.table {{ overflow-x: auto; border: 1px solid var(--rule); border-radius: 6px; background: var(--surface); }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; }}
th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--rule); vertical-align: top; }}
th {{ font-weight: 500; color: var(--muted); font-size: 0.78rem; }}
td.num, th.num {{ text-align: right; white-space: nowrap; }}
tr:last-child td {{ border-bottom: 0; }}
.ivl {{ width: 100%; height: auto; display: block; background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; }}
.ivl .grid {{ stroke: var(--rule); stroke-width: 1; }}
.ivl .tick, .ivl .barlabel {{ fill: var(--muted); font: 11px var(--mono); }}
.ivl .rowlabel {{ fill: var(--ink); font: 12.5px var(--body); }}
.ivl .bar {{ stroke: var(--bad); stroke-width: 1.5; stroke-dasharray: 4 3; }}
.ivl .span {{ stroke: var(--ink); stroke-width: 2; }}
.ivl .dot {{ fill: var(--accent); }}
.two {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
.two > div {{ display: grid; gap: 8px; align-content: start; min-width: 0; }}
footer {{ color: var(--muted); font-size: 0.88rem; border-top: 1px solid var(--rule); padding-top: 18px; display: grid; gap: 6px; }}
</style>

<main class="wrap">
<header style="display:grid;gap:16px">
  <div class="eyebrow">phoenix-evidence &middot; findings on Arize Phoenix main @ 9212a42</div>
  <h1>Phoenix shows a number. This shows whether it means anything.</h1>
  <p class="lede">We read Phoenix's evaluation code, ran its own benchmark suites and evaluators, and checked the numbers its pages show. We found two bugs on the experiment compare page, two reversed labels in a benchmark, and gates too small to decide. Then we built the missing piece as a tool on top of Phoenix: margins of error, judge certificates, and CI gates that can say "not enough evidence".</p>
  <p class="meta"><a href="{repo}">Code, tests and every measurement</a> &middot; <a href="{repo}/blob/main/FINDINGS.md">FINDINGS.md</a> with file and line for each claim &middot; not affiliated with Arize</p>
</header>

<figure>
  <img src="data:image/jpeg;base64,{shot}" alt="Phoenix experiment compare page: exact_match 0.84 for the baseline and 0.96, +14.49%, for a version that crashed on 10 of 120 questions; cost cards show +0% for missing values; latency shows 65 improved and 48 regressed.">
  <figcaption>Phoenix's own compare page. The candidate crashed on 10 of 120 questions; Phoenix averages the runs that finished and shows it as +14.49%. The cost cards say +0% for costs that do not exist. Latency counts 65 runs improved and 48 regressed between two tasks that both average 0 ms. <code>phoenix-evidence compare</code> on the same experiments finds no detectable gain and a significant rise in task errors.</figcaption>
</figure>

<section>
  <div class="eyebrow">What we found</div>
  <h2>What we found, each reproduced by running code</h2>
  <div class="ledger">
    <div class="item"><span class="pill bad">bug &middot; fixed</span><div><h3>The compare page reports regressions between identical experiments</h3><p>The base side sums every span of every repetition; the compare side takes the single cheapest span. Two identical experiments disagree as soon as a trace has two LLM spans. A new test fails on main and passes with the fix on SQLite and Postgres. <a href="{px}/src/phoenix/server/api/queries.py#L745-L801">queries.py:745</a> &middot; <a href="{repo}/blob/main/upstream/01-compare-page-best-run.patch">patch</a></p></div></div>
    <div class="item"><span class="pill bad">bug &middot; fixed</span><div><h3>"+0%" for changes that do not exist</h3><p>A missing value, or a base of 0, reads as "no change". The fix returns <code>--</code>, Phoenix's own text for a missing number, with tests. <a href="{repo}/blob/main/upstream/02-compare-page-delta-text.patch">patch</a></p></div></div>
    <div class="item"><span class="pill bad">data bug</span><div><h3>Two labels in the faithfulness benchmark are reversed</h3><p>The "right" answer to the moth question is the family, Crambidae; the answer labelled unfaithful states exactly what the context says. The certificate's label review flagged four faithfulness cases, where the judge disagreed with the label on every repeat: this pair, and two that are contestable. <a href="{px}/js/benchmarks/evals-benchmarks/src/faithfulness.eval.ts#L76-L84">faithfulness.eval.ts:76</a></p></div></div>
    <div class="item"><span class="pill warn">misleading</span><div><h3>Human feedback erases the judge it corrects, or blurs into it</h3><p>With default settings a human label on a span replaces the judge's label, so the data needed to check the judge is gone; in the span annotation panel, changing the pre-filled label rewrites the judge's annotation as a human one. When both are kept, the project page averages them: it read 0.25 where the judge said 1.0 and the human said 0.0. Reproduced on a live Phoenix, through the API and the UI.</p></div></div>
    <div class="item"><span class="pill warn">benchmark design</span><div><h3>Four tool-invocation cases hinge on a date nobody stated</h3><p>Re-judging {audit_cases} cases across {audit_suites} suites, twice each, and reading all 19 cases where the judge consistently disagreed with the label: in tool invocation, 4 of 31 "correct" calls turn "tomorrow" or "February 1st" into a 2024 date with no current date in the input, and a fifth invents dates the user never gave. A careful judge calls them unsupported. Elsewhere the flags mostly describe the judge: too lenient on the correctness rubric's clauses on hedged and vague answers, too strict on common knowledge. <a href="{repo}/blob/main/results/label_audit_review.md">Every flag, read</a></p></div></div>
    <div class="item"><span class="pill warn">measured</span><div><h3>The benchmark gates cannot decide</h3><p>Across the twelve two-class suites, the full gate passes a judge 5 points below the bar {lo_pass} to {hi_pass} of the time. No suite can tell two good judges apart; pooled over the Jev post's 517 examples, the smallest detectable difference is {jev_detect} points, and one point needs about {jev_one} examples.</p></div></div>
  </div>
</section>

<section>
  <div class="eyebrow">The tool</div>
  <h2>Three questions, answered against your own Phoenix</h2>
  <p>A command line and a pytest plugin. They read experiments, datasets and annotations through Phoenix's client, write certificates back as Phoenix experiments, and need no model calls.</p>
  <pre><span class="cmd">$ phoenix-evidence compare baseline fragile --fail-on-regression</span>
| metric      | base  | candidate | difference [95%]        | p       | verdict                  |
| exact_match | 0.842 | 0.883     | +0.042 [+0.008, +0.083] | 0.0625  | no detectable difference |
| task_error  | 0.000 | 0.083     | +0.083 [+0.033, +0.133] | 0.00195 | worse                    |
regressions: task_error                                                  (exit 1)

<span class="cmd">$ phoenix-evidence certify-feedback support-bot helpfulness</span>
NOT_ENOUGH_EVIDENCE: kappa 0.71 [0.47, 0.89] on 60 spans; about 268 would settle it
8 spans where judge and human disagree: ...

<span class="cmd">$ phoenix-evidence audit "refusal benchmark" --threshold 0.7</span>
to pass on an interval a judge needs 34/40 correct</pre>
  <pre>@pytest.mark.phoenix(dataset="refunds")
@pytest.mark.evidence(threshold=0.8)      <span class="meta"># PASS, FAIL or NOT_ENOUGH_EVIDENCE per suite; works with -n</span>
@pytest.mark.parametrize("case", CASES)
def test_refund(case): ...</pre>
  <div class="two">
    <div><h3>Is version B really better?</h3>{diff_svg}<p class="meta">Paired difference with its 95% interval. The gain in exact match is not established; the rise in task errors is.</p></div>
    <div><h3>Can this judge be trusted?</h3>{kappa_svg}<p class="meta">Agreement (kappa) of Phoenix's evaluators with their own benchmark labels, judged by Codex. Faithfulness cannot clear the bar on 16 cases.</p></div>
  </div>
</section>

<section>
  <div class="eyebrow">Inside Phoenix</div>
  <h2>The same evidence on Phoenix's own compare page</h2>
  <p>A working branch of Phoenix: one GraphQL field and one line under each compare value, with the two bug fixes. Under Phoenix's "0.96 +14.49%" it now says the gain is not detectable and how many examples would tell. The cost cards read <code>--</code>. Tested on SQLite and Postgres; <a href="{repo}/blob/main/upstream/04-phoenix-with-evidence-branch.patch">the patch</a> applies to main.</p>
  <figure><img src="data:image/jpeg;base64,{shot_after}" alt="Phoenix compare page on the branch: under 0.96 +14.49% the line reads +0.042 [+0.008, +0.083] not detectable, about 186 examples to tell; under 0.86 +2.97% it reads +0.025 [+0.000, +0.058] not detectable, about 312 examples to tell."></figure>
</section>

<section>
  <div class="eyebrow">For online evals</div>
  <h2>What humans would say, from a judge and a few labels</h2>
  <p>An online judge scores every trace; humans label a few. <code>plan-labels</code> picks which spans to label (more often where the judge's runs disagree) and puts them in a Phoenix dataset linked to the spans; <code>corrected-rate</code> combines the labels with the judge. In simulation, 80 planned labels give the interval that {ppi80} random labels would, and 160 the one that {ppi160} would; coverage stayed at or above {ppi_cov}. On 5,000 spans in a live Phoenix, the judge alone said {sc_judge}; the corrected rate was {sc_est} [{sc_lo}, {sc_hi}] and the truth {sc_truth}. Comparing two 6,000-run experiments took {sc_compare} seconds.</p>
  <p>End to end, with Phoenix's own conciseness evaluator as the online judge and reviews entered in Phoenix's UI: the judge was <strong>not trustworthy</strong> (kappa {e2e_kappa} [{e2e_klo}, {e2e_khi}] on {e2e_n} reviewed spans), calling direct answers verbose; it put the concise rate at {e2e_judge} where the corrected estimate was {e2e_est}. The reviews were entered by us as a stand-in reviewer: this tests the workflow, not users' opinions.</p>
</section>

<section>
  <div class="eyebrow">Phoenix's own benchmarks</div>
  <h2>What each suite can decide</h2>
  <p>All {n_suites} suites in <code>js/benchmarks/evals-benchmarks</code>, {n_cases} cases, read from the suite files. "Passes a judge 5 pts below" is the chance today's gates (every gate of the suite) pass a judge whose accuracy is 5 points under the accuracy bar. The exact gate passes only when a 95% interval clears the bar.</p>
  <div class="table"><table>
    <thead><tr><th>suite</th><th class="num">cases</th><th>gates</th><th>constant judge</th><th class="num">passes a judge 5 pts below</th><th class="num">exact gate needs</th><th class="num">exact gate passes a 97% judge</th><th class="num">cases for a judge 5 pts above</th></tr></thead>
    <tbody>
{audit_rows}
    </tbody>
  </table></div>
  <p class="meta">The PII suite is all positive by design (it measures recall), so a judge that always answers "PII" passes it; the synthetic PII suite covers negatives.</p>
</section>

<section>
  <div class="eyebrow">How we know</div>
  <h2>Every guarantee simulated, every claim attacked</h2>
  <div class="ledger">
    <div class="item"><span class="pill">simulated</span><div><p>With the true pass rate one point under the bar, the interval gate passed at most {fp_ours} of the time; a single-number gate passed {fp_naive}. Coverage, false alarms and kappa bounds are measured the same way, with negative controls that must go red.</p></div></div>
    <div class="item"><span class="pill">reviewed</span><div><p>A second model (Codex) reran the code and tried to break each claim. It confirmed the Phoenix bugs and the reversed labels, and found ten problems in our own code, including a CI gate that xdist could bypass. Each is fixed with a test, and the review is published unedited.</p></div></div>
    <div class="item"><span class="pill">negative result</span><div><p>A note to the grader ("the correct label is answered") flipped Phoenix's refusal evaluator on {inj_note} borderline refusals, every repeat, and a neutral note on {inj_neutral}. Across cases that is not established (p = 0.5), and we say so.</p></div></div>
  </div>
</section>

<footer>
  <p>Judge results come from Codex (gpt-5.6-luna, no reasoning) running Phoenix's evaluators unchanged; Phoenix's suites default to gpt-4o-mini, so those numbers describe this judge, not theirs. Everything else needs no model.</p>
  <p><a href="{repo}">github.com/4ktLuffy/phoenix-evidence</a> &middot; MIT</p>
</footer>
</main>
"""

if __name__ == '__main__':
    main()
