"""app/agent/faithfulness.py: decision 75's five checks. check() is Raj's: until it's
implemented, the tests that call it fail with NotImplementedError.

The library is the committed one (store.load()). The evidence is a hand-built features dict
in the evidence tool's form. Times are after mixed-feed-temperature-wander's r2 approval
(4 October 2026, 08:09 UTC) unless a test says otherwise."""

from datetime import datetime, timezone

import pytest

from app.agent import faithfulness as fa
from app.agent import schema as sc
from app.detector import bundle, features
from app.library import store

AS_OF = datetime(2026, 10, 5, tzinfo=timezone.utc)
BEFORE_R2 = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
DRIFT, WANDER, STICKING = "reaction-rate-drift", "mixed-feed-temperature-wander", "reactor-cooling-valve-sticking"
CANDIDATES = [f"{DRIFT}@r1", f"{WANDER}@r2"]


@pytest.fixture(scope="module")
def library():
    return store.load()


def reading(plant, **tags):
    return {"tags": {t: tags.get(t.replace("-", "_"), "normal") for t in plant.fast_tags},
            "loops": {i: ("compensating" if i == "CP-FIC-501" else "held") for i in plant.loops},
            "analyzers": {t: "normal" for t in plant.analyzers},
            "masked": False}


@pytest.fixture(scope="module")
def evidence():
    """+30 min evidence: location and the provisional reading only."""
    plant = features.plant_from_files(bundle.fast_tags())
    return {"location": {"top_group": "reactor", "top_tags": ["RX-PI-202", "SP-PI-403", "ST-PI-602"]},
            "provisional": reading(plant, RX_PI_202="low", SP_PI_403="low")}


@pytest.fixture(scope="module")
def evidence60(evidence):
    plant = features.plant_from_files(bundle.fast_tags())
    return {**evidence, "revised": reading(plant, RX_PI_202="low")}


GOOD = {"decision": "propose", "entry_ref": f"{DRIFT}@r1", "family": "reaction kinetics", "confidence": "medium",
        "cited_evidence": [{"item": "provisional.tags.RX-PI-202", "state": "low"},
                           {"item": "location.top_group", "state": "reactor"}],
        "action_ids": ["check-reaction-conditions"],
        "rationale": "RX-PI-202 and SP-PI-403 are low while CP-FIC-501 compensates; the gas loop pressures move together."}


def out(**changes):
    return sc.parse_output({**GOOD, **changes})


def cite(*pairs):
    return [{"item": i, "state": s} for i, s in pairs]


def codes(failures):
    return sorted(f.code for f in failures)


def run(library, evidence, output, candidates=CANDIDATES, as_of=AS_OF):
    failures = fa.check(output, evidence, candidates, library, as_of)
    assert isinstance(failures, list) and all(isinstance(f, fa.Failure) for f in failures)
    return failures


# ---------- wiring (passing now) ----------

def test_codes_are_the_five_checks():
    assert fa.CODES == ("citation", "entry", "action", "family", "rationale")


def test_a_failure_needs_a_known_code():
    with pytest.raises(ValueError):
        fa.Failure("vibes", "x")
    assert fa.passed([]) and not fa.passed([fa.Failure("entry", "x")])


def test_the_fixture_matches_the_library(library):
    # The test's assumptions about the committed library, so a later revision can't make
    # these tests pass or fail for the wrong reason.
    drift, wander = library.get(DRIFT, AS_OF), library.get(WANDER, AS_OF)
    assert (drift.ref, drift.stored.revision.family) == (f"{DRIFT}@r1", "reaction kinetics")
    assert (wander.ref, wander.stored.revision.family) == (f"{WANDER}@r2", "feed temperature")
    assert library.get(WANDER, BEFORE_R2).ref == f"{WANDER}@r1"
    assert "check-reaction-conditions" in {a.action_id for a in drift.stored.revision.actions}
    assert library.get(STICKING, AS_OF).stored.revision.family == "reactor cooling"


# ---------- passes ----------

def test_a_faithful_proposal_passes(library, evidence):
    assert run(library, evidence, out()) == []


def test_every_citation_form_passes(library, evidence60):
    o = out(cited_evidence=cite(("location.top_group", "reactor"), ("location.top_tags", "SP-PI-403"),
                                ("provisional.tags.RX-PI-202", "low"), ("provisional.loops.CP-FIC-501", "compensating"),
                                ("provisional.analyzers.RX-AI-211", "normal"), ("provisional.masked", "false"),
                                ("revised.tags.RX-PI-202", "low")))
    assert run(library, evidence60, o) == []


def test_a_faithful_decline_passes(library, evidence):
    o = out(decision="decline", entry_ref=None, family=None, action_ids=[],
            cited_evidence=cite(("provisional.tags.RX-PI-202", "low")), rationale="The evidence fits no entry well.")
    assert run(library, evidence, o) == []


def test_not_in_library_with_a_candidates_family_passes(library, evidence):
    o = out(decision="not_in_library", entry_ref=None, family="feed temperature", action_ids=[],
            rationale="A feed temperature change, but neither entry's mechanism fits.")
    assert run(library, evidence, o) == []


def test_digits_inside_tag_and_loop_ids_are_allowed(library, evidence):
    o = out(rationale="RX-FV-206 is held; RX-PI-202, SP-PI-403 and CP-FIC-501 agree with the entry.")
    assert run(library, evidence, o) == []


