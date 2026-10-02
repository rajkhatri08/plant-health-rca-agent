"""eval/entry_tests.py: decision 71's entry tests, in a throwaway git repo holding a copy
of the real tag register and loop map (as tests/test_approve_entry.py).

Two synthetic entries, distinguished by one required tag:
- ENTRY expects RX-FV-206 high (tests/test_library.revision())
- OTHER expects it low
Each has a provenance file of 4 detected runs (plus one undetected) that fits it exactly.
"""

import json
from datetime import timedelta

import pytest
import yaml

from app.library import schema
from eval import approve_entry as ap
from eval import entry_tests as et
from eval import run_record
from tests.test_approve_entry import REPO, commit, features, provenance, write
from tests.test_library import ENTRY, OTHER, T0, approval, revision

NOW = T0 + timedelta(hours=30)
PROV = {ENTRY: "eval/provenance/fault_04.yaml", OTHER: "eval/provenance/fault_11.yaml"}


def low_rev(entry_id=OTHER, **kw):
    doc = revision(entry_id, **kw)
    doc["signature"]["provisional"]["tags"]["RX-FV-206"]["state"] = "low"
    doc["signature"]["revised"]["tags"]["RX-FV-206"]["state"] = "low"
    return doc


def put_provenance(repo, entries):
    """Provenance files for {entry_id: [features, ...]}, one committed authoring record
    naming them all, and the entry key."""
    outputs = {}
    for e, runs in entries.items():
        rel = PROV.get(e, f"eval/provenance/{e}.yaml")
        write(repo, rel, provenance(runs=runs))
        outputs[e] = {"path": rel, "sha256": run_record.sha256(repo / rel)}
    write(repo, "eval/runs/20261001T000000Z_authoring.json",
          {"name": "authoring", "dirty": False, "outputs": outputs})
    write(repo, "eval/entry_provenance.yaml",
          {"entries": {e: PROV.get(e, f"eval/provenance/{e}.yaml") for e in entries}})


@pytest.fixture
def repo(git_repo):
    r = git_repo
    lib = r / "library"
    (lib / "entries").mkdir(parents=True)
    for name in ("tags.yaml", "loops.yaml"):
        (lib / name).write_text((REPO / "library" / name).read_text())
    (r / "eval").mkdir(exist_ok=True)
    (r / "eval" / "sources.yaml").write_text((REPO / "eval" / "sources.yaml").read_text())
    write(r, "library/accounts.yaml", {"accounts": [
        {"id": "raj", "person": "raj", "roles": ["author"]},
        {"id": "raj-review", "person": "raj", "roles": ["approver"]},
        {"id": "claude", "person": "claude", "roles": ["reviewer"]}]})
    write(r, f"library/entries/{ENTRY}/r1.yaml", revision(created=T0))
    put_provenance(r, {ENTRY: [features() for _ in range(4)]})
    commit(r)
    return r


def add_other(repo, approved=True, doc=None, runs=None):
    write(repo, f"library/entries/{OTHER}/r1.yaml", doc or low_rev(created=T0))
    if approved:
        write(repo, f"library/entries/{OTHER}/r1.approval.yaml", approval(OTHER, at=T0 + timedelta(hours=25)))
    put_provenance(repo, {ENTRY: [features() for _ in range(4)],
                          OTHER: runs or [features(fv206="low") for _ in range(4)]})
    commit(repo)


def run(repo, entry_id=ENTRY, k=1, now=NOW, **kw):
    return et.run(entry_id, k, repo_root=repo, now=now, **kw)


def record(path):
    return json.loads(path.read_text())


# ---------- passing ----------

def test_alone_passes_and_the_record_has_the_gates_shape(repo):
    passed, path = run(repo)
    rec = record(path)
    assert passed and path.name.endswith("_entry_tests.json")
    assert rec["config"]["entry"] == f"{ENTRY}@r1" and rec["dirty"] is False
    assert rec["metrics"]["passed"] is True
    assert rec["config"]["library"] == {ENTRY: f"{ENTRY}@r1"}
    assert rec["config"]["provenance"] == {ENTRY: PROV[ENTRY]}
    assert rec["config"]["revision_sha256"][ENTRY] == run_record.sha256(
        repo / "library" / "entries" / ENTRY / "r1.yaml")
    assert rec["metrics"]["runs"] == {ENTRY: 4}             # the undetected run isn't a case


def test_the_approval_gate_accepts_the_record(repo):
    run(repo)
    commit(repo)
    problems, _, _ = ap.gates(ENTRY, 1, repo, NOW)
    assert problems["entry_tests"] == []


def test_a_distinct_approved_entry_passes_both_ways(repo):
    add_other(repo)
    passed, path = run(repo)
    assert passed
    assert record(path)["config"]["library"] == {ENTRY: f"{ENTRY}@r1", OTHER: f"{OTHER}@r1"}


def test_a_tie_with_a_twin_passes(repo):
    # OTHER has ENTRY's signature: they tie everywhere, which decision 71 allows
    add_other(repo, doc=revision(OTHER, created=T0), runs=[features() for _ in range(4)])
    assert run(repo)[0]


# ---------- failing ----------

def test_self_fails_on_a_required_contradiction(repo, capsys):
    put_provenance(repo, {ENTRY: [features()] * 3 + [features(fv206="normal")]})
    commit(repo)
    passed, path = run(repo)
    out = capsys.readouterr().out
    assert not passed and record(path)["metrics"]["passed"] is False
    assert "required contradiction(s) on its own run 4 at provisional" in out
    assert record(path)["metrics"]["self_failures"] == 2          # both diagnosis times


