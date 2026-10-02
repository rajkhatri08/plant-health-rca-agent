"""app/diagnosis: the shared item verdicts and the signature matcher (decisions 15, 19, 67-69).

The example entry is tests/test_library.revision(); its listed items and weights are:
  location.top_group             required   2
  location.top_tags              supporting 1
  provisional.tags.RX-FV-206     required   2
  provisional.loops.RX-TIC-204   supporting 1
  provisional.analyzers.RX-AI-211 supporting 1   (expects not_yet_available)
  provisional.masked             supporting 1
  revised.tags.RX-FV-206         required   2
so the total listed weight is 8 at the +30 min diagnosis and 10 at +60 min.

The item tests pass now. The scoring tests fail with NotImplementedError until Raj
implements score, rank, credit and decline in app/diagnosis/matcher.py.
"""

from datetime import timedelta
from fractions import Fraction as F

import pytest
import yaml

from app.diagnosis import items as it
from app.diagnosis import matcher as m
from app.library import schema, store
from eval import approve_entry as ap
from tests.test_approve_entry import features, provenance
from tests.test_library import ENTRY, OTHER, T0, accounts, approval, put, revision, root  # noqa: F401
from tests.test_walls import imported_top_modules, py_files

THIRD = "reactor-agitator-speed-drop"
WITHDRAWN = "reactor-feed-impurity-rise"


def rev(doc=None):
    return schema.Revision.model_validate(yaml.safe_load(yaml.safe_dump(doc or revision())))


def with_item(scope, kind, key, expect, entry_id=ENTRY):
    doc = revision(entry_id)
    doc["signature"][scope].setdefault(kind, {})[key] = expect
    return rev(doc)


def verdicts(r, f):
    return {i.name: i.verdict(f) for i in it.items(r.signature)}


def s(ref, rc, fit):
    """A hand-built Score for the ranking tests (only rc, fit and ref matter there)."""
    return m.Score(ref=f"{ref}@r1", entry_id=ref, required_contradictions=rc, agree_weight=0,
                   contradict_weight=0, total_weight=1, fit=F(fit), verdicts=())


def refs(ranking):
    return [tuple(x.entry_id for x in block) for block in ranking]


# ---------- shared verdicts (app/diagnosis/items.py) ----------

def test_items_in_fixed_order_with_scope_and_weight():
    got = [(i.name, i.scope, i.weight) for i in it.items(rev().signature)]
    assert got == [("location.top_group", "location", "required"),
                   ("location.top_tags", "location", "supporting"),
                   ("provisional.tags.RX-FV-206", "provisional", "required"),
                   ("provisional.loops.RX-TIC-204", "provisional", "supporting"),
                   ("provisional.analyzers.RX-AI-211", "provisional", "supporting"),
                   ("provisional.masked", "provisional", "supporting"),
                   ("revised.tags.RX-FV-206", "revised", "required")]


def test_exact_match_agrees_everywhere():
    assert set(verdicts(rev(), features()).values()) == {it.AGREE}


def test_contradictions():
    f = features(fv206="low", top_group="separator")
    f["location"]["top_tags"] = ["SP-TI-401", "SP-PI-403", "SP-LI-402"]
    f["provisional"]["loops"]["RX-TIC-204"] = "held"
    f["provisional"]["masked"] = False
    v = verdicts(rev(), f)
    assert v == {k: it.CONTRADICT for k in v} | {"provisional.analyzers.RX-AI-211": it.AGREE}


def test_one_of_agrees_with_any_listed_state():
    r = with_item("provisional", "tags", "RX-FV-206", {"one_of": ["high", "low"], "weight": "required"})
    for state, want in (("high", it.AGREE), ("low", it.AGREE), ("normal", it.CONTRADICT)):
        f = features()
        f["provisional"]["tags"]["RX-FV-206"] = state
        assert verdicts(r, f)["provisional.tags.RX-FV-206"] == want


def test_missing_reading_is_unknown():
    f = features()
    del f["revised"]
    assert verdicts(rev(), f)["revised.tags.RX-FV-206"] == it.UNKNOWN
    del f["provisional"]
    v = verdicts(rev(), f)
    assert {k for k, x in v.items() if x == it.UNKNOWN} == {k for k in v if not k.startswith("location")}


def test_analyzer_not_yet_available():
    # not accepted: unknown, not a contradiction; accepted (the example's item): agree
    r = with_item("provisional", "analyzers", "RX-AI-211", {"state": "high", "weight": "supporting"})
    assert verdicts(r, features())["provisional.analyzers.RX-AI-211"] == it.UNKNOWN
    f = features()
    f["provisional"]["analyzers"]["RX-AI-211"] = "low"
    assert verdicts(r, f)["provisional.analyzers.RX-AI-211"] == it.CONTRADICT
    assert verdicts(rev(), features())["provisional.analyzers.RX-AI-211"] == it.AGREE
    f = features()
    f["provisional"]["analyzers"]["RX-AI-211"] = "high"
    assert verdicts(rev(), f)["provisional.analyzers.RX-AI-211"] == it.CONTRADICT


