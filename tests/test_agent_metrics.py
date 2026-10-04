"""eval/agent_metrics.py on hand-built rows (decisions 75, 77). The functions are Raj's: until
they're implemented, every test here fails with NotImplementedError."""

from fractions import Fraction

import pytest

from eval import agent_metrics as am
from eval import diag_metrics as dm

A, B, C = "entry-a", "entry-b", "entry-c"
RANK = [[A], [B, C]]                       # the matcher's blocks of entry_ids
FAMILY_OF = {A: "fam-a", B: "fam-b", C: "fam-a"}


def row(kind="known", outcome="proposed", entry=A, right=A, family="fam-a", answer_family=None,
        confidence="high", failures=(), candidates=(A, B), matcher_declined=False, run=1, fault=1,
        case="c1", stage="provisional", repeat=0, llm_key="k1", latency_ms=100.0):
    if kind != "known":
        right = None
    if kind == "false":
        family, fault = None, 0
    return {"case": case, "kind": kind, "run": run, "fault": fault, "family": family, "right": right,
            "stage": stage, "repeat": repeat, "outcome": outcome,
            "entry": entry if outcome == "proposed" else None, "answer_family": answer_family,
            "confidence": confidence if outcome in ("declined", "not_in_library", "proposed") else None,
            "failures": list(failures), "candidates": list(candidates), "matcher_ranking": RANK,
            "matcher_declined": matcher_declined, "llm_key": None if matcher_declined else llm_key,
            "cached": False, "latency_ms": None if matcher_declined else latency_ms,
            "tokens_in": 10, "tokens_out": 5, "tokens_thinking": 0, "error": None}


# ---------- to_case ----------

def test_a_right_proposal():
    c = am.to_case(row())
    assert isinstance(c, dm.Case) and not c.declined and c.ranking[0] == (A,)
    assert dm.topk_credit([c], 1) == 1


def test_the_agent_ranking_is_its_pick_then_the_matchers_rest():
    c = am.to_case(row(entry=B, right=C))
    assert c.ranking == ((B,), (A,), (C,))                 # B removed from its block, the rest kept
    assert dm.topk_credit([c], 1) == 0 and dm.topk_credit([c], 3) == 1


@pytest.mark.parametrize("outcome", ["matcher_declined", "declined", "not_in_library", "failed_check", "error"])
def test_no_proposal_on_a_known_case_is_wrong(outcome):
    c = am.to_case(row(outcome=outcome))
    assert c.declined and dm.topk_credit([c], 1) == 0 and dm.wrongly_declined([c]) == 1


@pytest.mark.parametrize("kind", ["false", "loo"])
@pytest.mark.parametrize("outcome, declined", [("matcher_declined", True), ("declined", True),
                                               ("failed_check", True), ("error", True),
                                               ("not_in_library", False), ("proposed", False)])
def test_unknowns_are_right_only_when_declined(kind, outcome, declined):
    assert am.to_case(row(kind=kind, outcome=outcome)).declined is declined


@pytest.mark.parametrize("outcome, declined", [("failed_check", False), ("error", False),
                                               ("declined", True), ("matcher_declined", True)])
def test_the_keep_rule_variant_on_loo(outcome, declined):
    assert am.to_case(row(kind="loo", outcome=outcome), keep_rule=True).declined is declined


def test_the_keep_rule_variant_leaves_false_alerts_alone():
    assert am.to_case(row(kind="false", outcome="error"), keep_rule=True).declined is True


# ---------- summary ----------

def test_summary():
    rows = [row(case="k1"), row(case="k2", entry=B, right=A), row(case="k3", outcome="failed_check",
                                                                  failures=["citation"]),
            row(kind="false", case="f1", outcome="declined"), row(kind="false", case="f2", outcome="proposed"),
            row(kind="loo", case="l1", outcome="matcher_declined", matcher_declined=True),
            row(kind="loo", case="l2", outcome="error"),
            row(kind="loo", case="l3", outcome="failed_check", failures=["schema"])]
    s = am.summary(rows, FAMILY_OF)
    assert s["known"] == 3 and s["top1"] == Fraction(1, 3)
    assert s["family"] == Fraction(1, 3)          # k2 picked B (fam-b); k3 has no answer
    assert s["wrongly_declined"] == Fraction(1, 3)
    assert s["false_alerts"] == 2 and s["false_alert_declined"] == Fraction(1, 2)
    assert s["loo"] == 3 and s["loo_declined"] == 1                # failures and errors decline here
    assert s["failed_check"] == 2 and s["schema"] == 1 and s["errors"] == 1