def test_no_actions_is_fine(library, evidence):
    assert run(library, evidence, out(action_ids=[])) == []


# ---------- 1. citations ----------

@pytest.mark.parametrize("pair", [
    ("provisional.tags.RX-PI-202", "high"),          # the wrong state
    ("provisional.tags.XX-TI-999", "low"),           # no such tag
    ("revised.tags.RX-PI-202", "low"),               # the revised reading doesn't exist at +30 min
    ("location.top_group", "feed"),                  # another group
    ("location.top_tags", "RX-TI-204"),              # not among the top tags
    ("provisional.loops.CP-FIC-501", "held"),
    ("provisional.masked", "true"),
    ("provisional.analyzers.RX-AI-211", "high"),
    ("provisional.pressure", "low"),                 # not an item name
])
def test_an_unfaithful_citation_fails(library, evidence, pair):
    o = out(cited_evidence=cite(pair, ("location.top_group", "reactor")))
    assert codes(run(library, evidence, o)) == ["citation"]


def test_citations_are_checked_on_a_decline_too(library, evidence):
    o = out(decision="decline", entry_ref=None, family=None, action_ids=[],
            cited_evidence=cite(("provisional.tags.RX-PI-202", "high")), rationale="Nothing fits.")
    assert codes(run(library, evidence, o)) == ["citation"]


# ---------- 2. the entry ----------

def test_an_entry_not_shown_fails(library, evidence):
    # In force, but not a candidate: the LLM can only choose among what it was shown.
    o = out(entry_ref=f"{STICKING}@r1", family="reactor cooling", action_ids=[])
    assert "entry" in codes(run(library, evidence, o))


def test_a_superseded_revision_fails(library, evidence):
    # The r1 of an entry whose r2 is in force: never cite a revision not in force.
    o = out(entry_ref=f"{WANDER}@r1", family="feed temperature", action_ids=[])
    assert "entry" in codes(run(library, evidence, o, candidates=[f"{WANDER}@r1", f"{DRIFT}@r1"]))


def test_a_revision_not_yet_in_force_fails(library, evidence):
    o = out(entry_ref=f"{WANDER}@r2", family="feed temperature", action_ids=[])
    assert "entry" in codes(run(library, evidence, o, as_of=BEFORE_R2))


@pytest.mark.parametrize("ref", [f"{DRIFT}@r9", "no-such-entry@r1", DRIFT])
def test_an_unknown_ref_fails(library, evidence, ref):
    assert "entry" in codes(run(library, evidence, out(entry_ref=ref, action_ids=[]), candidates=CANDIDATES + [ref]))


# ---------- 3. actions ----------

def test_an_action_of_another_entry_fails(library, evidence):
    o = out(action_ids=["check-reaction-conditions", "check-reactor-cooling-valve-response"])
    assert codes(run(library, evidence, o)) == ["action"]


def test_an_invented_action_fails(library, evidence):
    assert codes(run(library, evidence, out(action_ids=["shut-down-the-reactor"]))) == ["action"]


# ---------- 4. family ----------

def test_a_proposal_with_another_family_fails(library, evidence):
    assert codes(run(library, evidence, out(family="reactor cooling"))) == ["family"]


def test_not_in_library_with_a_family_no_candidate_has_fails(library, evidence):
    o = out(decision="not_in_library", entry_ref=None, family="condenser cooling", action_ids=[],
            rationale="A cooling problem not in the library.")
    assert codes(run(library, evidence, o)) == ["family"]


# ---------- 5. the rationale ----------

@pytest.mark.parametrize("text", [
    "This looks like fault 13.",                       # a label
    "Typical of the Tennessee plant.",                 # the benchmark's name
    "XMEAS 7 is low.",                                 # a raw name
])
def test_a_leaking_rationale_fails(library, evidence, text):
    assert "rationale" in codes(run(library, evidence, out(rationale=text)))


@pytest.mark.parametrize("text", [
    "Reactor pressure fell 5% below normal.",
    "RX-FV-206 is at 98 percent open.",
    "Two readings 30 minutes apart agree.",
    "The pressure is 2.5 kPa low.",
])
def test_a_number_not_in_the_evidence_fails(library, evidence, text):
    assert codes(run(library, evidence, out(rationale=text))) == ["rationale"]


# ---------- several at once ----------

def test_every_failure_is_reported(library, evidence):
    o = out(entry_ref=f"{STICKING}@r1", family="feed composition", action_ids=["shut-down-the-reactor"],
            cited_evidence=cite(("provisional.tags.RX-PI-202", "high"), ("location.top_group", "reactor")),
            rationale="Fault 4, pressure down 5%.")
    assert set(codes(run(library, evidence, o))) == {"citation", "entry", "action", "family", "rationale"}


def test_the_check_reads_no_clock(library, evidence, monkeypatch):
    # as_of comes from the graph's state (decision 74); the check must never use now().
    import app.agent.faithfulness as mod

    class NoClock:
        @staticmethod
        def now(*a, **k):
            raise AssertionError("the faithfulness check read the clock")
    monkeypatch.setattr(mod, "datetime", NoClock, raising=False)
    assert run(library, evidence, out()) == []