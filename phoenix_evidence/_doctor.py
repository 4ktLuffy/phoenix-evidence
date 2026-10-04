"""What is wrong with this labelled dataset before anyone trusts a score on it?

Checks that a pass rate cannot show: the same example twice (it counts double), near-copies with
different labels (a label error, or a deliberate minimal pair worth knowing about), copies across
splits (the test split leaks into the one used for tuning), examples in more than one split, and
missing labels. Class balance and the constant-judge check come from `audit_labels`.

Near-copies are found by word 3-gram Jaccard similarity over every pair, which is exact and fine
for a few thousand examples; above `max_pairs_examples` only exact copies are checked. One changed
word moves three 3-grams, so in short texts (under about 40 words) a one-word minimal pair falls
below the default similarity of 0.8.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

# Numbers keep their inner punctuation: '1.0' and '1,0' (or 10:30 and 10.30) are different texts (review 3).
_WORD = re.compile(r'\w+(?:[.,:/-]\w+)*')


@dataclass(frozen=True)
class Example:
    id: str
    input: Mapping[str, Any]
    label: str | None
    splits: tuple[str, ...] = ()


def _text(payload: Mapping[str, Any]) -> str:
    return ' '.join(str(payload[k]) for k in sorted(payload))


def _normal(payload: Mapping[str, Any]) -> str:
    return ' '.join(_WORD.findall(_text(payload).lower()))


def _shingles(normal: str, k: int = 3) -> frozenset[str]:
    words = normal.split()
    if len(words) < k:
        return frozenset([normal])
    return frozenset(' '.join(words[i : i + k]) for i in range(len(words) - k + 1))


def _n(count: int, one: str, many: str) -> str:
    return f'{count} {one if count == 1 else many}'


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


@dataclass
class Diagnosis:
    examples: int
    exact_copies: list[list[str]] = field(default_factory=list)  # groups of ids, same text
    near_copies: list[tuple[str, str, float]] = field(default_factory=list)  # (id, id, similarity)
    conflicting: list[tuple[str, str, float]] = field(default_factory=list)  # copies or near-copies, labels differ
    cross_split: list[tuple[str, str, float]] = field(default_factory=list)  # copies in different splits
    in_several_splits: list[str] = field(default_factory=list)
    unlabelled: list[str] = field(default_factory=list)
    near_copy_check: bool = True
    labels: dict[str, Any] | None = None  # audit_labels, when a threshold is given

    def problems(self) -> list[str]:
        out = []
        if self.exact_copies:
            extra = sum(len(g) - 1 for g in self.exact_copies)
            out.append(
                f'{_n(extra, "example is an exact copy", "examples are exact copies")} of another: each counts twice'
            )
        if self.conflicting:
            out.append(f'{_n(len(self.conflicting), "pair", "pairs")} of (near-)copies with different labels: '
                       'a label error, or a deliberate minimal pair')  # fmt: skip
        if self.cross_split:
            out.append(f'{_n(len(self.cross_split), "pair", "pairs")} of (near-)copies in different splits: '
                       'one split leaks into the other')  # fmt: skip
        if self.in_several_splits:
            out.append(f'{_n(len(self.in_several_splits), "example is", "examples are")} in more than one split')
        if self.unlabelled:
            out.append(f'{_n(len(self.unlabelled), "example has", "examples have")} no label')
        if not self.near_copy_check:
            out.append('too many examples for the pairwise near-copy check; only exact copies were checked')
        if self.labels:
            out += self.labels['warnings']
        return out

    def __str__(self) -> str:
        found = self.problems()
        head = f'{self.examples} examples: '
        return head + ('no problems found' if not found else '; '.join(found))


def diagnose(
    examples: Sequence[Example],
    similar: float = 0.8,
    threshold: float | None = None,
    alpha: float = 0.05,
    max_pairs_examples: int = 4000,
) -> Diagnosis:
    """Diagnose a labelled dataset. `similar` is the Jaccard similarity that counts as a near-copy;
    `threshold`, when given, is the pass bar a judge must clear on this dataset (adds `audit_labels`)."""
    from phoenix_evidence.phoenix import audit_labels

    d = Diagnosis(len(examples))
    normal = [_normal(e.input) for e in examples]
    groups: dict[str, list[int]] = defaultdict(list)
    for i, text in enumerate(normal):
        groups[text].append(i)
    d.exact_copies = [[examples[i].id for i in g] for g in groups.values() if len(g) > 1]
    pairs: list[tuple[int, int, float]] = [(i, j, 1.0) for g in groups.values() for i, j in combinations(g, 2)]
    if len(examples) <= max_pairs_examples:
        reps = [g[0] for g in groups.values()]
        shingles = {i: _shingles(normal[i]) for i in reps}
        for a, b in combinations(reps, 2):
            s = jaccard(shingles[a], shingles[b])
            if s >= similar:
                for i in groups[normal[a]]:
                    for j in groups[normal[b]]:
                        pairs.append((min(i, j), max(i, j), s))
                d.near_copies.append((examples[a].id, examples[b].id, round(s, 3)))
    else:
        d.near_copy_check = False
    for i, j, s in pairs:
        ei, ej = examples[i], examples[j]
        if ei.label is not None and ej.label is not None and ei.label != ej.label:
            d.conflicting.append((ei.id, ej.id, round(s, 3)))
        if ei.splits and ej.splits and set(ei.splits) != set(ej.splits):
            d.cross_split.append((ei.id, ej.id, round(s, 3)))
    d.in_several_splits = [e.id for e in examples if len(set(e.splits)) > 1]
    d.unlabelled = [e.id for e in examples if e.label is None]
    if threshold is not None:
        labelled = [e.label for e in examples if e.label is not None]
        if labelled:
            d.labels = audit_labels(labelled, threshold, alpha)
    return d


def pair_accuracy(
    pairs: Sequence[tuple[str, str]], truth: Mapping[str, str], judged: Mapping[str, Sequence[str | None]]
) -> dict[str, float | int]:
    """Score a judge on minimal pairs: a pair counts only when the judge gets both members right.

    Per-case accuracy rewards a judge that labels both members of a pair the same way with 50%;
    per pair it scores 0, which is what it deserves on a pair built to tell the two apart.
    `judged[id]` holds one label per repetition; repetition r of a pair uses repetition r of each.
    """
    cases = case_total = both = total = same_label = 0
    for a, b in pairs:
        # Only repetitions both members have are scored, for the case and the pair figures alike.
        for la, lb in zip(judged.get(a, []), judged.get(b, []), strict=False):
            total += 1
            case_total += 2
            cases += (la == truth[a]) + (lb == truth[b])
            both += la == truth[a] and lb == truth[b]
            same_label += la == lb
    return {'pairs': len(pairs), 'pair_judgments': total,
            'case_accuracy': cases / case_total if case_total else float('nan'),
            'pair_accuracy': both / total if total else float('nan'),
            'same_label_on_both': same_label / total if total else float('nan')}  # fmt: skip
