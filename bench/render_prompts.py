"""Render the exact prompts Phoenix's evaluators send, so another model can judge the same cases.

    uv run --extra phoenix python bench/render_prompts.py correctness hallucination tool_response_handling

Each suite's phoenix-evals evaluator runs unchanged against an adapter that records the prompt and
the output schema instead of calling a model. Writes results/scratch/prompts.jsonl (gitignored:
it contains Phoenix's benchmark text): one line per case with the suite, case index, prompt,
allowed labels and the cache key the label audit used, so the new judge's labels pair with the
frozen ones.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import OUT, SUITES, load_inputs  # noqa: E402
from label_audit import AUDIT  # noqa: E402
from phoenix.evals import LLM  # noqa: E402
from phoenix.evals.llm.registries import register_adapter, register_provider  # noqa: E402
from phoenix.evals.llm.types import BaseLLMAdapter  # noqa: E402

import phoenix_evidence.codex as codex  # noqa: E402

CAPTURED: list[dict[str, Any]] = []


class CaptureClient:
    model = 'capture'


def _labels(schema: dict[str, Any]) -> list[str]:
    label = schema.get('properties', {}).get('label', {})
    return list(label.get('enum') or [o.get('const') for o in label.get('oneOf', [])])


@register_adapter(identifier=lambda client: isinstance(client, CaptureClient), name='capture')
@register_provider(provider='capture', client_factory=lambda **kw: CaptureClient())
class CaptureAdapter(BaseLLMAdapter):
    @classmethod
    def client_name(cls) -> str:
        return 'capture'

    def generate_text(self, prompt: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    async def async_generate_text(self, prompt: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def generate_object(self, prompt: Any, schema: dict[str, Any], method: Any = None, **kwargs: Any) -> dict[str, Any]:
        labels = _labels(schema)
        CAPTURED.append({'prompt': codex._prompt_text(prompt), 'labels': labels, 'schema': schema})
        return {'explanation': 'captured', 'label': labels[0]}

    async def async_generate_object(
        self, prompt: Any, schema: dict[str, Any], method: Any = None, **kwargs: Any
    ) -> dict[str, Any]:
        return self.generate_object(prompt, schema, method, **kwargs)

    @property
    def model_name(self) -> str:
        return 'capture'


def main(names: list[str]) -> None:
    specs = {**AUDIT, **SUITES}
    llm = LLM(provider='capture', model='capture')
    rows = []
    for name in names:
        evaluator = specs[name]['evaluator'](llm=llm)
        for i, case in enumerate(load_inputs(f'{name}.eval.ts')):
            payload = specs[name]['to_input'](case)
            CAPTURED.clear()
            evaluator.evaluate(payload)
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            rows.append(
                {
                    'suite': name,
                    'case': i,
                    'key': digest,
                    'prompt': CAPTURED[0]['prompt'],
                    'labels': CAPTURED[0]['labels'],
                }
            )
    path = OUT / 'scratch' / 'prompts.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    print(f'{len(rows)} prompts -> {path}')


if __name__ == '__main__':
    main(sys.argv[1:])
