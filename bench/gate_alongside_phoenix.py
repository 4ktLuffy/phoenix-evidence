"""Check that the evidence gate and Phoenix's own pytest plugin agree on what happened.

    PHOENIX_BASE_URL=http://localhost:6006 uv run --extra phoenix --with pytest python bench/gate_alongside_phoenix.py

Runs a 30-case suite (3 cases fail) with both `@pytest.mark.phoenix` and `@pytest.mark.evidence`
against a running Phoenix, then reads the experiment back. The evidence gate shows the failing
cases as expected misses and decides the suite; Phoenix's plugin must still record those three
runs as failures, because the gate changes the pytest report only after Phoenix's hook has read
it. Writes results/gate_alongside_phoenix.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from phoenix.client import Client

OUT = Path(__file__).resolve().parent.parent / 'results'
SUITE = """
import pytest

@pytest.mark.phoenix(dataset='{dataset}')
@pytest.mark.evidence(threshold=0.6)
@pytest.mark.parametrize('i', range(30))
def test_case(i):
    assert i >= 3  # cases 0, 1, 2 fail
"""


def main() -> None:
    base_url = os.environ.get('PHOENIX_BASE_URL', 'http://localhost:6006')
    dataset = f'evidence-gate-check-{uuid.uuid4().hex[:8]}'
    with tempfile.TemporaryDirectory() as tmp:
        test_file = Path(tmp) / 'test_gate.py'
        test_file.write_text(SUITE.format(dataset=dataset))
        report = Path(tmp) / 'evidence.json'
        done = subprocess.run(
            [sys.executable, '-m', 'pytest', str(test_file), '-q', '-p', 'no:cacheprovider', '--rootdir', tmp,
             '--evidence-report', str(report)],
            capture_output=True, text=True, env={**os.environ, 'PHOENIX_BASE_URL': base_url},
        )  # fmt: skip
        decision = json.loads(report.read_text())[dataset]
    client = Client(base_url=base_url)
    ds = client.datasets.get_dataset(dataset=dataset)
    experiment = client.experiments.list(dataset_id=ds.id)[-1]
    ran = client.experiments.get_experiment(experiment_id=experiment['id'])
    runs = ran['task_runs']
    result = {
        'pytest_exit': done.returncode,
        'pytest_summary': done.stdout.strip().splitlines()[-1],
        'evidence_decision': decision,
        'phoenix_runs': len(runs),
        'phoenix_runs_recorded_as_failed': sum(1 for r in runs if r.get('error')),
    }
    print(json.dumps(result, indent=1))
    assert result['phoenix_runs'] == 30 and result['phoenix_runs_recorded_as_failed'] == 3, (
        'Phoenix lost the real outcome'
    )
    (OUT / 'gate_alongside_phoenix.json').write_text(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
