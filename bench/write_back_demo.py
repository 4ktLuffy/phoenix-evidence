"""Write a certificate into a running Phoenix and read it back. No new model calls (cached judgments).

    PHOENIX_BASE_URL=http://localhost:6006 uv run --extra phoenix python bench/write_back_demo.py [suite]

Re-certifies one suite from results/judgments/ (the cache bench/certify_phoenix_suites.py wrote),
uploads its labelled cases as a dataset and the certificate as an experiment on it, then reads the
experiment back through the client to show what Phoenix stored. Writes results/write_back.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from certify_phoenix_suites import EFFORT, MODEL, OUT, SUITES, CachedJudge, load_inputs  # noqa: E402
from phoenix.client import Client  # noqa: E402
from phoenix.evals import LLM  # noqa: E402

from phoenix_evidence import Case, certify  # noqa: E402
from phoenix_evidence.phoenix import write_certificate  # noqa: E402


async def main(name: str) -> None:
    suites = json.loads((OUT.parent / 'bench' / 'phoenix_suites' / 'suites.json').read_text())
    spec = SUITES[name]
    data = suites['suites'][f'{name}.eval.ts']
    cases = [
        Case(str(i), spec['to_input'](inp), str(label))
        for i, (inp, label) in enumerate(zip(load_inputs(f'{name}.eval.ts'), data['truth'], strict=True))
    ]
    judge = CachedJudge(name, spec['evaluator'](llm=LLM(provider='codex', model=MODEL, effort=EFFORT)))
    cert = await certify(
        judge, cases, controls=spec['controls'](), repeats=2,
        judge_name=f'{spec["evaluator"].__name__} on codex:{MODEL}@{EFFORT}',
    )  # fmt: skip
    assert judge.new_calls == 0, 'expected every judgment to come from the cache'
    client = Client(base_url=os.environ.get('PHOENIX_BASE_URL', 'http://localhost:6006'))
    ids = write_certificate(client, cert, cases, dataset_name=f'{name} benchmark (phoenix-evidence)')
    stored = client.experiments.get_experiment(experiment_id=ids['experiment_id'])
    meta = stored['experiment_metadata'] if isinstance(stored, dict) else stored.experiment_metadata
    print(cert)
    print(json.dumps(ids, indent=1))
    print('verdict stored in Phoenix:', meta['phoenix_evidence_certificate']['verdict'])
    (OUT / 'write_back.json').write_text(json.dumps({**ids, 'stored_metadata': meta}, indent=1, default=str))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'refusal'))