def test_approval_gate_uses_the_shared_items():
    # one engine: the gate's items are items.items(), and only agree counts there
    assert not hasattr(ap, "_items")
    r = rev()
    assert [a["item"] for a in ap.agreement(r, provenance())] == [i.name for i in it.items(r.signature)]
    runs = [features() for _ in range(4)]
    del runs[0]["revised"]                      # unknown on one run counts against the item
    got = {a["item"]: a["agreed"] for a in ap.agreement(r, provenance(runs=runs))}
    assert got["revised.tags.RX-FV-206"] == 3 and got["provisional.tags.RX-FV-206"] == 4


# ---------- constants ----------

def test_decision_69_constants():
    assert m.WEIGHTS == {"required": 2, "supporting": 1}
    assert m.SCOPES == {"provisional": ("location", "provisional"),
                        "revised": ("location", "provisional", "revised")}


# ---------- score ----------

def test_exact_match_scores_full_fit():
    p = m.score(rev(), features(), "provisional")
    assert (p.ref, p.entry_id) == (f"{ENTRY}@r1", ENTRY)
    assert (p.required_contradictions, p.agree_weight, p.contradict_weight, p.total_weight, p.fit) \
        == (0, 8, 0, 8, F(1))
    r = m.score(rev(), features(), "revised")
    assert (r.required_contradictions, r.agree_weight, r.total_weight, r.fit) == (0, 10, 10, F(1))


def test_scope_by_diagnosis_time():
    names = [n for n, _ in m.score(rev(), features(), "provisional").verdicts]
    assert names == [i.name for i in it.items(rev().signature) if i.scope != "revised"]
    names = [n for n, _ in m.score(rev(), features(), "revised").verdicts]
    assert names == [i.name for i in it.items(rev().signature)]


def test_required_contradiction():
    f = features(fv206="low")                   # both readings
    p = m.score(rev(), f, "provisional")
    assert (p.required_contradictions, p.agree_weight, p.contradict_weight, p.fit) == (1, 6, 2, F(1, 2))
    r = m.score(rev(), f, "revised")
    assert (r.required_contradictions, r.agree_weight, r.contradict_weight, r.fit) == (2, 6, 4, F(1, 5))


def test_supporting_contradiction_isnt_required():
    f = features()
    f["provisional"]["masked"] = False
    p = m.score(rev(), f, "provisional")
    assert (p.required_contradictions, p.agree_weight, p.contradict_weight, p.fit) == (0, 7, 1, F(6, 8))


def test_one_of_scores_as_agree():
    doc = revision()
    doc["signature"]["provisional"]["tags"]["RX-FV-206"] = {"one_of": ["high", "low"], "weight": "required"}
    f = features(fv206="low")
    f["revised"]["tags"]["RX-FV-206"] = "high"
    assert m.score(rev(doc), f, "revised").fit == F(1)


def test_unknown_items_count_in_the_total_only():
    # supporting analyzer expecting high, observed not_yet_available: 7 of 8 agree
    r = with_item("provisional", "analyzers", "RX-AI-211", {"state": "high", "weight": "supporting"})
    p = m.score(r, features(), "provisional")
    assert (p.required_contradictions, p.agree_weight, p.contradict_weight, p.total_weight, p.fit) \
        == (0, 7, 0, 8, F(7, 8))
    # a required unknown isn't a required contradiction
    r = with_item("provisional", "analyzers", "RX-AI-211", {"state": "high", "weight": "required"})
    p = m.score(r, features(), "provisional")
    assert (p.required_contradictions, p.total_weight, p.fit) == (0, 9, F(7, 9))
    assert dict(p.verdicts)["provisional.analyzers.RX-AI-211"] == it.UNKNOWN


def test_missing_revised_reading():
    f = features()
    del f["revised"]
    r = m.score(rev(), f, "revised")
    assert (r.required_contradictions, r.agree_weight, r.contradict_weight, r.total_weight, r.fit) \
        == (0, 8, 0, 10, F(4, 5))
    assert m.score(rev(), f, "provisional").fit == F(1)


def test_fit_is_exact():
    assert isinstance(m.score(rev(), features(fv206="low"), "revised").fit, F)


# ---------- rank ----------

def test_rank_contradictions_first_then_fit():
    got = m.rank([s("a", 0, "1/2"), s("b", 1, 1), s("c", 0, "3/4")])
    assert refs(got) == [("c",), ("a",), ("b",)]


