"""Certify Phoenix's own evaluators on Phoenix's own benchmark cases, with Codex as the model.

    uv run --extra phoenix python bench/certify_phoenix_suites.py [suite ...]

Cases and human labels come from js/benchmarks/evals-benchmarks (bench/phoenix_suites/suites.json);
the evaluator is the matching Python class from phoenix-evals, unchanged, with `LLM(provider='codex')`.
Every judgment is cached in results/judgments/<suite>.jsonl keyed by its input, so a rerun makes no
new calls, and each line records the model that produced it. Writes results/certificates.json.

The judge is Codex, not the gpt-4o-mini these suites default to, so the numbers are about this
judge and say nothing about theirs; the method is the same for any model.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix.evals import LLM  # noqa: E402
from phoenix.evals.metrics.conciseness import ConcisenessEvaluator  # noqa: E402
from phoenix.evals.metrics.faithfulness import FaithfulnessEvaluator  # noqa: E402
from phoenix.evals.metrics.refusal import RefusalEvaluator  # noqa: E402

import phoenix_evidence.codex  # noqa: E402,F401  (registers provider 'codex')
from phoenix_evidence import Case, certify, grader_note, reformat, swapped_answer  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'results'
MODEL, EFFORT = 'gpt-5.6-luna', 'none'

SUITES: dict[str, dict[str, Any]] = {
    'conciseness': {
        'evaluator': ConcisenessEvaluator,
        'to_input': lambda i: {'input': i['question'], 'output': i['answer']},
        'controls': lambda: [reformat(), grader_note('concise')],
    },
    'faithfulness': {
        'evaluator': FaithfulnessEvaluator,
        'to_input': lambda i: {'input': i['question'], 'context': i['context'], 'output': i['answer']},
        # An answer drawn from a different question and context is not supported by this context.
        'controls': lambda: [reformat(), grader_note('faithful'), swapped_answer('unfaithful')],
    },
    'refusal': {
        'evaluator': RefusalEvaluator,
        'to_input': lambda i: {'input': i['question'], 'output': i['answer']},
        'controls': lambda: [reformat(), grader_note('answered')],
    },
}


def load_inputs(suite_file: str) -> list[dict[str, Any]]:
    """Case inputs from bench/phoenix_suites/suites.inputs.json (not committed: it is Phoenix's own
    benchmark text). Regenerate with `PHOENIX=<checkout> npx tsx bench/phoenix_suites/extract.mjs`."""
    path = HERE / 'phoenix_suites' / 'suites.inputs.json'
    if not path.exists():
        raise SystemExit(f'{path} is missing: run bench/phoenix_suites/extract.mjs against a Phoenix checkout')
    return json.loads(path.read_text())['inputs'][suite_file]


class CachedJudge:
    """Phoenix evaluator behind a disk cache; repeats of one input are cached by repeat number."""

    def __init__(self, suite: str, evaluator: Any) -> None:
        self.path = OUT / 'judgments' / f'{suite}.jsonl'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                row = json.loads(line)
                self.cache[row['key']] = row
        self.evaluator = evaluator
        self.seen: dict[str, int] = {}
        self.new_calls = 0

    async def __call__(self, payload: dict[str, Any]) -> str | None:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        # Repeat number per input in this run, so repeats are distinct cached calls.
        n = self.seen.get(digest, 0)
        self.seen[digest] = n + 1
        key = f'{digest}:{n}'
        if key in self.cache:
            return self.cache[key]['label']
        started = time.time()
        try:
            scores = await self.evaluator.async_evaluate(payload)
            label, explanation, error = scores[0].label, scores[0].explanation, None
        except Exception as e:  # recorded, and counted as a failed call by certify
            label, explanation, error = None, None, repr(e)[:300]
        row = {'key': key, 'label': label, 'explanation': explanation, 'error': error,
               'model': f'codex:{MODEL}@{EFFORT}', 'seconds': round(time.time() - started, 1)}  # fmt: skip
        self.cache[key] = row
        self.new_calls += 1
        with self.path.open('a') as f:
            f.write(json.dumps(row) + '\n')
        if error:
            raise RuntimeError(error)
        return label


async def main(names: list[str]) -> None:
    suites = json.loads((HERE / 'phoenix_suites' / 'suites.json').read_text())
    llm = LLM(provider='codex', model=MODEL, effort=EFFORT)
    results_path = OUT / 'certificates.json'
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    for name in names:
        spec = SUITES[name]
        data = suites['suites'][f'{name}.eval.ts']
        cases = [Case(str(i), spec['to_input'](inp), str(label))
                 for i, (inp, label) in enumerate(zip(load_inputs(f'{name}.eval.ts'), data['truth'], strict=True))]  # fmt: skip
        judge = CachedJudge(name, spec['evaluator'](llm=llm))
        cert = await certify(
            judge,
            cases,
            controls=spec['controls'](),
            repeats=2,
            judge_name=f'{spec["evaluator"].__name__} on codex:{MODEL}@{EFFORT}',
            concurrency=8,
        )
        print(cert, f'\n  ({judge.new_calls} new calls)\n', flush=True)
        results[name] = {**cert.summary(), 'records': cert.records, 'phoenix_commit': suites['phoenix_commit']}
        results_path.write_text(json.dumps(results, indent=1))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:] or list(SUITES)))
