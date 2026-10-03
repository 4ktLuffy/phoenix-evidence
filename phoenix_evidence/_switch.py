"""Before you switch judges (a new model, an edited prompt): what would change, on evidence?

Phoenix keys an online evaluator's annotations by a fingerprint of its configuration, so editing
the judge starts a new history and old and new scores are no longer comparable (Phoenix #15531).
This answers, on a sample both judges score, the three questions that decide a switch:

- how often the new judge disagrees with the old one (the share of verdicts that would flip);
- how the pass rate would move (a paired difference, so the movement is the judges', not traffic);
- if some of the sample has human labels, which judge agrees with the humans more (paired).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from phoenix_evidence._compare import Comparison, compare
from phoenix_evidence._intervals import clopper_pearson


@dataclass(frozen=True)
class SwitchImpact:
    items: int
    flips: int
    flip_interval: tuple[float, float]
    pass_rate: Comparison
    human_agreement: Comparison | None
    flipped_items: list[str]

    def __str__(self) -> str:
        lo, hi = self.flip_interval
        lines = [
            f'{self.flips}/{self.items} verdicts would change [{lo:.3f}, {hi:.3f}]',
            f'pass rate, new minus old: {self.pass_rate.difference:+.3f} '
            f'[{self.pass_rate.interval[0]:+.3f}, {self.pass_rate.interval[1]:+.3f}], {self.pass_rate.direction.value}',
        ]
        if self.human_agreement is not None:
            h = self.human_agreement
            lines.append(
                f'agreement with humans, new minus old, on {h.examples} labelled items: {h.difference:+.3f} '
                f'[{h.interval[0]:+.3f}, {h.interval[1]:+.3f}], {h.direction.value}'
            )
        return '\n'.join(lines)


def switch_impact(
    old: Mapping[str, str],
    new: Mapping[str, str],
    pass_label: str,
    human: Mapping[str, str] | None = None,
    alpha: float = 0.05,
) -> SwitchImpact:
    """Compare two judges' labels on the items both scored (and, where given, against human labels)."""
    shared = sorted(set(old) & set(new))
    if not shared:
        raise ValueError('the two judges share no scored items')
    flipped = [k for k in shared if old[k] != new[k]]
    rate = compare(
        {k: [float(old[k] == pass_label)] for k in shared},
        {k: [float(new[k] == pass_label)] for k in shared},
        alpha=alpha,
    )
    agreement = None
    if human:
        labelled = [k for k in shared if k in human]
        if labelled:
            agreement = compare(
                {k: [float(old[k] == human[k])] for k in labelled},
                {k: [float(new[k] == human[k])] for k in labelled},
                alpha=alpha,
            )
    return SwitchImpact(
        items=len(shared),
        flips=len(flipped),
        flip_interval=clopper_pearson(len(flipped), len(shared), alpha),
        pass_rate=rate,
        human_agreement=agreement,
        flipped_items=flipped,
    )
