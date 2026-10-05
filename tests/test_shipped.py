"""app/agent/shipped.py: decision 79's rule. Raj's function: until it's implemented, these fail
with NotImplementedError."""

import pytest

from app.agent import shipped

A, B, C = "entry-a@r1", "entry-b@r1", "entry-c@r1"


def blocks(*bs):
    return [[{"ref": r, "entry_id": r.split("@")[0], "required_contradictions": 0, "fit": "1/1", "verdicts": []}
             for r in b] for b in bs]


SINGLE = blocks([A], [B], [C])          # one top entry
TIED = blocks([B, A], [C])              # a tie at the top (blocks are in ref order inside: A, B)


def out(decision="propose", entry_ref=A, family="fam-a", rationale="fits", actions=("x",)):
    return {"decision": decision, "entry_ref": entry_ref if decision == "propose" else None,
            "family": family if decision != "decline" else None, "confidence": "high",
            "cited_evidence": [], "action_ids": list(actions) if decision == "propose" else [], "rationale": rationale}


def test_agreeing_with_a_single_top_entry_proposes_it():
    s = shipped.ship(out(entry_ref=A), [], {"key": "k"}, SINGLE)
    assert s == {"decision": "propose", "entry_ref": A, "tie_break": False, "matcher_top": [A], "dissent": None}


@pytest.mark.parametrize("pick", [A, B])
def test_a_pick_within_a_tied_top_block_is_a_tie_break(pick):
    s = shipped.ship(out(entry_ref=pick), [], {"key": "k"}, TIED)
    assert s["decision"] == "propose" and s["entry_ref"] == pick and s["tie_break"] is True
    assert s["matcher_top"] == [A, B] and s["dissent"] is None


def test_a_pick_outside_the_top_block_is_a_veto():
    s = shipped.ship(out(entry_ref=B, rationale="B fits better"), [], {"key": "k"}, SINGLE)
    assert s["decision"] == "veto" and s["entry_ref"] is None and s["tie_break"] is False
    assert s["matcher_top"] == [A]
    assert s["dissent"] == {"llm_decision": "propose", "llm_entry_ref": B, "rationale": "B fits better",
                            "family_note": None}


def test_a_pick_below_a_tie_is_a_veto():
    assert shipped.ship(out(entry_ref=C), [], {"key": "k"}, TIED)["decision"] == "veto"


def test_a_decline_is_a_veto():
    s = shipped.ship(out("decline", rationale="nothing fits"), [], {"key": "k"}, SINGLE)
    assert s["decision"] == "veto" and s["entry_ref"] is None
    assert s["dissent"] == {"llm_decision": "decline", "llm_entry_ref": None, "rationale": "nothing fits",
                            "family_note": None}


def test_not_in_library_is_a_veto_with_its_family_as_a_note():
    s = shipped.ship(out("not_in_library", family="fam-b", rationale="a kinetics change"), [], {"key": "k"}, SINGLE)
    assert s["decision"] == "veto" and s["entry_ref"] is None
    assert s["dissent"]["family_note"] == "fam-b" and s["dissent"]["llm_decision"] == "not_in_library"


@pytest.mark.parametrize("output, failures, llm", [
    (out(), [{"code": "citation", "detail": "x"}], {"key": "k"}),         # faithfulness
    (None, [{"code": "schema", "detail": "x"}], {"key": "k"}),            # schema
    (None, [], {"error": "the API failed 3 times"}),                     # an API error
])
def test_a_failure_or_an_error_shows_the_evidence(output, failures, llm):
    s = shipped.ship(output, failures, llm, SINGLE)
    assert s["decision"] == "evidence" and s["entry_ref"] is None and s["dissent"] is None
    assert s["matcher_top"] == [A]


@pytest.mark.parametrize("output", [out(entry_ref=B), out(entry_ref=C), out("decline"),
                                    out("not_in_library", family="fam-c")])
@pytest.mark.parametrize("ranking", [SINGLE, TIED])
def test_dissent_never_becomes_a_proposal(output, ranking):
    s = shipped.ship(output, [], {"key": "k"}, ranking)
    top = {x["ref"] for x in ranking[0]}
    if output["decision"] == "propose" and output["entry_ref"] in top:
        assert s["decision"] == "propose"
    else:
        assert s["decision"] == "veto" and s["entry_ref"] is None and s["dissent"] is not None
    assert s["decision"] in shipped.DECISIONS