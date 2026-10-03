import json

import pytest

SUITE = """
import pytest

@pytest.mark.evidence(threshold={threshold})
@pytest.mark.parametrize('i', range({n}))
def test_case(i):
    assert i >= {failures}
"""


def run(pytester: pytest.Pytester, n: int, failures: int, threshold: float, *args: str):
    pytester.makepyfile(test_suite=SUITE.format(n=n, failures=failures, threshold=threshold))
    report = pytester.path / 'evidence.json'
    result = pytester.runpytest('--evidence-report', str(report), *args)
    return result, json.loads(report.read_text())['test_suite']


def test_small_suite_that_passes_every_case_is_not_enough_evidence(pytester):
    # 16 cases, 13 pass: Phoenix's average gate at 0.7 says PASS (0.81); the interval cannot.
    result, decision = run(pytester, 16, 3, 0.7)
    assert decision['verdict'] == 'NOT_ENOUGH_EVIDENCE'
    result.stdout.fnmatch_lines(['*phoenix-evidence*', '*NOT_ENOUGH_EVIDENCE*'])


def test_strict_mode_fails_the_session_on_not_enough_evidence(pytester):
    # 15 of 16 pass: above the bar on a point estimate, not on the interval.
    pytester.makepyfile(test_suite=SUITE.format(n=16, failures=1, threshold=0.7))
    assert pytester.runpytest().ret == 0
    assert pytester.runpytest('--evidence-strict').ret != 0


def test_large_suite_clearly_above_the_bar_passes_despite_some_failing_cases(pytester):
    result, decision = run(pytester, 200, 4, 0.8)
    assert decision['verdict'] == 'PASS'
    assert result.ret == 0
    result.assert_outcomes(passed=196, xfailed=4)


def test_soft_false_keeps_hard_gates(pytester):
    pytester.makepyfile(
        test_suite=SUITE.format(n=200, failures=4, threshold=0.8).replace('threshold=0.8', 'threshold=0.8, soft=False')
    )
    assert pytester.runpytest().ret != 0


def test_clearly_below_the_bar_fails_the_session(pytester):
    result, decision = run(pytester, 100, 60, 0.8)
    assert decision['verdict'] == 'FAIL'
    assert result.ret != 0


def test_errors_in_setup_count_as_failures(pytester):
    pytester.makepyfile(
        test_suite="""
import pytest

@pytest.fixture
def broken():
    raise RuntimeError('provider down')

@pytest.mark.evidence(threshold=0.5)
@pytest.mark.parametrize('i', range(10))
def test_case(i, broken):
    assert True
"""
    )
    report = pytester.path / 'evidence.json'
    pytester.runpytest('--evidence-report', str(report))
    decision = json.loads(report.read_text())['test_suite']
    assert decision['missing'] == 10 and decision['verdict'] == 'FAIL'


def test_repetitions_count_as_one_example(pytester):
    pytester.makepyfile(
        test_suite="""
import pytest

@pytest.mark.evidence(threshold=0.5)
@pytest.mark.parametrize('rep', ['phxrep1', 'phxrep2', 'phxrep3'])
@pytest.mark.parametrize('i', range(10))
def test_case(i, rep):
    assert True
"""
    )
    report = pytester.path / 'evidence.json'
    pytester.runpytest('--evidence-report', str(report))
    decision = json.loads(report.read_text())['test_suite']
    assert decision['examples'] == 10 and decision['judgments'] == 30


def test_teardown_error_turns_a_pass_into_a_failure(pytester):
    pytester.makepyfile(
        test_suite="""
import pytest

@pytest.fixture
def leaky():
    yield
    raise RuntimeError('teardown')

@pytest.mark.evidence(threshold=0.5)
@pytest.mark.parametrize('i', range(10))
def test_case(i, leaky):
    assert True
"""
    )
    report = pytester.path / 'evidence.json'
    pytester.runpytest('--evidence-report', str(report))
    decision = json.loads(report.read_text())['test_suite']
    assert decision['estimate'] == 0 and decision['verdict'] == 'FAIL'


def test_marker_level_skips_are_left_out(pytester):
    pytester.makepyfile(
        test_suite="""
import pytest

@pytest.mark.evidence(threshold=0.5)
@pytest.mark.parametrize('i', range(10))
def test_case(i):
    if i < 3:
        pytest.skip('in-body skip: counts as not passing')
    assert True

@pytest.mark.evidence(threshold=0.5)
@pytest.mark.skip(reason='not run at all')
def test_skipped_by_marker():
    assert False
"""
    )
    report = pytester.path / 'evidence.json'
    pytester.runpytest('--evidence-report', str(report))
    decision = json.loads(report.read_text())['test_suite']
    assert decision['examples'] == 10 and decision['missing'] == 3


def test_xdist_workers_are_decided_together(pytester):
    pytest.importorskip('xdist')
    pytester.makepyfile(test_suite=SUITE.format(n=40, failures=40, threshold=0.8))
    report = pytester.path / 'evidence.json'
    result = pytester.runpytest_subprocess('-n', '2', '--evidence-strict', '--evidence-report', str(report))
    decision = json.loads(report.read_text())['test_suite']
    assert decision['examples'] == 40 and decision['verdict'] == 'FAIL'
    assert result.ret != 0
