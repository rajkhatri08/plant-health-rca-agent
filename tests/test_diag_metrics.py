"""eval/diag_metrics.py on hand-built cases (decisions 69-72). These fail with
NotImplementedError until Raj implements the stubs.

Entries a, b (family F1), c (F2), d (F3). Rankings are tied blocks of entry_ids."""

from fractions import Fraction as F

import numpy as np
import pytest

from app.diagnosis import matcher
from eval import diag_metrics as dm

FAMILY = {"a": "F1", "b": "F1", "c": "F2", "d": "F3"}


def known(run, right, ranking, declined=False, fault=1):
    return dm.Case(run=run, fault=fault, family=FAMILY[right], right=right, ranking=ranking, declined=declined)


def loo(run, family, ranking, declined):
    return dm.Case(run=run, fault=2, family=family, right=None, ranking=ranking, declined=declined)


def false_alert(run, ranking, declined):
    return dm.Case(run=run, fault=0, family=None, right=None, ranking=ranking, declined=declined)


R1 = (("a",), ("b",), ("c",), ("d",))              # a alone first
TIE = (("a", "b"), ("c",), ("d",))                 # a and b tie for first
LOW = (("c",), ("a", "b", "d"))                    # a in a three-way block at ranks 2..4


# ---------- top-k credit ----------

def test_topk_credit_sums_over_known_cases():
    cases = [known(1, "a", R1), known(2, "a", TIE), known(3, "a", LOW)]
    assert dm.topk_credit(cases, 1) == 1 + F(1, 2) + 0
    assert dm.topk_credit(cases, 2) == 1 + 1 + F(1, 3)
    assert dm.topk_credit(cases, 3) == 1 + 1 + F(2, 3)
    assert dm.topk_credit(cases, 4) == 3


def test_topk_credit_matches_the_matchers_rule():
    # one engine: the same credit as app.diagnosis.matcher.credit on the same blocks
    def score_blocks(ranking):
        return [tuple(matcher.Score(f"{e}@r1", e, 0, 0, 0, 1, F(1), ()) for e in block) for block in ranking]
    for ranking in (R1, TIE, LOW):
        for k in (1, 2, 3, 4):
            assert dm.topk_credit([known(1, "a", ranking)], k) == matcher.credit(score_blocks(ranking), "a", k)


def test_topk_credit_declined_counts_zero():
    assert dm.topk_credit([known(1, "a", R1, declined=True), known(2, "a", R1)], 1) == 1


def test_topk_credit_ignores_cases_whose_answer_is_a_decline():
    cases = [known(1, "a", R1), loo(2, "F1", R1, False), false_alert(3, R1, False)]
    assert dm.topk_credit(cases, 1) == 1


def test_topk_credit_right_entry_missing_from_ranking():
    assert dm.topk_credit([known(1, "a", (("c",), ("d",)))], 4) == 0


def test_topk_credit_is_exact():
    assert isinstance(dm.topk_credit([known(1, "a", LOW)], 2), F)


# ---------- family credit ----------

def test_family_credit_top_block_share():
    cases = [known(1, "a", R1),                        # top a: F1, right family
             known(2, "a", (("b",), ("a",))),          # top b: also F1
             known(3, "a", (("c",), ("a",))),          # top c: F2
             known(4, "a", (("a", "c"), ("b",)))]      # half the top block is F1
    assert dm.family_credit(cases, FAMILY) == 1 + 1 + 0 + F(1, 2)


def test_family_credit_counts_leave_one_out_and_skips_false_alerts():
    cases = [loo(1, "F1", (("b",), ("c",)), declined=False),     # forced label, right family
             loo(2, "F1", (("c",), ("b",)), declined=False),     # forced label, wrong family
             false_alert(3, R1, declined=False)]
    assert dm.family_credit(cases, FAMILY) == 1


def test_family_credit_declined_counts_zero():
    assert dm.family_credit([known(1, "a", R1, declined=True), loo(2, "F1", R1, True)], FAMILY) == 0


# ---------- declines ----------

