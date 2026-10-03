"""A suite-level gate for Phoenix's pytest integration that can say "not enough evidence".

    @pytest.mark.phoenix(dataset='refunds', repetitions=3)
    @pytest.mark.evidence(threshold=0.8)
    @pytest.mark.parametrize('case', CASES)
    def test_refund(case): ...

Each test that carries `@pytest.mark.evidence` is one judgment toward its suite, not a hard gate:
a failing case is shown as an expected miss (`x`, with the reason) and the suite verdict decides
the session. Phoenix's own plugin still records the case's real outcome, because this hook runs
outermost and changes the report only after Phoenix's has read it. Pass `soft=False` to keep
pytest's rule that any failing case fails the session.

Each such test counts toward its suite (the Phoenix dataset name
when `@pytest.mark.phoenix` is present, else the test file). Repetitions of one example count as
one example. A test that errors or is skipped after starting counts as a failure, not as a
missing run. At the end of the session each suite is decided on an exact interval:

    PASS                 the pass rate is shown to be at least the threshold
    FAIL                 it is shown to be below: the session fails
    NOT_ENOUGH_EVIDENCE  neither: reported, and the session fails only with --evidence-strict

Phoenix's spec for this harness deferred an aggregate gate "so it can be designed properly on
its own later" (internal_docs/specs/pytest-eval-ci.md); this is one design, measured in
bench/coverage.py.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from phoenix_evidence._gate import RateDecision, Verdict, decide_rate

_REP = re.compile(r'(^|-)phxrep\d+(-|$)')
_STATE: dict[str, Any] = {}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup('phoenix-evidence')
    group.addoption('--evidence-strict', action='store_true', help='fail the session on NOT_ENOUGH_EVIDENCE too')
    group.addoption('--evidence-report', default=None, help='write the suite decisions to this JSON file')


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        'markers', 'evidence(threshold, alpha=0.05, soft=True): gate the suite on an interval, not each case'
    )
    _STATE.clear()
    # suite -> example -> test node id -> outcome (True, False, or None for a run that never scored)
    _STATE.update(outcomes=defaultdict(lambda: defaultdict(dict)), settings={}, lost=[], config=config)


def _suite(item: pytest.Item) -> str:
    marker = item.get_closest_marker('phoenix')
    if marker is not None and marker.kwargs.get('dataset'):
        return str(marker.kwargs['dataset'])
    return re.sub(r'\.py$', '', item.nodeid.split('::', 1)[0])


def _example(item: pytest.Item) -> str:
    """The test's id with Phoenix's repetition parameter removed, so repetitions group together."""
    match = re.search(r'\[(.*)\]$', item.nodeid)
    if not match:
        return item.nodeid
    params = _REP.sub(lambda m: '-' if m.group(1) and m.group(2) else '', match.group(1)).strip('-')
    return item.nodeid[: match.start()] + (f'[{params}]' if params else '')


_PROPERTY = 'phoenix_evidence'


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
    """Attach each phase's outcome to its own report.

    Reports travel to the xdist controller one by one, so the outcome cannot be lost with a worker
    that dies before the end of the session; the controller (or the single process) records it in
    `pytest_runtest_logreport`. Runs outermost, after Phoenix's own hook has read the report.
    """
    outcome = yield
    marker = item.get_closest_marker('evidence')
    if marker is None:
        return
    report = outcome.get_result()
    suite = _suite(item)
    threshold = marker.kwargs.get('threshold', marker.args[0] if marker.args else None)
    if threshold is None:
        raise pytest.UsageError(f'{item.nodeid}: @pytest.mark.evidence needs threshold=')
    value: bool | None | str
    if report.when == 'setup':
        # A setup error is a run that never scored. A setup skip (skip/skipif markers,
        # xfail(run=False)) is a case the suite chose not to run, and is left out, as Phoenix's
        # own plugin leaves it out of the experiment.
        if not report.failed:
            return
        value = None
    elif report.when == 'call':
        if report.skipped:  # pytest.skip() in the body, or an expected xfail: it did not pass
            value = None
        else:
            value = report.passed
            if report.failed and marker.kwargs.get('soft', True):
                report.outcome = 'skipped'
                report.wasxfail = f'counted toward the {suite!r} suite gate (phoenix-evidence)'  # type: ignore[attr-defined]
    elif report.when == 'teardown' and report.failed:
        value = 'teardown_failed'  # pytest reports it as an error, so a passing call did not pass
    else:
        return
    report.user_properties.append(
        (
            _PROPERTY,
            json.dumps(
                {
                    'suite': suite,
                    'example': _example(item),
                    'threshold': float(threshold),
                    'alpha': float(marker.kwargs.get('alpha', 0.05)),
                    'value': value,
                }
            ),
        )  # fmt: skip
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    config = _STATE.get('config')
    if config is None or _is_xdist_worker(config):
        return  # workers only attach outcomes; the controller (or the single process) records them
    payload = next((v for k, v in report.user_properties if k == _PROPERTY), None)
    if payload is None:
        if report.failed and 'crashed' in str(getattr(report, 'longrepr', '')):
            _STATE['lost'].append(report.nodeid)  # a worker died: its outcome never arrived
        return
    data = json.loads(payload)
    _STATE['settings'][data['suite']] = (data['threshold'], data['alpha'])
    runs = _STATE['outcomes'][data['suite']][data['example']]
    if data['value'] == 'teardown_failed':
        if runs.get(report.nodeid):
            runs[report.nodeid] = False
    else:
        runs[report.nodeid] = data['value']


def _decisions() -> dict[str, RateDecision]:
    out = {}
    for suite, by_example in _STATE.get('outcomes', {}).items():
        threshold, alpha = _STATE['settings'][suite]
        out[suite] = decide_rate([list(runs.values()) for runs in by_example.values()], threshold, alpha)
    return out


def _is_xdist_worker(config: pytest.Config) -> bool:
    return hasattr(config, 'workerinput')


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _is_xdist_worker(session.config):
        return  # the controller decides, and is the only writer of the report
    decisions = _decisions()
    if not decisions:
        return
    _STATE['decisions'] = decisions
    strict = session.config.getoption('--evidence-strict')
    blocking = {Verdict.FAIL} | ({Verdict.NOT_ENOUGH_EVIDENCE} if strict else set())
    lost = _STATE.get('lost', [])
    if (lost or any(d.verdict in blocking for d in decisions.values())) and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    path = session.config.getoption('--evidence-report')
    if path:
        Path(path).write_text(
            json.dumps(
                {
                    s: {'verdict': d.verdict.value, 'estimate': d.estimate, 'interval': list(d.interval),
                        'threshold': d.threshold, 'examples': d.examples, 'judgments': d.judgments, 'missing': d.missing}
                    for s, d in decisions.items()
                } | ({'_incomplete': {'lost_test_reports': lost}} if lost else {}),
                indent=1,
            )
        )  # fmt: skip


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    decisions = _STATE.get('decisions')
    if not decisions:
        return
    terminalreporter.section('phoenix-evidence')
    for suite, decision in sorted(decisions.items()):
        terminalreporter.write_line(f'{suite}: {decision}')
    lost = _STATE.get('lost', [])
    if lost:
        terminalreporter.write_line(
            f'incomplete: {len(lost)} test reports were lost with a crashed worker; the decisions above omit them'
        )
