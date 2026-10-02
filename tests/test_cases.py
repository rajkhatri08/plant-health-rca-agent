"""eval/cases.py on synthetic runs (never data/): the shared scoring path, by fault and pool.

The inputs (static PCA, Watch boundaries, evidence normals) are made with their own
drivers on the calibration fixture, as in tests/test_authoring.py. The loader serves only
what each test allows and records every call."""

import json

import pytest

import dataset.loader as loader_mod
from dataset.loader import Runs
from eval import authoring, cases, dev_table, run_record
from tests.test_approve_entry import commit
from tests.test_authoring import NUMBERS, QUIET, authoring_runs, author, ready  # noqa: F401
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)


def runs_for(fault, pool):
    r = authoring_runs(fault)
    return Runs(r.name, fault, pool, r.columns, r.runs)


@pytest.fixture
def ctx(ready, monkeypatch, tmp_path):
    """ready's inputs, with a loader that serves any pool and records the calls."""
    calls = []

    def load_faulty(fault, pool):
        calls.append((fault, pool))
        return runs_for(fault, pool)

    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    return {**ready, "calls": calls, "cases_root": tmp_path / "data" / "cases"}


def make(c, pool, faults, **kw):
    return cases.run(pool, faults, c["model_path"], c["out"], c["watch"], c["normals"],
                     out_root=c["cases_root"], repo_root=c["repo"], **kw)


# ---------- constants ----------

def test_known_faults_are_protocols_twelve():
    assert cases.KNOWN_FAULTS == (1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14)
    assert set(cases.KNOWN_FAULTS) == set(dev_table.FAMILIES)
    assert cases.POOLS == ("authoring", "dev", "forest_ceiling")


def test_cases_go_under_gitignored_data():
    assert cases.DEFAULT_DIR.parts[-2:] == ("data", "cases")
    gitignore = (run_record.Path(__file__).resolve().parents[1] / ".gitignore").read_text().split()
    assert "data/" in gitignore


# ---------- one path: authoring calls it ----------

def test_authoring_uses_the_shared_path():
    assert authoring.publications_from_held is cases.publications_from_held
    assert authoring.AuthoringError is cases.CasesError


def test_same_per_run_as_authoring(ctx):
    docs = author(ctx)
    commit(ctx["repo"])                     # authoring wrote provenance files into the repo
    paths, _ = make(ctx, "authoring", (1, 4))
    for f in (1, 4):
        got = json.loads(paths[f].read_text())
        assert got["per_run"] == docs[f]["per_run"]
        assert got["inputs"] == docs[f]["inputs"]


# ---------- a run ----------

def test_dev_cases_files_and_record(ctx):
    paths, record = make(ctx, "dev", (2, 11))
    assert ctx["calls"] == [(2, "dev"), (11, "dev")]
    rec = json.loads(record.read_text())
    rel = record.relative_to(ctx["repo"]).as_posix()
    assert rec["name"] == "cases" and rec["dirty"] is False
    assert rec["config"]["pool"] == "dev" and rec["config"]["faults"] == [2, 11]
    assert rec["config"]["readings"] == {"provisional": 10, "revised": 20}
    assert rec["config"]["watch_record"].endswith("_calibrate_watch.json")
    for f in (2, 11):
        path = paths[f]
        assert path.parent.parent == ctx["cases_root"] and path.parent.name.endswith("_dev")
        assert rec["outputs"][f"fault_{f:02d}"]["sha256"] == run_record.sha256(path)
        doc = json.loads(path.read_text())
        assert (doc["fault"], doc["family"], doc["pool"], doc["record"]) == \
            (f, dev_table.FAMILIES[f], "dev", rel)
        assert doc["runs"] == NUMBERS
        detected = [r for r in doc["per_run"] if r["detected"]]
        assert [r["run"] for r in doc["per_run"] if not r["detected"]] == [QUIET]
        assert all({"location", "provisional", "revised"} <= set(r["features"]) for r in detected)
        assert rec["metrics"][f"fault_{f:02d}"] == {"runs": 5, "detected": len(detected)}


def test_default_is_all_twelve_known_faults(ctx):
    make(ctx, "forest_ceiling", cases.KNOWN_FAULTS)
    assert ctx["calls"] == [(f, "forest_ceiling") for f in cases.KNOWN_FAULTS]


# ---------- refusals, all before loading ----------

@pytest.mark.parametrize("pool, faults", [
    ("calibration", (1,)), ("test", (1,)),                       # not a faulty training pool
    ("dev", (3,)), ("dev", (9,)), ("dev", (15,)),                # excluded: no entry, no case
    ("dev", (16,)), ("dev", (20,)),                              # quarantined
    ("dev", ()), ("dev", (1, 1)),
])
def test_refuses_bad_requests_before_loading(ctx, pool, faults):
    with pytest.raises(cases.CasesError):
        make(ctx, pool, faults)
    assert ctx["calls"] == []


def test_refuses_dirty_tree_before_loading(ctx):
    (ctx["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        make(ctx, "dev", (2,))
    assert ctx["calls"] == []


def test_never_overwrites(ctx):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
    make(ctx, "dev", (2,), now=now)
    n = len(ctx["calls"])
    with pytest.raises((FileExistsError, run_record.RunRecordError)):
        make(ctx, "dev", (2,), now=now)
    assert len(ctx["calls"]) == n                                # refused before loading


def test_main_refuses_an_unknown_pool():
    with pytest.raises(SystemExit):
        cases.main(["calibration"])