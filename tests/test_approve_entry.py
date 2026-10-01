"""eval/approve_entry.py: the gated approval (decisions 16, 24, 67), in a throwaway git
repo holding a copy of the real tag register and loop map. The example draft is
tests/test_library.revision(); its provenance agrees with it on every detected run."""

import copy
import json
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from app.library import schema, store
from eval import approve_entry as ap
from eval import run_record
from tests.test_library import ENTRY, T0, revision

REPO = Path(__file__).resolve().parents[1]
NOW = T0 + timedelta(hours=25)
PROV = "eval/provenance/fault_04.yaml"


def features(fv206="high", top_group="reactor"):
    reading = {"tags": {"RX-FV-206": fv206}, "loops": {"RX-TIC-204": "compensating"},
               "analyzers": {"RX-AI-211": "not_yet_available"}, "masked": True}
    return {"location": {"top_group": top_group, "top_tags": ["RX-FV-206", "RX-TI-205", "RX-TI-204"]},
            "provisional": copy.deepcopy(reading), "revised": copy.deepcopy(reading)}


def provenance(family="reactor cooling", runs=None):
    runs = runs or [features() for _ in range(4)]
    per_run = [{"run": i, "detected": True, "features": f} for i, f in enumerate(runs, start=1)]
    per_run.append({"run": 99, "detected": False, "notification_sample": None, "delay_min": None})
    return {"fault": 4, "family": family, "pool": "authoring", "per_run": per_run}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "update", "--allow-empty")


def write(repo, rel, doc):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc) if rel.endswith(".json") else yaml.safe_dump(doc, sort_keys=False))
    return path


def record_authoring(repo, prov_rel=PROV):
    sha = run_record.sha256(repo / prov_rel)
    write(repo, "eval/runs/20261001T000000Z_authoring.json",
          {"name": "authoring", "dirty": False, "outputs": {"fault_04": {"path": prov_rel, "sha256": sha}}})


@pytest.fixture
def repo(git_repo):
    r = git_repo
    lib = r / "library"
    (lib / "entries").mkdir(parents=True)
    for name in ("tags.yaml", "loops.yaml"):
        shutil.copyfile(REPO / "library" / name, lib / name)
    write(r, "library/accounts.yaml", {"accounts": [
        {"id": "raj", "person": "raj", "roles": ["author"]},
        {"id": "raj-review", "person": "raj", "roles": ["approver"]},
        {"id": "claude", "person": "claude", "roles": ["reviewer"]},
        {"id": "sam", "person": "sam", "roles": ["approver"]}]})
    (r / "eval").mkdir(exist_ok=True)
    shutil.copyfile(REPO / "eval" / "sources.yaml", r / "eval" / "sources.yaml")
    write(r, f"library/entries/{ENTRY}/r1.yaml", revision(created=T0))
    write(r, PROV, provenance())
    record_authoring(r)
    write(r, "eval/entry_provenance.yaml", {"entries": {ENTRY: PROV}})
    write(r, "eval/runs/20261002T000000Z_entry_tests.json",
          {"name": "entry_tests", "dirty": False, "config": {"entry": f"{ENTRY}@r1"}, "metrics": {"passed": True}})
    commit(r)
    return r


def approve(repo, approver="raj-review", now=NOW, k=1):
    return ap.run(ENTRY, k, approver, repo_root=repo, now=now)


def approval_file(repo, k=1):
    return repo / "library" / "entries" / ENTRY / f"r{k}.approval.yaml"


def refused(repo, gate, capsys, **kw):
    with pytest.raises(ap.ApprovalError, match=gate):
        approve(repo, **kw)
    assert not approval_file(repo).exists()
    out = capsys.readouterr().out
    assert f"{gate:14s} FAIL" in out
    return out


# ---------- approved ----------

def test_all_gates_pass_and_the_approval_is_written(repo, capsys):
    doc = approve(repo)
    assert doc == {"entry_id": ENTRY, "revision": 1, "approver": "raj-review",
                   "approved_at": "2026-10-02T10:00:00Z", "checks": list(schema.REQUIRED_CHECKS),
                   "independent": False}
    assert yaml.safe_load(approval_file(repo).read_text()) == doc
    out = capsys.readouterr().out
    assert all(f"{g:14s} pass" in out for g in schema.REQUIRED_CHECKS)
    assert "self-approved (single-person demo)" in out
    lib = store.load(**ap.library_paths(repo))
    assert lib.get(ENTRY, NOW).approval_label == "self-approved (single-person demo)"


def test_another_person_makes_it_independent(repo):
    assert approve(repo, approver="sam")["independent"] is True


# ---------- each gate ----------

