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

from phoenix_evidence._ppi import CorrectedRate, corrected_rate, plan_labels  # noqa: E402

__all__ += ['CorrectedRate', 'corrected_rate', 'plan_labels']
from phoenix_evidence._switch import SwitchImpact, switch_impact  # noqa: E402

__all__ += ['SwitchImpact', 'switch_impact']
from phoenix_evidence._canary import CanaryReport, canary, count_flips  # noqa: E402
from phoenix_evidence._doctor import Diagnosis, Example, diagnose, pair_accuracy  # noqa: E402
from phoenix_evidence._jury import Jury, jury  # noqa: E402
from phoenix_evidence._price import Price, price_of_certainty  # noqa: E402

__all__ += ['CanaryReport', 'Diagnosis', 'Example', 'Jury', 'Price', 'canary', 'count_flips', 'diagnose', 'jury',
            'pair_accuracy', 'price_of_certainty']  # fmt: skip
from phoenix_evidence._sequential import SequentialComparison  # noqa: E402

__all__ += ['SequentialComparison']
