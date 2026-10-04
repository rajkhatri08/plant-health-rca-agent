"""app/agent/schema.py: the LLM's output schema (decision 75), the Pydantic model and the
JSON schema sent to the provider, kept in step."""

import json

import pytest

from app.agent import llm
from app.agent import schema as sc
from app.library.schema import FAMILIES
from shared.leak_scan import find_leaks

GOOD = {"decision": "propose", "entry_ref": "reaction-rate-drift@r1", "family": "reaction kinetics",
        "confidence": "medium",
        "cited_evidence": [{"item": "provisional.tags.RX-PI-202", "state": "low"},
                           {"item": "location.top_group", "state": "reactor"}],
        "action_ids": ["check-reaction-conditions"], "rationale": "RX-PI-202 is low."}


def doc(**changes):
    return {**GOOD, **changes}


def test_a_good_proposal_parses():
    o = sc.parse_output(GOOD)
    assert o.decision == "propose" and o.cited_evidence[0].item == "provisional.tags.RX-PI-202"
    assert o.action_ids == ("check-reaction-conditions",)


def test_a_decline_and_a_not_in_library_answer_parse():
    sc.parse_output(doc(decision="decline", entry_ref=None, family=None, action_ids=[], cited_evidence=[]))
    sc.parse_output(doc(decision="not_in_library", entry_ref=None, family="feed composition", action_ids=[]))


@pytest.mark.parametrize("changes, match", [
    ({"decision": "maybe"}, "decision"),
    ({"confidence": "certain"}, "confidence"),
    ({"family": "cooling"}, "family"),
    ({"entry_ref": None}, "propose needs entry_ref"),
    ({"entry_ref": ""}, "propose needs entry_ref"),
    ({"family": None}, "propose needs family"),
    ({"cited_evidence": [GOOD["cited_evidence"][0]]}, "at least 2"),
    ({"decision": "decline", "entry_ref": None, "family": None, "action_ids": ["x"]}, "no actions"),
    ({"decision": "decline", "family": None, "action_ids": []}, "no entry_ref"),
    ({"decision": "decline", "entry_ref": None, "action_ids": []}, "decline has no family"),
    ({"decision": "not_in_library", "entry_ref": None, "family": None, "action_ids": []}, "needs family"),
    ({"decision": "not_in_library", "entry_ref": None, "action_ids": ["x"]}, "no actions"),
    ({"action_ids": ["a", "a"]}, "repeats"),
    ({"rationale": "x" * 601}, "rationale"),
    ({"cited_evidence": [{"item": "", "state": "low"}, GOOD["cited_evidence"][1]]}, "item"),
    ({"cited_evidence": [{"item": "a", "state": "low", "why": "x"}, GOOD["cited_evidence"][1]]}, "why"),
    ({"extra": 1}, "extra"),
])
def test_bad_outputs_are_refused(changes, match):
    with pytest.raises(sc.OutputError, match=match):
        sc.parse_output(doc(**changes))


@pytest.mark.parametrize("parsed", [None, [], "text", 3])
def test_not_an_object_is_refused(parsed):
    with pytest.raises(sc.OutputError, match="isn't a JSON object"):
        sc.parse_output(parsed)


def test_a_missing_field_is_refused():
    d = dict(GOOD)
    del d["confidence"]
    with pytest.raises(sc.OutputError, match="confidence"):
        sc.parse_output(d)


def test_rationale_at_the_limit_is_fine():
    sc.parse_output(doc(rationale="x" * 600))


# ---------- the JSON schema sent to the provider ----------

def test_json_schema_matches_the_model():
    props = sc.JSON_SCHEMA["properties"]
    assert set(props) == set(sc.Output.model_fields) == set(sc.JSON_SCHEMA["required"])
    assert props["decision"]["enum"] == list(sc.DECISIONS)
    assert props["confidence"]["enum"] == list(sc.CONFIDENCE)
    assert props["family"]["enum"] == list(FAMILIES) + [None]
    assert props["rationale"]["maxLength"] == sc.RATIONALE_MAX == 600
    assert set(props["cited_evidence"]["items"]["properties"]) == set(sc.Citation.model_fields)
    assert sc.JSON_SCHEMA["additionalProperties"] is False


def test_json_schema_is_flat_and_serialisable():
    text = json.dumps(sc.JSON_SCHEMA)
    assert "$ref" not in text and "$defs" not in text


def test_output_schema_is_versioned_for_the_cache_key():
    s = sc.output_schema()
    assert isinstance(s, llm.OutputSchema) and s.version == sc.SCHEMA_VERSION == "diagnosis-1"
    assert s.json_schema is sc.JSON_SCHEMA


def test_the_schema_text_sent_to_the_model_is_clean():
    assert find_leaks(json.dumps(sc.JSON_SCHEMA)) == []