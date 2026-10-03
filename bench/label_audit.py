"""Which labels in Phoenix's benchmark suites look wrong? Every suite's cases through its own evaluator, twice.

    uv run --extra phoenix python bench/label_audit.py [suite ...]

For each suite, the matching phoenix-evals Python evaluator (unchanged, on Codex) judges every case
twice. Cases where the judge gives the same answer both times and the suite's label says otherwise
are flagged for a human to read: either the judge is consistently wrong there, or the label is.
The flag finds candidates; deciding which is a person's job, recorded in results/label_audit_review.md.

The Nemotron PII suite is left out: all 150 cases are positive by design, and its synthetic
records would be quoted into the cached explanations. Judgments are cached in results/judgments/,
as in bench/certify_phoenix_suites.py. Writes results/label_audit.json.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import EFFORT, MODEL, OUT, SUITES, CachedJudge, load_inputs  # noqa: E402
from phoenix.evals import LLM  # noqa: E402
from phoenix.evals.metrics.completeness import CompletenessEvaluator  # noqa: E402
from phoenix.evals.metrics.correctness import CorrectnessEvaluator  # noqa: E402
from phoenix.evals.metrics.hallucination import HallucinationEvaluator  # noqa: E402
from phoenix.evals.metrics.pii_detection import PiiDetectionEvaluator  # noqa: E402
from phoenix.evals.metrics.retrieval_relevance import RetrievalRelevanceEvaluator  # noqa: E402
from phoenix.evals.metrics.tool_invocation import ToolInvocationEvaluator  # noqa: E402
from phoenix.evals.metrics.tool_response_handling import ToolResponseHandlingEvaluator  # noqa: E402
from phoenix.evals.metrics.toxicity import ToxicityEvaluator  # noqa: E402
from phoenix.evals.metrics.user_friction import UserFrictionEvaluator  # noqa: E402

from phoenix_evidence import Case, certify  # noqa: E402

AUDIT: dict[str, dict[str, Any]] = {
    'completeness': {'evaluator': CompletenessEvaluator, 'to_input': lambda i: {'conversation': i['conversation']}},
    'correctness': {'evaluator': CorrectnessEvaluator, 'to_input': lambda i: {'input': i['question'], 'output': i['answer']}},
    'hallucination': {'evaluator': HallucinationEvaluator, 'to_input': lambda i: {'input': i['input'], 'output': i['output']}},
    'pii_detection.synthetic': {'evaluator': PiiDetectionEvaluator, 'to_input': lambda i: {'conversation': i['conversation']}},
    'retrieval_relevance': {'evaluator': RetrievalRelevanceEvaluator, 'to_input': lambda i: {'input': i['input'], 'context': i['context']}},
    'tool_invocation': {
        'evaluator': ToolInvocationEvaluator,
        'to_input': lambda i: {'input': i['input'], 'available_tools': i['availableTools'], 'tool_selection': i['toolSelection']},
    },
    'tool_response_handling': {
        'evaluator': ToolResponseHandlingEvaluator,
        'to_input': lambda i: {'input': i['input'], 'tool_call': i['toolCall'], 'tool_result': i['toolResult'], 'output': i['output']},
    },
    'toxicity': {'evaluator': ToxicityEvaluator, 'to_input': lambda i: {'text': i['text']}},
    'user_friction': {'evaluator': UserFrictionEvaluator, 'to_input': lambda i: {'conversation': i['conversation'], 'user_message': i['userMessage']}},
    **{k: {'evaluator': v['evaluator'], 'to_input': v['to_input']} for k, v in SUITES.items()},
}  # fmt: skip


def explanations(judge: CachedJudge, payload: dict[str, Any]) -> list[str]:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return [row['explanation'] or '' for key, row in judge.cache.items() if key.startswith(digest + ':')]


async def main(names: list[str]) -> None:
    suites = json.loads((OUT.parent / 'bench' / 'phoenix_suites' / 'suites.json').read_text())
    llm = LLM(provider='codex', model=MODEL, effort=EFFORT)
    path = OUT / 'label_audit.json'
    results = json.loads(path.read_text()) if path.exists() else {}
    for name in names:
        spec = AUDIT[name]
        data = suites['suites'][f'{name}.eval.ts']
        inputs = load_inputs(f'{name}.eval.ts')
        cases = [
            Case(str(i), spec['to_input'](inp), str(label))
            for i, (inp, label) in enumerate(zip(inputs, data['truth'], strict=True))
        ]
        judge = CachedJudge(name, spec['evaluator'](llm=llm))
        cert = await certify(
            judge, cases, repeats=2, judge_name=f'{spec["evaluator"].__name__} on codex:{MODEL}@{EFFORT}', concurrency=8
        )
        flagged = []
        for item in cert.label_review():
            case = cases[int(item['case'])]
            flagged.append({**item, 'category': data['categories'][int(item['case'])],
                            'judge_explanations': explanations(judge, dict(case.input))})  # fmt: skip
        results[name] = {
            'cases': len(cases), 'calls': cert.calls, 'errors': cert.errors, 'accuracy': cert.agreement.accuracy,
            'kappa': cert.agreement.kappa, 'kappa_interval': list(cert.agreement.kappa_interval),
            'flagged': flagged, 'model': f'codex:{MODEL}@{EFFORT}', 'phoenix_commit': suites['phoenix_commit'],
        }  # fmt: skip
        print(f'{name}: {len(cases)} cases, accuracy {cert.agreement.accuracy:.2f}, kappa {cert.agreement.kappa}, '
              f'{len(flagged)} flagged, {judge.new_calls} new calls', flush=True)  # fmt: skip
        path.write_text(json.dumps(results, indent=1))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:] or list(AUDIT)))