def test_wrongly_declined_share_of_known_cases():
    cases = [known(1, "a", R1, declined=True), known(2, "b", R1), known(3, "c", R1),
             known(4, "d", R1), false_alert(5, R1, declined=True)]
    assert dm.wrongly_declined(cases) == F(1, 4)


def test_decline_share_over_cases_whose_answer_is_a_decline():
    cases = [false_alert(1, R1, True), false_alert(2, R1, False), false_alert(3, R1, True),
             loo(4, "F1", R1, True), known(5, "a", R1, declined=True)]
    assert dm.decline_share(cases) == F(3, 4)


def test_decline_share_false_alerts_alone():
    assert dm.decline_share([false_alert(1, R1, True), false_alert(2, R1, False)]) == F(1, 2)


# ---------- candidate recall ----------

def test_candidate_recall_ignores_the_decline_and_counts_ties():
    cases = [known(1, "a", R1, declined=True), known(2, "a", LOW), known(3, "a", (("c",), ("d",), ("a",)))]
    assert dm.candidate_recall(cases, 1) == F(1, 3)
    assert dm.candidate_recall(cases, 2) == (1 + F(1, 3) + 0) / 3
    assert dm.candidate_recall(cases, 3) == (1 + F(2, 3) + 1) / 3


# ---------- empty denominators ----------

@pytest.mark.parametrize("fn", [lambda c: dm.wrongly_declined(c), lambda c: dm.candidate_recall(c, 1)])
def test_no_known_cases_refused(fn):
    with pytest.raises(ValueError):
        fn([false_alert(1, R1, True)])


def test_no_decline_cases_refused():
    with pytest.raises(ValueError):
        dm.decline_share([known(1, "a", R1)])


# ---------- paired bootstrap of the top-1 difference ----------

def test_paired_bootstrap_same_method_is_zero():
    cases = [known(r, "a", TIE if r % 2 else R1) for r in range(1, 11)]
    assert dm.paired_top1_bootstrap(cases, cases, np.random.default_rng(1), n=200) == (0, 0.0, 0.0)


def test_paired_bootstrap_always_right_vs_never():
    a = [known(r, "a", R1) for r in range(1, 6)]
    b = [known(r, "a", (("c",), ("a",))) for r in range(1, 6)]
    diff, lo, hi = dm.paired_top1_bootstrap(a, b, np.random.default_rng(1), n=200)
    assert (diff, lo, hi) == (1, 1.0, 1.0)


def test_paired_bootstrap_resamples_run_numbers_not_cases():
    # run 1 carries two cases where A is right and B wrong; run 2 two where both are right.
    # A draw is two run numbers, so the difference is 1 (1,1), 0 (2,2) or 0.5 (1,2).
    a = [known(1, "a", R1), known(1, "b", (("b",),), fault=4), known(2, "a", R1), known(2, "b", (("b",),), fault=4)]
    b = [known(1, "a", (("c",), ("a",))), known(1, "b", (("c",), ("b",)), fault=4),
         known(2, "a", R1), known(2, "b", (("b",),), fault=4)]
    diff, lo, hi = dm.paired_top1_bootstrap(a, b, np.random.default_rng(7), n=2000)
    assert diff == F(1, 2) and (lo, hi) == (0.0, 1.0)


def test_paired_bootstrap_is_seeded():
    a = [known(r, "a", TIE if r % 3 else R1) for r in range(1, 21)]
    b = [known(r, "a", R1 if r % 2 else LOW) for r in range(1, 21)]
    one = dm.paired_top1_bootstrap(a, b, np.random.default_rng(20261002), n=300)
    two = dm.paired_top1_bootstrap(a, b, np.random.default_rng(20261002), n=300)
    assert one == two


def test_paired_bootstrap_needs_the_same_cases():
    a = [known(1, "a", R1), known(2, "a", R1)]
    with pytest.raises(ValueError):
        dm.paired_top1_bootstrap(a, [known(1, "a", R1), known(3, "a", R1)], np.random.default_rng(1), n=10)
    with pytest.raises(ValueError):
        dm.paired_top1_bootstrap(a, [known(1, "a", R1), known(2, "a", R1, fault=4)], np.random.default_rng(1), n=10)