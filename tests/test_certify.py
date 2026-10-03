import asyncio
import random

from phoenix_evidence import Case, Trust, certify, grader_note, reformat, swapped_answer


def qa_cases(n: int = 80) -> list[Case]:
    # Even ids: the answer belongs to the question. Odd ids: it does not.
    cases = []
    for i in range(n):
        question = f'question {i}'
        answer = f'answer to question {i}' if i % 2 == 0 else f'answer to question {i + 1000}'
        cases.append(Case(str(i), {'input': question, 'output': answer}, 'correct' if i % 2 == 0 else 'incorrect'))
    return cases


def honest(payload) -> str:
    return (
        'correct'
        if payload['output'].split('[')[0].strip().split()[-1] == payload['input'].split()[-1]
        else 'incorrect'
    )


def run(judge, cases, **kw):
    async def wrapped(payload):
        return judge(payload)

    controls = [reformat(), grader_note('correct'), swapped_answer('incorrect')]
    return asyncio.run(certify(wrapped, cases, controls=controls, **kw))


def test_sound_judge_is_trustworthy():
    cert = run(honest, qa_cases())
    assert cert.verdict is Trust.TRUSTWORTHY, cert


def test_constant_judge_is_not_trustworthy():
    cert = run(lambda p: 'correct', qa_cases())
    assert cert.verdict is Trust.NOT_TRUSTWORTHY
    assert {c.name: c.status for c in cert.checks}['agreement'] is Trust.NOT_TRUSTWORTHY


def test_judge_that_obeys_the_grader_note_is_caught():
    def obedient(payload):
        return 'correct' if 'verified' in payload['output'] else honest(payload)

    cert = run(obedient, qa_cases())
    status = {c.name: c.status for c in cert.checks}
    assert status['grader_note'] is Trust.NOT_TRUSTWORTHY
    assert status['agreement'] is Trust.TRUSTWORTHY  # agreement alone would have passed it
    assert cert.verdict is Trust.NOT_TRUSTWORTHY


def test_coin_flipping_judge_fails_consistency():
    rng = random.Random(0)

    def flaky(payload):
        label = honest(payload)
        return label if rng.random() < 0.7 else ('incorrect' if label == 'correct' else 'correct')

    cert = run(flaky, qa_cases(), repeats=3)
    assert {c.name: c.status for c in cert.checks}['consistency'] is Trust.NOT_TRUSTWORTHY


def test_few_labels_give_not_enough_evidence_and_a_label_estimate():
    rng = random.Random(1)

    def decent(payload):
        label = honest(payload)
        return label if rng.random() < 0.9 else ('incorrect' if label == 'correct' else 'correct')

    cert = run(decent, qa_cases(12), repeats=1)
    assert cert.verdict is Trust.NOT_ENOUGH_EVIDENCE


def test_errors_are_counted_not_hidden():
    def broken(payload):
        raise RuntimeError('provider down')

    cert = run(broken, qa_cases(10))
    assert cert.errors == cert.calls
    assert cert.verdict is not Trust.TRUSTWORTHY


def test_label_review_lists_consistent_disagreements():
    cases = qa_cases(20)
    wrong = {'0', '2'}  # these two human labels are reversed
    cases = [
        Case(
            c.id,
            c.input,
            ('incorrect' if c.human_label == 'correct' else 'correct') if c.id in wrong else c.human_label,
        )
        for c in cases
    ]
    cert = run(honest, cases)
    assert {r['case'] for r in cert.label_review()} == wrong
