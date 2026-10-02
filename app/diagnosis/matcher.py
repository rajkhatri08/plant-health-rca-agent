"""The signature matcher (decisions 15, 69). Runtime code: no imports from dataset/,
eval/ or ingest/, and no labels: it knows entries by entry_id only.

Decision 69 (Raj's S1 choices, 2 October 2026; not yet written into docs/decisions.md):
- Verdicts: each listed item is agree, contradict or unknown (app/diagnosis/items.py,
  shared with the approval gate).
- Scope: the +30 min diagnosis ("provisional") scores the location and provisional items;
  the +60 min diagnosis ("revised") scores the location, provisional and revised items.
- Weights, fixed in advance: required 2, supporting 1.
- Ranking: fewer required contradictions first, then higher
      fit = (agreeing weight - contradicting weight) / total listed weight in scope.
  Unknown items count in the total but neither agree nor contradict.
- Ties are kept, not broken: entries with equal (required contradictions, fit) share a
  block. Top-1 gives 1/m credit when m entries tie for first including the right one;
  top-k counts a tied block fractionally the same way.
- Decline when every entry has a required contradiction, or the top entry's fit is below
  a threshold set on dev (S7: accept 95% of known-fault dev cases).

Conventions (Claude's, to confirm):
- fit is an exact fractions.Fraction, so ties are exact equality, never a float tolerance.
- A ranking is a list of tied blocks, best first; each block is a tuple of Scores ordered
  by ref, so the output is deterministic.
- Top-k credit when the right entry's block covers ranks a..b (m = b - a + 1 entries):
  1 if k >= b, 0 if k < a, else (k - a + 1) / m. Top-1 is the k = 1 case (1/m when a = 1).
  An entry not in the ranking (left out, or not in force) gets 0.
- "Below a threshold" is strict: a fit equal to the threshold isn't declined. An empty
  ranking (no entry in force) is a decline.
- The threshold is an argument, so one per diagnosis time or a shared one are both
  possible (open in S1).

Raj implements score, rank, credit and decline. candidates and match are wiring.
"""

from dataclasses import dataclass
from fractions import Fraction

from app.diagnosis import items as sig_items

WEIGHTS = {"required": 2, "supporting": 1}
SCOPES = {"provisional": ("location", "provisional"),
          "revised": ("location", "provisional", "revised")}


@dataclass(frozen=True)
class Score:
    ref: str                        # entry_id@r<k>
    entry_id: str
    required_contradictions: int
    agree_weight: int
    contradict_weight: int
    total_weight: int               # every listed item in scope, unknown ones included
    fit: Fraction
    verdicts: tuple                 # ((item name, verdict), ...) for the items in scope, in items() order


def score(revision, features, at) -> Score:
    """One revision (schema.Revision) against one case's features at diagnosis time at
    ("provisional" or "revised"), per decision 69. Uses items.items() for the verdicts;
    only items whose scope is in SCOPES[at] count."""
    if at not in SCOPES:
        raise ValueError(f"at must be one of {tuple(SCOPES)}, got {at!r}")
    rc = agree = contra = total = 0
    verdicts = []
    for item in sig_items.items(revision.signature):
        if item.scope not in SCOPES[at]:
            continue                                    # not in scope at this diagnosis time
        w = WEIGHTS[item.weight]
        v = item.verdict(features)
        total += w                                      # unknown items still count in the total
        if v == sig_items.AGREE:
            agree += w
        elif v == sig_items.CONTRADICT:
            contra += w
            if item.weight == "required":
                rc += 1
        verdicts.append((item.name, v))
    if total == 0:
        raise ValueError(f"{revision.entry_id} lists no item in scope at {at}")
    return Score(ref=f"{revision.entry_id}@r{revision.revision}", entry_id=revision.entry_id,
                 required_contradictions=rc, agree_weight=agree, contradict_weight=contra,
                 total_weight=total, fit=Fraction(agree - contra, total), verdicts=tuple(verdicts))


def rank(scores) -> list:
    """[(Score, ...), ...]: tied blocks, best first (fewer required contradictions, then
    higher fit); within a block, ordered by ref."""
    blocks = {}
    for sc in scores:                                   # equal (contradictions, fit) share a block
        blocks.setdefault((sc.required_contradictions, sc.fit), []).append(sc)
    order = sorted(blocks, key=lambda key: (key[0], -key[1]))   # fewer contradictions, then higher fit
    return [tuple(sorted(blocks[key], key=lambda sc: sc.ref)) for key in order]


def credit(ranking, entry_id, k) -> Fraction:
    """Top-k credit for the right entry, with ties counted fractionally (see the module
    docstring)."""
    a = 1                                               # the first rank this block covers
    for block in ranking:
        b = a + len(block) - 1                          # the last rank it covers
        if any(sc.entry_id == entry_id for sc in block):
            if k >= b:
                return Fraction(1)
            if k < a:
                return Fraction(0)
            return Fraction(k - a + 1, len(block))      # part of the tied block fits in the top k
        a = b + 1
    return Fraction(0)                                  # not ranked at all


def decline(ranking, threshold) -> bool:
    """True when the ranking is empty, every entry has a required contradiction, or the
    top block's fit is below threshold."""
    if not ranking:
        return True                                     # no entry in force
    top = ranking[0][0]                                 # the whole top block shares its scores
    if top.required_contradictions > 0:
        return True                                     # the best has one, so every entry has one
    return top.fit < threshold                          # strictly below; equal isn't declined


def candidates(library, as_of) -> list:
    """The revisions in force as of as_of (store.Library.in_force), by entry_id. Drafts,
    withdrawn entries and approvals after as_of are never candidates."""
    return [inf.stored.revision for _, inf in sorted(library.in_force(as_of).items())]


def match(library, features, at, as_of) -> list:
    """Rank every entry in force as of as_of against one case's features."""
    if at not in SCOPES:
        raise ValueError(f"at must be one of {tuple(SCOPES)}, got {at!r}")
    return rank([score(rev, features, at) for rev in candidates(library, as_of)])
