"""Diagnosis metrics (decisions 69-72; PROTOCOL, Diagnosis: Metrics). Builder side: cases
carry labels. Stubs for Raj; every function raises NotImplementedError until then.

A Case is one diagnosis by one method at one diagnosis time:
- a known-fault case: right is the right entry_id, family its family
- a leave-one-out case: right is None (the entry was removed), family is the case's family
- a false-alert case (a notification on a normal dev run): right and family are None, fault 0
The right answer is a decline exactly when right is None.

ranking is the method's output as tied blocks of entry_ids, best first, e.g.
(("a",), ("b", "c"), ("d",)): the matcher's blocks (decision 69), or a forest's classes
grouped by equal probability. declined says whether the method declined the case (decision
69's rule for the matcher, the top probability below its threshold for a forest).

Conventions (Claude's readings, to confirm):
- Credit for a tied block is decision 69's: if the right entry's block covers ranks a..b
  (m entries), top-k credit is 1 if k >= b, 0 if k < a, else (k - a + 1) / m. It's the
  same rule as app.diagnosis.matcher.credit (one engine), on entry_ids.
- A declined known-fault case gets no top-k and no family credit: a decline isn't an answer.
- Candidate recall ignores the decline: it measures whether the right entry is among the
  top k the matcher would hand on (PROTOCOL: candidate recall, and the top-k rule).
- Family credit for a tied top block is the share of the block in the case's family.
- Results are exact Fractions; an empty denominator raises ValueError.
"""

from dataclasses import dataclass
from fractions import Fraction

from types import SimpleNamespace

from app.diagnosis import matcher
from eval import metrics


@dataclass(frozen=True)
class Case:
    run: int                    # run number, for the bootstrap (decision 49, rule 3)
    fault: int                  # 0 for a false-alert case
    family: str | None          # the case's family; None for a false-alert case
    right: str | None           # the right entry_id; None when the right answer is a decline
    ranking: tuple              # tied blocks of entry_ids, best first
    declined: bool


def _credit(ranking, right, k) -> Fraction:
    """Decision 69's credit for the right entry among tied blocks of entry_ids, through
    app.diagnosis.matcher.credit itself (one engine): it only reads each item's entry_id."""
    blocks = [tuple(SimpleNamespace(entry_id=e) for e in block) for block in ranking]
    return matcher.credit(blocks, right, k)


def _known(cases):
    """The known-fault cases: those with a right entry."""
    return [c for c in cases if c.right is not None]


def _top1_rate(cases) -> Fraction:
    known = _known(cases)
    if not known:
        raise ValueError("no known-fault cases")
    return topk_credit(known, 1) / len(known)


def topk_credit(cases, k) -> Fraction:
    """Top-k credit summed over the known-fault cases (right is not None). Declined cases
    count 0. top-1 is k = 1; the rate is this sum over the number of known-fault cases."""
    return sum((Fraction(0) if c.declined else _credit(c.ranking, c.right, k)
                for c in _known(cases)), Fraction(0))          # a decline isn't an answer


def family_credit(cases, family_of) -> Fraction:
    """Family credit summed over the cases with a family (known-fault and leave-one-out):
    the share of the top block whose family (family_of[entry_id]) is the case's family.
    Declined cases count 0."""
    total = Fraction(0)
    for c in cases:
        if c.family is None or c.declined or not c.ranking:
            continue                                        # false alerts, declines: no credit
        top = c.ranking[0]
        total += Fraction(sum(family_of[e] == c.family for e in top), len(top))
    return total


def wrongly_declined(cases) -> Fraction:
    """The share of known-fault cases that were declined."""
    known = _known(cases)
    if not known:
        raise ValueError("no known-fault cases")
    return Fraction(sum(c.declined for c in known), len(known))


def decline_share(cases) -> Fraction:
    """The share of cases whose right answer is a decline (right is None: false-alert and
    leave-one-out cases) that were declined."""
    should = [c for c in cases if c.right is None]         # false-alert and leave-one-out cases
    if not should:
        raise ValueError("no cases whose right answer is a decline")
    return Fraction(sum(c.declined for c in should), len(should))


def candidate_recall(cases, k) -> Fraction:
    """The share of known-fault cases whose right entry is in the top k, ties counted
    fractionally, whether or not the case was declined."""
    known = _known(cases)
    if not known:
        raise ValueError("no known-fault cases")
    return sum((_credit(c.ranking, c.right, k) for c in known), Fraction(0)) / len(known)


def paired_top1_bootstrap(cases_a, cases_b, rng, n=metrics.BOOTSTRAP_N, level=0.95) -> tuple:
    """(difference, lo, hi): method A's top-1 rate minus method B's, over the known-fault
    cases, and its percentile interval from n paired resamples of run numbers (decision 72;
    rule 3). Each resample draws run numbers with replacement and brings every case with a
    drawn number, for both methods (metrics.paired_bootstrap_ci does the draw). A and B
    must hold the same cases: the same (run, fault) pairs."""
    key = lambda c: (c.run, c.fault)
    if sorted(map(key, cases_a)) != sorted(map(key, cases_b)):
        raise ValueError("A and B must hold the same cases: the same (run, fault) pairs")
    diff = _top1_rate(cases_a) - _top1_rate(cases_b)
    lo, hi = metrics.paired_bootstrap_ci(cases_a, cases_b, lambda cs: float(_top1_rate(cs)),
                                         rng, n=n, level=level)   # one run-number draw for both
    return diff, lo, hi
