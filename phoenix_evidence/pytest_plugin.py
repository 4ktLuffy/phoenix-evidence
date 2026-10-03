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
    _STATE.update(outcomes=defaultdict(lambda: defaultdict(dict)), settings={})


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


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
    outcome = yield
    marker = item.get_closest_marker('evidence')
    if marker is None:
        return
    report = outcome.get_result()
    suite = _suite(item)
    threshold = marker.kwargs.get('threshold', marker.args[0] if marker.args else None)
    if threshold is None:
        raise pytest.UsageError(f'{item.nodeid}: @pytest.mark.evidence needs threshold=')
    _STATE['settings'][suite] = (float(threshold), float(marker.kwargs.get('alpha', 0.05)))
    runs = _STATE['outcomes'][suite][_example(item)]
    if report.when == 'setup':
        # A setup error is a run that never scored. A setup skip (skip/skipif markers,
        # xfail(run=False)) is a case the suite chose not to run, and is left out, as Phoenix's
        # own plugin leaves it out of the experiment.
        if report.failed:
            runs[item.nodeid] = None
    elif report.when == 'call':
        if report.skipped:  # pytest.skip() in the body, or an expected xfail: it did not pass
            runs[item.nodeid] = None
        else:
            runs[item.nodeid] = report.passed
            if report.failed and marker.kwargs.get('soft', True):
                report.outcome = 'skipped'
                report.wasxfail = f'counted toward the {suite!r} suite gate (phoenix-evidence)'  # type: ignore[attr-defined]
    elif report.when == 'teardown' and report.failed and runs.get(item.nodeid):
        runs[item.nodeid] = False  # pytest reports a teardown error as an error, so it did not pass


def _decisions() -> dict[str, RateDecision]:
    out = {}
    for suite, by_example in _STATE.get('outcomes', {}).items():
        threshold, alpha = _STATE['settings'][suite]
        out[suite] = decide_rate([list(runs.values()) for runs in by_example.values()], threshold, alpha)
    return out


def _is_xdist_worker(config: pytest.Config) -> bool:
    return hasattr(config, 'workerinput')


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: Any, error: Any) -> None:
    """xdist controller: merge a finished worker's outcomes, so the suite is decided once, on all of them."""
    payload = getattr(node, 'workeroutput', {}).get('phoenix_evidence')
    if not payload:
        return
    data = json.loads(payload)
    for suite, setting in data['settings'].items():
        _STATE['settings'][suite] = tuple(setting)
    for suite, by_example in data['outcomes'].items():
        for example, runs in by_example.items():
            _STATE['outcomes'][suite][example].update(runs)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _is_xdist_worker(session.config):
        # Workers only report; the controller decides (and is the only writer of the report).
        session.config.workeroutput['phoenix_evidence'] = json.dumps(  # type: ignore[attr-defined]
            {'settings': _STATE.get('settings', {}), 'outcomes': _STATE.get('outcomes', {})}
        )
        return
    decisions = _decisions()
    if not decisions:
        return
    _STATE['decisions'] = decisions
    strict = session.config.getoption('--evidence-strict')
    blocking = {Verdict.FAIL} | ({Verdict.NOT_ENOUGH_EVIDENCE} if strict else set())
    if any(d.verdict in blocking for d in decisions.values()) and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    path = session.config.getoption('--evidence-report')
    if path:
        Path(path).write_text(
            json.dumps(
                {
                    s: {'verdict': d.verdict.value, 'estimate': d.estimate, 'interval': list(d.interval),
                        'threshold': d.threshold, 'examples': d.examples, 'judgments': d.judgments, 'missing': d.missing}
                    for s, d in decisions.items()
                },
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