def test_self_fails_when_not_first(repo, capsys):
    # OTHER is broader (top group only) and fits ENTRY's runs fully; ENTRY expects masked
    # False, so its fit drops below OTHER's on its own runs
    broad = revision(OTHER, created=T0)
    broad["signature"] = {"location": {"top_group": {"one_of": ["reactor"], "weight": "required"}}}
    narrow = revision(created=T0)
    narrow["signature"]["provisional"]["masked"]["state"] = False
    write(repo, f"library/entries/{ENTRY}/r1.yaml", narrow)
    add_other(repo, doc=broad, runs=[features() for _ in range(4)])
    passed, path = run(repo)
    out = capsys.readouterr().out
    assert not passed
    assert f"{ENTRY}: not first on its own run" in out
    assert record(path)["metrics"]["self_failures"] == 8           # 4 runs x 2 times


def test_specificity_fails_when_the_subject_outranks_an_approved_entry(repo, capsys):
    # subject: broad (top group only); OTHER (approved): expects masked False, so on its
    # own runs the broad subject ranks strictly above it. Regression flags OTHER too.
    broad = revision(created=T0)
    broad["signature"] = {"location": {"top_group": {"one_of": ["reactor"], "weight": "required"}}}
    write(repo, f"library/entries/{ENTRY}/r1.yaml", broad)
    other = revision(OTHER, created=T0)
    other["signature"]["provisional"]["masked"]["state"] = False
    add_other(repo, doc=other, runs=[features() for _ in range(4)])
    passed, path = run(repo)
    out = capsys.readouterr().out
    m = record(path)["metrics"]
    assert not passed and m["self_failures"] == 0
    assert m["specificity_failures"] == 8 and m["regression_failures"] == 8
    assert f"{ENTRY}: ranks above {OTHER} on {OTHER}'s run" in out
    assert f"{OTHER}: not first on its own run" in out


def test_no_detected_run_fails(repo):
    doc = provenance(runs=[features()])
    doc["per_run"] = [r for r in doc["per_run"] if not r["detected"]]
    write(repo, PROV[ENTRY], doc)
    write(repo, "eval/runs/20261001T000000Z_authoring.json", {"name": "authoring", "dirty": False,
          "outputs": {"x": {"path": PROV[ENTRY], "sha256": run_record.sha256(repo / PROV[ENTRY])}}})
    commit(repo)
    passed, path = run(repo)
    assert not passed and record(path)["metrics"]["self_failures"] == 1


# ---------- which library ----------

def test_other_drafts_are_left_out(repo):
    add_other(repo, approved=False)
    passed, path = run(repo)
    assert passed and record(path)["config"]["library"] == {ENTRY: f"{ENTRY}@r1"}


def test_an_approval_after_as_of_is_left_out(repo):
    add_other(repo)
    _, path = run(repo, now=T0 + timedelta(hours=24, minutes=30))
    assert set(record(path)["config"]["library"]) == {ENTRY}


def test_the_subject_replaces_its_own_entry(repo):
    write(repo, f"library/entries/{ENTRY}/r1.approval.yaml", approval(ENTRY, at=T0 + timedelta(hours=25)))
    write(repo, f"library/entries/{ENTRY}/r2.yaml", revision(k=2, created=T0 + timedelta(hours=26)))
    commit(repo)
    passed, path = run(repo, k=2)
    rec = record(path)
    assert passed and rec["config"]["entry"] == f"{ENTRY}@r2"
    assert rec["config"]["library"] == {ENTRY: f"{ENTRY}@r2"}


def test_the_subject_can_be_the_approved_revision(repo):
    write(repo, f"library/entries/{ENTRY}/r1.approval.yaml", approval(ENTRY, at=T0 + timedelta(hours=25)))
    commit(repo)
    assert run(repo)[0]


# ---------- refusals ----------

def test_refuses_an_unknown_revision(repo):
    with pytest.raises(et.EntryTestError):
        run(repo, k=2)


def test_refuses_an_entry_without_provenance(repo):
    add_other(repo)
    write(repo, "eval/entry_provenance.yaml", {"entries": {ENTRY: PROV[ENTRY]}})
    commit(repo)
    with pytest.raises(et.EntryTestError, match=f"{OTHER} has no provenance file"):
        run(repo)


def test_refuses_provenance_no_authoring_record_wrote(repo):
    doc = yaml.safe_load((repo / PROV[ENTRY]).read_text())
    doc["per_run"][0]["run"] = 7                               # changed after the record
    write(repo, PROV[ENTRY], doc)
    commit(repo)
    with pytest.raises(et.EntryTestError, match="isn't an output of a committed authoring run record"):
        run(repo)


def test_refuses_a_dirty_tree_and_writes_nothing(repo):
    (repo / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        run(repo)
    assert not list((repo / "eval" / "runs").glob("*_entry_tests.json"))


def test_allow_dirty_writes_a_record_the_gate_ignores(repo):
    (repo / "code.py").write_text("x = 2\n")
    passed, path = run(repo, allow_dirty=True)
    assert passed and record(path)["dirty"] is True
    problems, _, _ = ap.gates(ENTRY, 1, repo, NOW)
    assert problems["entry_tests"]


def test_writes_nothing_under_library(repo):
    before = sorted(p.relative_to(repo) for p in (repo / "library").rglob("*"))
    run(repo)
    assert sorted(p.relative_to(repo) for p in (repo / "library").rglob("*")) == before


def test_main_exit_codes(repo, monkeypatch):
    monkeypatch.setattr(run_record, "REPO_ROOT", repo)
    monkeypatch.setattr(et, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    assert et.main([ENTRY, "1"]) == 0
    assert et.main([ENTRY, "9"]) == 1


def test_both_diagnosis_times():
    assert et.TIMES == ("provisional", "revised")
    assert schema.REQUIRED_CHECKS[4] == "entry_tests"