def test_schema_gate_unknown_source(repo, capsys):
    write(repo, f"library/entries/{ENTRY}/r1.yaml", revision(created=T0, sources=["src-999"]))
    commit(repo)
    refused(repo, "schema", capsys)


def test_schema_gate_library_that_doesnt_load(repo, capsys):
    write(repo, f"library/entries/{ENTRY}/r1.yaml", {**revision(created=T0), "family": "cooling"})
    commit(repo)
    refused(repo, "schema", capsys)


def test_leak_scan_gate(repo, capsys):
    write(repo, f"library/entries/{ENTRY}/r1.yaml",
          revision(created=T0, description="Behaves like fault 4 in the benchmark."))
    commit(repo)
    refused(repo, "leak_scan", capsys)


def test_provenance_gate_without_a_key(repo, capsys):
    write(repo, "eval/entry_provenance.yaml", {"entries": {}})
    commit(repo)
    refused(repo, "provenance", capsys)


def test_provenance_gate_file_not_from_an_authoring_record(repo, capsys):
    (repo / "eval/runs/20261001T000000Z_authoring.json").unlink()
    commit(repo)
    refused(repo, "provenance", capsys)


def test_provenance_gate_other_family(repo, capsys):
    write(repo, PROV, provenance(family="condenser cooling"))
    record_authoring(repo)
    commit(repo)
    refused(repo, "provenance", capsys)


def test_provenance_gate_required_item_must_agree_on_every_run(repo, capsys):
    write(repo, PROV, provenance(runs=[features()] * 3 + [features(fv206="normal")]))
    record_authoring(repo)
    commit(repo)
    out = refused(repo, "provenance", capsys)
    assert "provisional.tags.RX-FV-206 (required) agrees on 3 of 4 detected runs" in out
    assert "revised.tags.RX-FV-206 (required) agrees on 3 of 4 detected runs" in out


def test_supporting_items_need_half_the_runs(repo):
    # top_tags is supporting: present in 2 of 4 runs passes (0.5), 1 of 4 doesn't.
    off = features()
    off["location"]["top_tags"] = ["RX-TI-204", "RX-TI-205", "RX-PI-202"]
    rev = schema.Revision.model_validate(yaml.safe_load(yaml.safe_dump(revision())))
    assert ap.disagreements(rev, provenance(runs=[features()] * 2 + [off] * 2)) == []
    got = ap.disagreements(rev, provenance(runs=[features()] + [off] * 3))
    assert got == ["location.top_tags (supporting) agrees on 1 of 4 detected runs"]


def test_one_of_agrees_with_any_listed_state(repo):
    doc = revision()
    doc["signature"]["provisional"]["tags"]["RX-FV-206"] = {"one_of": ["high", "low"], "weight": "required"}
    rev = schema.Revision.model_validate(yaml.safe_load(yaml.safe_dump(doc)))
    runs = [features(), features(fv206="low"), features()]
    for f in runs:
        f["revised"]["tags"]["RX-FV-206"] = "high"
    assert ap.disagreements(rev, provenance(runs=runs)) == []


def test_agreement_counts(repo):
    rev = schema.Revision.model_validate(yaml.safe_load(yaml.safe_dump(revision())))
    got = {a["item"]: (a["weight"], a["agreed"], a["of"]) for a in ap.agreement(rev, provenance())}
    assert got["location.top_group"] == ("required", 4, 4)
    assert got["provisional.masked"] == ("supporting", 4, 4)
    assert set(got) == {"location.top_group", "location.top_tags", "provisional.tags.RX-FV-206",
                        "provisional.loops.RX-TIC-204", "provisional.analyzers.RX-AI-211",
                        "provisional.masked", "revised.tags.RX-FV-206"}


@pytest.mark.parametrize("record", [
    None,                                                                         # no record
    {"name": "entry_tests", "dirty": False, "config": {"entry": f"{ENTRY}@r2"}, "metrics": {"passed": True}},
    {"name": "entry_tests", "dirty": True, "config": {"entry": f"{ENTRY}@r1"}, "metrics": {"passed": True}},
    {"name": "entry_tests", "dirty": False, "config": {"entry": f"{ENTRY}@r1"}, "metrics": {"passed": False}},
])
def test_entry_tests_gate(repo, capsys, record):
    path = repo / "eval/runs/20261002T000000Z_entry_tests.json"
    path.unlink()
    if record:
        write(repo, "eval/runs/20261002T000000Z_entry_tests.json", record)
    commit(repo)
    refused(repo, "entry_tests", capsys)


def test_gap_24h_gate(repo, capsys):
    refused(repo, "gap_24h", capsys, now=T0 + timedelta(hours=23, minutes=59))


