"""Evidence for the numbers Phoenix shows: can this judge be trusted, is B really better than A,
and can this suite decide at all."""

from phoenix_evidence._agreement import Agreement, agreement, balanced_accuracy, cohen_kappa
from phoenix_evidence._compare import Comparison, Direction, compare, holm, sign_flip_p_value
from phoenix_evidence._gate import ConstantJudgeCheck, RateDecision, Verdict, constant_judge, decide_rate
from phoenix_evidence._intervals import clopper_pearson, rate_interval, wilson
from phoenix_evidence._power import (
    detectable_difference,
    examples_to_pass,
    fail_probability,
    paired_examples_needed,
    pass_probability,
)

__all__ = [
    'Agreement', 'Comparison', 'ConstantJudgeCheck', 'Direction', 'RateDecision', 'Verdict', 'agreement',
    'balanced_accuracy', 'clopper_pearson', 'cohen_kappa', 'compare', 'constant_judge', 'decide_rate',
    'detectable_difference', 'examples_to_pass', 'fail_probability', 'holm', 'paired_examples_needed',
    'pass_probability', 'rate_interval', 'sign_flip_p_value', 'wilson',
]  # fmt: skip

from phoenix_evidence._certify import (  # noqa: E402
    Bars,
    Case,
    Certificate,
    Control,
    Trust,
    certify,
    grader_note,
    neutral_note,
    reformat,
    swapped_answer,
)

__all__ += [
    'Bars',
    'Case',
    'Certificate',
    'Control',
    'Trust',
    'certify',
    'grader_note',
    'neutral_note',
    'reformat',
    'swapped_answer',
]