def test_summary_with_no_false_alerts_or_loo():
    s = am.summary([row()], FAMILY_OF)
    assert s["false_alert_declined"] is None and s["loo_declined"] is None


# ---------- the keep rule ----------

M = {"top1": 0.70, "family": 0.85, "unknowns_declined": 0.80}


def reps(*triples):
    return [dict(zip(("top1", "family", "unknowns_declined"), t)) for t in triples]


def test_kept_when_5_points_better_in_every_repeat_and_never_2_worse():
    out = am.keep_rule(reps(*[(0.76, 0.85, 0.80)] * 5), M)
    assert out["keep"] and out["better_on"] == ["top1"] and out["worse_on"] == []
    assert out["metrics"]["top1"]["diff_mean"] == pytest.approx(0.06)
    assert len(out["metrics"]["top1"]["diffs"]) == 5


def test_not_kept_when_one_repeat_falls_short():
    out = am.keep_rule(reps(*[(0.76, 0.85, 0.80)] * 4, (0.74, 0.85, 0.80)), M)
    assert not out["keep"] and out["better_on"] == []


def test_not_kept_when_another_metric_is_more_than_2_points_worse():
    out = am.keep_rule(reps(*[(0.80, 0.82, 0.80)] * 5), M)
    assert not out["keep"] and out["better_on"] == ["top1"] and out["worse_on"] == ["family"]


def test_exactly_2_points_worse_is_allowed():
    out = am.keep_rule(reps(*[(0.80, 0.83, 0.80)] * 5), M)
    assert out["keep"] and out["worse_on"] == []


# ---------- the confidence check, agreement, misses ----------

def test_confidence_table():
    rows = [row(case="a", confidence="high"), row(case="b", confidence="high", entry=B),
            row(case="c", confidence="low", kind="false", outcome="declined"),
            row(case="d", outcome="failed_check", failures=["citation"])]          # no valid output
    t = am.confidence_table(rows)
    assert t["high"] == {"n": 2, "correct": 1} and t["low"] == {"n": 1, "correct": 1}
    assert t["medium"] == {"n": 0, "correct": 0}


def test_agreement():
    rows = ([row(case="s", repeat=r) for r in range(5)]
            + [row(case="u", repeat=r, entry=(A if r < 3 else B)) for r in range(5)])
    a = am.agreement(rows)
    assert a["cases"] == 2 and a["stable"] == 1 and a["unstable"] == [("u", "provisional")]
    assert a["mean_agreement"] == pytest.approx((1 + 3 / 5) / 2)


def test_miss_labels():
    rows = [row(case="ok"),
            row(case="gate", outcome="matcher_declined", matcher_declined=True),
            row(case="retr", entry=B, right=C, candidates=(A, B)),
            row(case="reas", entry=B, right=A, candidates=(A, B)),
            row(case="fail", outcome="failed_check", right=A, candidates=(A, B))]
    assert am.miss_labels(rows) == {"gate": 1, "retrieval": 1, "reasoning": 2}


def test_not_in_library_secondary():
    rows = [row(kind="loo", case="a", outcome="not_in_library", family="fam-a", answer_family="fam-a"),
            row(kind="loo", case="b", outcome="not_in_library", family="fam-a", answer_family="fam-b"),
            row(kind="loo", case="c", outcome="declined")]
    assert am.not_in_library_secondary(rows) == {"cases": 3, "answers": 2, "family_correct": 1}


def test_latency_and_cost():
    rows = [row(case="a", llm_key="k1", latency_ms=100.0), row(case="b", llm_key="k2", latency_ms=300.0),
            row(case="c", llm_key="k1", latency_ms=200.0),                 # the same call again (a cache hit)
            row(case="d", outcome="matcher_declined", matcher_declined=True)]
    ledger = {"k1": {"cost_inr": "0.10"}, "k2": {"cost_inr": "0.30"}}
    out = am.latency_cost(rows, ledger)
    assert out["calls"] == 3 and out["latency_ms"]["median"] == 200.0 and out["latency_ms"]["max"] == 300.0
    assert out["latency_ms"]["p95"] == pytest.approx(290.0)
    assert out["cost_inr"] == pytest.approx(0.40) and out["cost_per_diagnosis"] == pytest.approx(0.10)