def test_every_failing_gate_is_reported_at_once(repo, capsys):
    write(repo, f"library/entries/{ENTRY}/r1.yaml",
          revision(created=T0, description="Behaves like fault 4."))
    (repo / "eval/runs/20261002T000000Z_entry_tests.json").unlink()
    commit(repo)
    with pytest.raises(ap.ApprovalError, match="leak_scan, entry_tests, gap_24h"):
        approve(repo, now=T0 + timedelta(hours=1))
    out = capsys.readouterr().out
    assert "schema         pass" in out and "provenance     pass" in out


# ---------- refusals ----------

@pytest.mark.parametrize("approver", ["raj", "claude", "nobody"])
def test_only_an_approver_account_other_than_the_authors(repo, approver):
    with pytest.raises(ap.ApprovalError, match="approver role|author"):
        approve(repo, approver=approver)
    assert not approval_file(repo).exists()


def test_never_overwrites_an_approval(repo):
    approve(repo)
    commit(repo)
    with pytest.raises(FileExistsError):
        approve(repo, approver="sam")
    assert yaml.safe_load(approval_file(repo).read_text())["approver"] == "raj-review"


def test_refuses_a_dirty_tree(repo):
    (repo / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        approve(repo)


def test_refuses_an_unknown_revision(repo):
    with pytest.raises(ap.ApprovalError, match="isn't in the library"):
        approve(repo, k=2)


def test_main_reports_errors(repo, monkeypatch, capsys):
    monkeypatch.setattr(run_record, "REPO_ROOT", repo)
    assert ap.main([ENTRY, "1", "--approver", "raj"]) == 1
    assert "error:" in capsys.readouterr().err


# ---------- the committed files ----------

def test_committed_entry_key_and_sources_load():
    assert isinstance(ap.load_entry_key(REPO / "eval" / "entry_provenance.yaml"), dict)
    assert "src-001" in ap.load_sources(REPO / "eval" / "sources.yaml")


def test_entry_key_refusals(tmp_path):
    path = tmp_path / "key.yaml"
    path.write_text(yaml.safe_dump({"entries": {"a-b": "x.yaml", "c-d": "x.yaml"}}))
    with pytest.raises(ap.ApprovalError, match="two entries"):
        ap.load_entry_key(path)
    path.write_text(yaml.safe_dump({"entries": {"Fault 4": "x.yaml"}}))
    with pytest.raises(ap.ApprovalError):
        ap.load_entry_key(path)

# ---------- --check: report the gates on a dirty tree, write nothing ----------

def test_check_on_an_uncommitted_draft(repo, capsys):
    # A draft written but not committed: --check runs, reports, writes nothing.
    write(repo, f"library/entries/{ENTRY}/r1.yaml",
          revision(created=T0, description="Behaves like fault 4."))
    failed = ap.check(ENTRY, 1, repo_root=repo, now=T0 + timedelta(hours=1))
    assert set(failed) == {"leak_scan", "gap_24h"}
    out = capsys.readouterr().out
    assert "leak_scan      FAIL" in out and "schema         pass" in out
    assert "approvable by the 24 h gap from 2026-10-02T09:00:00Z" in out
    assert "check only: nothing written; failing: leak_scan, gap_24h" in out
    assert not approval_file(repo).exists()


def test_check_passes_when_every_gate_does(repo, capsys):
    (repo / "code.py").write_text("x = 2\n")                    # dirty: --check doesn't mind
    assert ap.check(ENTRY, 1, "raj-review", repo_root=repo, now=NOW) == {}
    out = capsys.readouterr().out
    assert "approver       pass (raj-review)" in out and "every gate passes" in out
    assert not approval_file(repo).exists()


def test_check_reports_an_approver_that_cant_approve(repo, capsys):
    failed = ap.check(ENTRY, 1, "raj", repo_root=repo, now=NOW)
    assert list(failed) == ["approver"] and "approver role" in failed["approver"][0]


def test_check_after_an_approval_still_only_reports(repo):
    approve(repo)
    before = approval_file(repo).read_text()
    assert ap.check(ENTRY, 1, repo_root=repo, now=NOW) == {}
    assert approval_file(repo).read_text() == before


def test_main_check_exit_codes(repo, monkeypatch, capsys):
    monkeypatch.setattr(run_record, "REPO_ROOT", repo)
    monkeypatch.setattr(ap, "_now", lambda now=None: NOW)
    assert ap.main([ENTRY, "1", "--check"]) == 0
    (repo / "eval/runs/20261002T000000Z_entry_tests.json").unlink()
    assert ap.main([ENTRY, "1", "--check"]) == 1
    assert not approval_file(repo).exists()
    with pytest.raises(SystemExit):
        ap.main([ENTRY, "1"])                                    # --approver needed without --check
