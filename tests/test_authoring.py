"""eval/authoring.py on synthetic runs (never data/): authoring runs only (LEAKAGE wall 3).

Static PCA, the Watch boundaries and the evidence normals are made first with their own
drivers on the calibration fixture, then the loaders serve only the authoring pool."""

import hashlib
import json

import numpy as np
import pytest
import yaml

import dataset.loader as loader_mod
from app.detector import features
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import approve_entry, authoring, cases, dev_table
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import evidence_normals, metrics, run_record
from ingest import tags as tagmap
from tests.test_approve_entry import commit
from tests.test_calibrate_driver import GAPS, GRID, setup  # noqa: F401 (fixture)
from tests.test_calibrate_watch import WGRID
from tests.test_fit_pca import FAST, two_factor_runs

NUMBERS = [94, 176, 178, 206, 301]
QUIET = 301                               # this run gets no step, so it isn't detected
REGISTER = tagmap.register()
ANALYZERS = [r["tag"] for r in REGISTER if r["kind"] == "analyzer"]
INTERVAL = {r["tag"]: r["update_interval_min"] // 3 for r in REGISTER if r["kind"] == "analyzer"}


def hold(x, interval, phase=0):
    """A held series: the value published on samples s with s % interval == phase."""
    out = x.copy()
    last = x[0]
    for i in range(len(x)):
        if (i + 1) % interval == phase:
            last = x[i]
        out[i] = last
    return out


def authoring_runs(fault):
    runs = two_factor_runs(numbers=NUMBERS, samples=120, seed=200 + fault)
    fast = tagmap.column_indices(VARIABLES, FAST)
    an = dict(zip(ANALYZERS, tagmap.column_indices(VARIABLES, ANALYZERS)))
    for k, x in runs.runs.items():
        if k != QUIET:
            x[20:, fast] += np.float32(1.5 + 0.3 * fault)
        for t, c in an.items():
            x[:, c] = hold(x[:, c], INTERVAL[t])
    return Runs("faulty_training", fault, "authoring", VARIABLES, runs.runs)


@pytest.fixture
def ready(setup, monkeypatch, tmp_path):
    drv.run(setup["model_path"], setup["out"], repo_root=setup["repo"], q_grid=GRID, gap_range=GAPS)
    watch = tmp_path / "models" / "watch.json"
    cw.run(setup["model_path"], setup["out"], watch, repo_root=setup["repo"], q_grid=WGRID)
    normals = tmp_path / "models" / "normals.json"
    evidence_normals.run(normals, repo_root=setup["repo"])
    calls = []

    def load_faulty(fault, pool):
        calls.append((fault, pool))
        if pool != "authoring" or fault not in authoring.AUTHORED:
            pytest.fail(f"authoring loaded fault {fault} from {pool}")
        return authoring_runs(fault)

    monkeypatch.setattr(loader_mod, "load_normal", lambda pool: pytest.fail(f"loaded normal {pool}"))
    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    return {**setup, "watch": watch, "normals": normals, "calls": calls,
            "prov": setup["repo"] / "eval" / "provenance"}


def author(c, **kw):
    return authoring.run(c["model_path"], c["out"], c["watch"], c["normals"], out_dir=c["prov"],
                         repo_root=c["repo"], **kw)


# ---------- publications from held series ----------

def test_publications_follow_the_schedule():
    x = np.array([1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0])          # changes at 2, 4, 6: every 2, phase 0
    assert authoring.publications_from_held(x, 2) == [(2, 2.0), (4, 3.0), (6, 4.0)]


def test_an_equal_consecutive_value_is_still_a_publication():
    # The value published at 4 equals the one at 2, so nothing changes there; the schedule
    # (set by the other changes) still counts it.
    x = np.array([1.0, 2.0, 2.0, 2.0, 2.0, 5.0, 5.0])
    assert authoring.publications_from_held(x, 2) == [(2, 2.0), (4, 2.0), (6, 5.0)]


def test_off_schedule_changes_are_refused():
    with pytest.raises(authoring.AuthoringError, match="off the 2-sample schedule"):
        authoring.publications_from_held(np.array([1.0, 2.0, 3.0, 3.0]), 2)
    with pytest.raises(authoring.AuthoringError, match="never changes"):
        authoring.publications_from_held(np.ones(10), 5)


def test_only_the_authored_faults():
    assert authoring.FAULTS == (1, 4, 5, 6, 13)
    assert authoring.SECOND_FAULTS == (2, 7, 8, 10, 11, 12, 14)
    assert authoring.AUTHORED == cases.KNOWN_FAULTS                # the 12 known faults
    for f in (3, 9, 15, 16, 20):
        with pytest.raises(authoring.AuthoringError):
            authoring.load_authoring(f)


# ---------- the whole run ----------

def test_loads_only_the_authoring_pool_of_the_authored_faults(ready):
    author(ready)
    assert ready["calls"] == [(f, "authoring") for f in authoring.FAULTS]


def test_provenance_files(ready):
    docs = author(ready)
    for f in authoring.FAULTS:
        path = ready["prov"] / f"fault_{f:02d}.yaml"
        text = path.read_text()
        assert text.startswith("# Builder side (LEAKAGE wall 3)")
        doc = yaml.safe_load(text)
        assert doc == docs[f]
        assert doc["pool"] == "authoring" and doc["runs"] == NUMBERS
        detected = [r for r in doc["per_run"] if r["detected"]]
        assert [r["run"] for r in doc["per_run"] if not r["detected"]] == [QUIET]
        assert all("features" not in r for r in doc["per_run"] if not r["detected"])
        s = doc["summary"]
        assert s["detected"] == len(detected) == 4 and s["runs"] == 5
        for name in ("provisional", "revised"):
            for tag, counts in s[name]["tags"].items():
                assert sum(counts.values()) == len(detected), (f, name, tag)
            assert len(s[name]["loops"]) == 19 and len(s[name]["analyzers"]) == 19
        assert sum(s["location"]["top_group"].values()) == len(detected)


def test_features_equal_a_direct_extraction(ready):
    docs = author(ready)
    lim = json.loads(ready["out"].read_text())
    watch = json.loads(ready["watch"].read_text())
    _, bands = evidence_normals.load_normals(ready["normals"], ready["repo"])
    model = ready["model"]
    plant = features.plant_from_files(model.tags)
    names = list(watch["groups"])
    runs = authoring_runs(5)
    k = NUMBERS[0]
    x = runs.runs[k]
    track = drv.tracks(drv.score_runs(model, runs, [k]), (lim["t2_lim"], lim["spe_lim"]), lim["n"],
                       lim["gap"], lim["warmup"])[k]
    det = metrics.detection(track, metrics.TRAIN_ONSET, warmup=lim["warmup"])
    by_group, by_tag = cw.rbc_runs(model, lim, runs, names)
    an = dict(zip(plant.analyzers, tagmap.column_indices(VARIABLES, plant.analyzers)))
    pubs = {t: authoring.publications_from_held(x[:, c], INTERVAL[t]) for t, c in an.items()}
    want = features.extract(plant, x[:, tagmap.column_indices(VARIABLES, model.tags)], pubs, bands,
                            det.sample, lim["n"],
                            by_group[k] / np.array([watch["groups"][g]["w"] for g in names]),
                            by_tag[k] / np.array([watch["tags"][t] for t in model.tags]), names)
    row = next(r for r in docs[5]["per_run"] if r["run"] == k)
    assert row["notification_sample"] == det.sample and row["features"] == want


def canonical(docs):
    """The provenance content that doesn't depend on when or where it ran: everything but
    the commit, dirty flag, record name and input record paths."""
    keep = {f: {k: v for k, v in d.items() if k not in ("commit", "dirty", "record", "inputs")}
            for f, d in docs.items()}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()


# SHA-256 of canonical(docs) from the pre-S3 authoring.py (commit b1c0edc) on this fixture.
# S3 moved the scoring path into eval/cases.py; the output must not change.
GOLDEN = "6bd02c7a3e8285287c48c9945480d7665b600fec3c2998b9914ee113569a6bf9"


def test_output_is_unchanged_since_the_scoring_path_moved(ready):
    assert canonical(author(ready)) == GOLDEN


def test_record_ties_the_files_and_inputs(ready):
    docs = author(ready)
    (path,) = (ready["repo"] / "eval" / "runs").glob("*_authoring.json")
    rec = json.loads(path.read_text())
    rel = path.relative_to(ready["repo"]).as_posix()
    assert all(d["record"] == rel for d in docs.values())
    for f in authoring.FAULTS:
        out = rec["outputs"][f"fault_{f:02d}"]
        assert out["sha256"] == run_record.sha256(ready["prov"] / f"fault_{f:02d}.yaml")
        assert rec["metrics"][f"fault_{f:02d}"]["detected"] == 4
    cfg = rec["config"]
    assert cfg["pool"] == "authoring" and cfg["runs"] == NUMBERS
    assert cfg["watch_record"].endswith("_calibrate_watch.json")
    assert cfg["normals_record"].endswith("_evidence_normals.json")
    assert cfg["readings"] == {"provisional": 10, "revised": 20}


def test_refuses_existing_provenance_before_loading(ready):
    ready["prov"].mkdir(parents=True)
    (ready["prov"] / "fault_04.yaml").write_text("kept")
    with pytest.raises(FileExistsError):
        author(ready)
    assert ready["calls"] == [] and (ready["prov"] / "fault_04.yaml").read_text() == "kept"


def test_refuses_dirty_tree_before_loading(ready):
    (ready["repo"] / "code.py").write_text("x = 2\n")
    with pytest.raises(run_record.RunRecordError):
        author(ready)
    assert ready["calls"] == []


def test_refuses_normals_without_a_record(ready):
    doc = json.loads(ready["normals"].read_text())
    doc["tags"]["RX-TI-204"] = [0.0, 1.0]
    ready["normals"].write_text(json.dumps(doc))
    with pytest.raises(evidence_normals.NormalsError):
        author(ready)
    assert ready["calls"] == []


def test_provenance_never_goes_to_the_library(ready):
    author(ready)
    assert authoring.DEFAULT_DIR.parts[-2:] == ("eval", "provenance")
    written = [p.relative_to(ready["repo"]).parts[0] for p in ready["repo"].rglob("*.yaml")
               if "provenance" in p.parts]
    assert written and set(written) == {"eval"}                 # nothing under library/
    assert not (ready["repo"] / "library").exists()


# ---------- the second seven (--faults, week 5 S4) ----------

def test_second_faults_write_only_their_own_files(ready):
    docs = author(ready, faults=(2, 11))
    assert ready["calls"] == [(2, "authoring"), (11, "authoring")]
    assert sorted(p.name for p in ready["prov"].iterdir()) == ["fault_02.yaml", "fault_11.yaml"]
    (path,) = (ready["repo"] / "eval" / "runs").glob("*_authoring.json")
    rec = json.loads(path.read_text())
    assert rec["config"]["faults"] == [2, 11] and set(rec["outputs"]) == {"fault_02", "fault_11"}
    for f in (2, 11):
        assert docs[f]["family"] == dev_table.FAMILIES[f] and docs[f]["runs"] == NUMBERS
        assert rec["outputs"][f"fault_{f:02d}"]["sha256"] == run_record.sha256(ready["prov"] / f"fault_{f:02d}.yaml")


def test_second_batch_leaves_the_first_five_untouched(ready):
    author(ready)
    commit(ready["repo"])
    first = {p.name: run_record.sha256(p) for p in ready["prov"].iterdir()}
    author(ready, faults=authoring.SECOND_FAULTS)
    assert {p.name: run_record.sha256(p) for p in ready["prov"].iterdir() if p.name in first} == first
    assert len(list(ready["prov"].iterdir())) == 12
    records = sorted((ready["repo"] / "eval" / "runs").glob("*_authoring.json"))
    assert len(records) == 2
    for p in ready["prov"].iterdir():                 # each file comes from exactly one record
        found, _ = approve_entry.authoring_record_for(p, ready["repo"])
        assert found is not None
        owners = [r for r in records if any(o["sha256"] == run_record.sha256(p)
                                            for o in json.loads(r.read_text())["outputs"].values())]
        assert len(owners) == 1


@pytest.mark.parametrize("faults", [
    (1,), (2, 4), (4, 5, 6, 13, 1),                    # the first five are never re-authored
    (3,), (9,), (15,), (16,), (20,),                   # no entry
    (), (2, 2),
])
def test_refuses_other_faults_before_loading(ready, faults):
    with pytest.raises(authoring.AuthoringError):
        author(ready, faults=faults)
    assert ready["calls"] == [] and not ready["prov"].exists()


def test_refuses_an_existing_second_file_before_loading(ready):
    ready["prov"].mkdir(parents=True)
    (ready["prov"] / "fault_07.yaml").write_text("kept")
    with pytest.raises(FileExistsError):
        author(ready, faults=(2, 7))
    assert ready["calls"] == [] and (ready["prov"] / "fault_07.yaml").read_text() == "kept"
    assert not (ready["prov"] / "fault_02.yaml").exists()


def test_main_refuses_a_first_five_fault():
    assert authoring.main(["--faults", "4"]) == 1