def test_rank_keeps_ties_in_one_block_by_ref():
    got = m.rank([s("d", 0, "1/2"), s("b", 1, 1), s("c", 0, "3/4"), s("a", 0, "1/2")])
    assert refs(got) == [("c",), ("a", "d"), ("b",)]


def test_rank_same_fit_different_contradictions_dont_tie():
    assert refs(m.rank([s("a", 1, 1), s("b", 0, 1)])) == [("b",), ("a",)]


def test_rank_empty():
    assert m.rank([]) == []


# ---------- credit ----------

RANKING = [(s("c", 0, 1),), (s("a", 0, "1/2"), s("d", 0, "1/2")), (s("b", 1, 1),)]


@pytest.mark.parametrize("entry, k, want", [
    ("c", 1, 1), ("a", 1, 0), ("a", 2, F(1, 2)), ("d", 2, F(1, 2)), ("a", 3, 1),
    ("b", 3, 0), ("b", 4, 1), ("missing", 3, 0)])
def test_credit(entry, k, want):
    assert m.credit(RANKING, entry, k) == want


def test_credit_tie_for_first_gives_one_over_m():
    ranking = [(s("a", 0, 1), s("b", 0, 1), s("c", 0, 1)), (s("d", 0, "1/2"),)]
    assert m.credit(ranking, "b", 1) == F(1, 3)
    assert m.credit(ranking, "b", 2) == F(2, 3)
    assert m.credit(ranking, "b", 3) == 1


def test_credit_block_lower_down():
    ranking = [(s("x", 0, 1),), (s("y", 0, "1/2"), s("z", 0, "1/2"), s("w", 0, "1/2"))]
    assert [m.credit(ranking, "z", k) for k in (1, 2, 3, 4)] == [0, F(1, 3), F(2, 3), 1]


# ---------- decline ----------

def test_decline_when_every_entry_has_a_required_contradiction():
    assert m.decline([(s("a", 1, 1),), (s("b", 2, 1),)], threshold=F(0))


def test_decline_when_top_fit_is_below_threshold():
    ranking = [(s("a", 0, "1/2"),), (s("b", 1, 1),)]
    assert m.decline(ranking, threshold=F(3, 4))
    assert not m.decline(ranking, threshold=F(1, 2))       # equal isn't below
    assert not m.decline(ranking, threshold=F(1, 4))


def test_decline_empty_ranking():
    assert m.decline([], threshold=F(0))


# ---------- as-of: only entries in force are candidates ----------

@pytest.fixture
def library(root, accounts):
    for e in (ENTRY, OTHER, THIRD, WITHDRAWN):
        put(root, "r1.yaml", revision(e), e)
    put(root, "r1.approval.yaml", approval(ENTRY, at=T0 + timedelta(hours=25)), ENTRY)
    put(root, "r1.approval.yaml", approval(THIRD, at=T0 + timedelta(hours=30)), THIRD)
    put(root, "r1.approval.yaml", approval(WITHDRAWN, at=T0 + timedelta(hours=25)), WITHDRAWN)
    put(root, "r2.yaml", revision(WITHDRAWN, k=2, created=T0 + timedelta(hours=1), withdrawn=True), WITHDRAWN)
    put(root, "r2.approval.yaml", approval(WITHDRAWN, k=2, at=T0 + timedelta(hours=26)), WITHDRAWN)
    return store.load(root, accounts)        # OTHER stays a draft


@pytest.mark.parametrize("hours, want", [
    (24, []), (25.5, [ENTRY, WITHDRAWN]), (27, [ENTRY]), (31, [THIRD, ENTRY])])
def test_candidates_are_the_entries_in_force(library, hours, want):
    got = m.candidates(library, T0 + timedelta(hours=hours))
    assert [r.entry_id for r in got] == want == sorted(want)        # by entry_id
    assert OTHER not in [r.entry_id for r in got]       # the draft never


def test_candidates_need_an_aware_time(library):
    with pytest.raises(ValueError):
        m.candidates(library, T0.replace(tzinfo=None))


def test_match_ranks_only_entries_in_force(library):
    got = m.match(library, features(), "provisional", T0 + timedelta(hours=31))
    assert sorted(x.entry_id for block in got for x in block) == [ENTRY, THIRD]
    assert all(x.ref.endswith("@r1") for block in got for x in block)


def test_match_refuses_an_unknown_diagnosis_time(library):
    with pytest.raises(ValueError):
        m.match(library, features(), "final", T0 + timedelta(hours=31))


# ---------- walls ----------

def test_app_diagnosis_imports_neither_eval_nor_ingest():
    files = list(py_files("app/diagnosis"))
    assert {p.name for p in files} >= {"items.py", "matcher.py"}
    hits = [f"{p.name}: {mod}" for p in files
            for mod in imported_top_modules(p.read_text()) & {"eval", "ingest", "dataset"}]
    assert hits == []