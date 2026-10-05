"""The loader (decision 49): runs by pool, one assignment for every file, sealed data refused.

Runs on a synthetic open-data repo under tmp_path. Values encode where they came from:
column 0 = run number, column 1 = sample, column 2 = fault.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
import yaml

import dataset.loader as loader_mod
from dataset.convert import ID_COLUMNS, VARIABLES, output_path
from dataset.loader import LoaderError

REPO = Path(__file__).resolve().parents[1]
RUNS, SAMPLES = 500, 3
POOLS = yaml.safe_load((REPO / "dataset" / "splits.yaml").read_text())


def _table(fault, runs=RUNS, samples=SAMPLES, seed=0):
    r, s = np.meshgrid(np.arange(1, runs + 1), np.arange(1, samples + 1), indexing="ij")
    r, s = r.ravel(), s.ravel()
    rng = np.random.default_rng(seed)
    cols = {"faultNumber": np.full(r.size, fault, np.int16), "simulationRun": r.astype(np.int16),
            "sample": s.astype(np.int16)}
    for i, c in enumerate(VARIABLES):
        cols[c] = {0: r, 1: s, 2: np.full(r.size, fault)}.get(i, rng.normal(size=r.size)).astype(np.float32)
    perm = rng.permutation(r.size)  # shuffled rows: the loader must sort
    return pa.table({k: v[perm] for k, v in cols.items()})


class OpenRepo:
    def __init__(self, root):
        self.root = root / "repo"
        self.data = self.root / "data"
        self.sealed = root / "sealed"
        (self.root / "dataset").mkdir(parents=True)
        (self.root / "dataset" / "splits.yaml").write_bytes((REPO / "dataset" / "splits.yaml").read_bytes())
        self.hashes = {"fault_free_training": {}, "faulty_training": {}}
        self.write("fault_free_training", 0, _table(0))
        for f in range(1, 16):
            self.write("faulty_training", f, _table(f, seed=f))
        # A sealed file the loader must never reach.
        sealed_file = output_path(self.sealed / "converted", "faulty_training", 16)
        sealed_file.parent.mkdir(parents=True)
        pq.write_table(_table(16), sealed_file)
        self.sealed_file = sealed_file
        self.save_manifest()

    def write(self, name, fault, table):
        path = output_path(self.data, name, fault)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)
        self.hashes[name][str(path.relative_to(self.data))] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def save_manifest(self):
        splits_sha = hashlib.sha256((self.root / "dataset" / "splits.yaml").read_bytes()).hexdigest()
        manifest = {
            "raw_files": {
                "fault_free_training": {"faults": [0], "runs_per_fault": RUNS, "samples_per_run": SAMPLES},
                "faulty_training": {"faults": list(range(1, 21)), "runs_per_fault": RUNS,
                                    "samples_per_run": SAMPLES}},
            "splits": {"file": "dataset/splits.yaml", "sha256": splits_sha},
            "conversion": {"open_reports": {n: {"files": f} for n, f in self.hashes.items()}},
        }
        (self.root / "dataset" / "manifest.yaml").write_text(yaml.safe_dump(manifest))


@pytest.fixture(scope="module")
def _built(tmp_path_factory):
    return OpenRepo(tmp_path_factory.mktemp("open"))


@pytest.fixture
def repo(_built, monkeypatch):
    monkeypatch.setattr(loader_mod, "REPO_ROOT", _built.root)
    monkeypatch.setattr(loader_mod, "SEALED_ROOT", _built.sealed)
    return _built


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    """A repo tests may modify."""
    r = OpenRepo(tmp_path)
    monkeypatch.setattr(loader_mod, "REPO_ROOT", r.root)
    monkeypatch.setattr(loader_mod, "SEALED_ROOT", r.sealed)
    return r


# Rule 1: one assignment, by run number, for every file.

@pytest.mark.parametrize("pool", ["fit", "early_stop", "calibration", "dev"])
def test_normal_pool_returns_exactly_its_numbers(repo, pool):
    runs = loader_mod.load_normal(pool)
    assert sorted(runs.runs) == POOLS["pools"][pool]
    assert runs.columns == VARIABLES
    for k, a in runs.runs.items():
        assert a.shape == (SAMPLES, len(VARIABLES)) and a.dtype == np.float32
        assert (a[:, 0] == k).all() and (a[:, 1] == np.arange(1, SAMPLES + 1)).all()
        assert (a[:, 2] == 0).all()


def test_faulty_dev_uses_the_dev_numbers_for_every_fault(repo):
    dev = sorted(loader_mod.load_normal("dev").runs)
    assert dev == POOLS["pools"]["dev"]
    for f in range(1, 16):
        runs = loader_mod.load_faulty(f, "dev").runs
        assert sorted(runs) == dev
        assert all((a[:, 2] == f).all() and (a[:, 0] == k).all() for k, a in runs.items())


# Rule 2: authoring and forest runs never use a dev number.

def test_authoring_same_five_for_every_fault_and_never_dev(repo):
    dev = set(POOLS["pools"]["dev"])
    sets = {f: sorted(loader_mod.load_faulty(f, "authoring").runs) for f in range(1, 16)}
    assert all(s == POOLS["authoring"] for s in sets.values())
    assert len(POOLS["authoring"]) == 5 and not set(POOLS["authoring"]) & dev


def test_forest_ceiling_never_dev_or_authoring(repo):
    runs = set(loader_mod.load_faulty(4, "forest_ceiling").runs)
    assert len(runs) == 445
    assert not runs & set(POOLS["pools"]["dev"]) and not runs & set(POOLS["authoring"])


@pytest.mark.parametrize("pool", ["fit", "early_stop", "calibration", "test", "all"])
def test_faulty_runs_refused_outside_their_pools(repo, pool):
    with pytest.raises(LoaderError, match="faulty runs come only from"):
        loader_mod.load_faulty(1, pool)


@pytest.mark.parametrize("pool", ["authoring", "forest_ceiling", "test", "all"])
def test_unknown_normal_pool_refused(repo, pool):
    with pytest.raises(LoaderError, match="unknown normal pool"):
        loader_mod.load_normal(pool)


# Sealed data: never reachable without EVAL_MODE (conftest unsets it; no test sets it).

@pytest.mark.parametrize("fault", [16, 17, 18, 19, 20])
def test_quarantined_faults_refused(repo, fault):
    with pytest.raises(LoaderError, match="sealed"):
        loader_mod.load_faulty(fault, "dev")


@pytest.mark.parametrize("fault", [0, 21, -1])
def test_non_open_fault_numbers_refused(repo, fault):
    with pytest.raises(LoaderError, match="isn't an open fault"):
        loader_mod.load_faulty(fault, "dev")


@pytest.mark.parametrize("fault", [True, 1.0, "1"])
def test_fault_must_be_int(repo, fault):
    with pytest.raises(LoaderError, match="must be an int"):
        loader_mod.load_faulty(fault, "dev")


@pytest.mark.parametrize("fault", [0, 1, 16])
def test_test_split_refused_without_eval_mode(repo, fault):
    # conftest unsets EVAL_MODE; nothing is logged, because nothing was attempted.
    with pytest.raises(LoaderError, match="EVAL_MODE=1"):
        loader_mod.load_testing(fault, purpose="test")
    assert not (repo.root / "eval" / "test_access.log").exists()


def test_check_path_refuses_sealed_folder(repo):
    with pytest.raises(LoaderError, match="sealed folder"):
        loader_mod.check_path(repo.sealed_file)


def test_check_path_refuses_traversal_out_of_data(repo):
    sneaky = repo.data / ".." / ".." / "sealed" / "converted" / "faulty_training" / "fault_16.parquet"
    with pytest.raises(LoaderError, match="sealed folder"):
        loader_mod.check_path(sneaky)
    with pytest.raises(LoaderError, match="outside <repo>/data"):
        loader_mod.check_path(repo.data / ".." / "dataset" / "manifest.yaml")


def test_symlink_into_sealed_folder_refused(scratch_repo):
    target = output_path(scratch_repo.data, "faulty_training", 1)
    target.unlink()
    target.symlink_to(scratch_repo.sealed_file)
    with pytest.raises(LoaderError, match="sealed folder"):
        loader_mod.load_faulty(1, "dev")


# Integrity: the files and the pools are the manifest's versions.

def test_changed_data_file_refused(scratch_repo):
    path = output_path(scratch_repo.data, "fault_free_training", 0)
    pq.write_table(_table(0, seed=99), path)
    with pytest.raises(LoaderError, match="SHA-256"):
        loader_mod.load_normal("fit")


def test_edited_splits_refused(scratch_repo):
    p = scratch_repo.root / "dataset" / "splits.yaml"
    p.write_text(p.read_text().replace("fit: [1,", "fit: [2,", 1))
    with pytest.raises(LoaderError, match="pools unavailable"):
        loader_mod.load_normal("fit")


def test_missing_run_refused(scratch_repo):
    t = _table(0)
    t = t.filter(pc.not_equal(t["simulationRun"], 7))
    scratch_repo.write("fault_free_training", 0, t)
    scratch_repo.save_manifest()
    with pytest.raises(LoaderError, match="expected"):
        loader_mod.load_normal("fit")


def test_wrong_fault_in_file_refused(scratch_repo):
    scratch_repo.write("faulty_training", 2, _table(3))
    scratch_repo.save_manifest()
    with pytest.raises(LoaderError, match="all fault 2"):
        loader_mod.load_faulty(2, "dev")


def test_default_roots_reach_nothing():
    # conftest points the loader at paths that don't exist.
    with pytest.raises(LoaderError):
        loader_mod.load_normal("fit")


# The test split (week 7 S1): only under EVAL_MODE, on a clean tree, logged, checksummed.
# A synthetic sealed folder under tmp_path. No test sets EVAL_MODE: eval_mode is replaced.

TEST_SAMPLES = 4


class SealedRepo(OpenRepo):
    """An OpenRepo with testing files (faults 0, 1, 16) and their conversion reports in its
    sealed folder, committed to git so the clean-tree check can pass."""

    def __init__(self, root):
        super().__init__(root)
        self.converted = self.sealed / "converted"
        self.reports = {}
        files = {"fault_free_testing": {}, "faulty_testing": {}}
        for fault in (0, 1, 16):
            name = "fault_free_testing" if fault == 0 else "faulty_testing"
            path = output_path(self.converted, name, fault)
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(_table(fault, samples=TEST_SAMPLES, seed=100 + fault), path)
            files[name][str(path.relative_to(self.converted))] = {
                "rows": RUNS * TEST_SAMPLES, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for name, f in files.items():
            report = self.converted / f"conversion_report_{name}.json"
            report.write_text(json.dumps({"name": name, "side": "sealed", "files": f}))
            self.reports[name] = hashlib.sha256(report.read_bytes()).hexdigest()
        self.save_manifest()
        (self.root / ".gitignore").write_text("data/\n")
        for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "init"]):
            subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t",
                            "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)

    def save_manifest(self):
        super().save_manifest()
        path = self.root / "dataset" / "manifest.yaml"
        manifest = yaml.safe_load(path.read_text())
        manifest["raw_files"]["fault_free_testing"] = {"faults": [0], "runs_per_fault": RUNS,
                                                       "samples_per_run": TEST_SAMPLES}
        manifest["raw_files"]["faulty_testing"] = {"faults": list(range(1, 21)), "runs_per_fault": RUNS,
                                                   "samples_per_run": TEST_SAMPLES}
        manifest["conversion"]["sealed_reports"] = getattr(self, "reports", {})
        path.write_text(yaml.safe_dump(manifest))

    def log(self):
        log = self.root / "eval" / "test_access.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def sealed_repo(tmp_path, monkeypatch):
    r = SealedRepo(tmp_path)
    monkeypatch.setattr(loader_mod, "REPO_ROOT", r.root)
    monkeypatch.setattr(loader_mod, "SEALED_ROOT", r.sealed)
    monkeypatch.setattr(loader_mod, "eval_mode", lambda environ=None: True)
    return r


@pytest.mark.parametrize("environ, on", [({"EVAL_MODE": "1"}, True), ({}, False), ({"EVAL_MODE": "0"}, False),
                                         ({"EVAL_MODE": "true"}, False), ({"EVAL_MODE": " 1"}, False)])
def test_eval_mode_is_exactly_one(environ, on):
    assert loader_mod.eval_mode(environ) is on


def test_eval_mode_is_off_in_every_test():
    assert loader_mod.eval_mode() is False


@pytest.mark.parametrize("fault, name", [(0, "fault_free_testing"), (1, "faulty_testing"), (16, "faulty_testing")])
def test_test_load_returns_all_500_runs_and_logs_it(sealed_repo, fault, name):
    runs = loader_mod.load_testing(fault, purpose="dev_table pca_static")
    assert (runs.name, runs.fault, runs.pool, runs.columns) == (name, fault, "test", VARIABLES)
    assert sorted(runs.runs) == list(range(1, RUNS + 1))
    for k, a in runs.runs.items():
        assert a.shape == (TEST_SAMPLES, len(VARIABLES)) and a.dtype == np.float32
        assert (a[:, 0] == k).all() and (a[:, 1] == np.arange(1, TEST_SAMPLES + 1)).all()
        assert (a[:, 2] == fault).all()
    [line] = sealed_repo.log()
    assert line["action"] == "load" and (line["file"], line["fault"]) == (name, fault)
    assert line["purpose"] == "dev_table pca_static" and line["dirty"] is False and len(line["commit"]) == 40


def test_each_load_adds_one_line_and_the_log_doesnt_dirty_the_tree(sealed_repo):
    # The second load runs after the first wrote the (uncommitted) log: still clean.
    loader_mod.load_testing(0, purpose="a")
    loader_mod.load_testing(1, purpose="b")
    assert [(x["fault"], x["purpose"], x["dirty"]) for x in sealed_repo.log()] == [(0, "a", False), (1, "b", False)]


def test_dirty_tree_refused_and_logged(sealed_repo):
    (sealed_repo.root / "dataset" / "splits.yaml").write_text("pools: {}\n")
    with pytest.raises(LoaderError, match="dirty"):
        loader_mod.load_testing(1, purpose="x")
    [line] = sealed_repo.log()
    assert line["dirty"] is True


def test_untracked_file_makes_the_tree_dirty(sealed_repo):
    (sealed_repo.root / "eval").mkdir(exist_ok=True)
    (sealed_repo.root / "eval" / "scratch.py").write_text("x = 1\n")
    with pytest.raises(LoaderError, match="dirty"):
        loader_mod.load_testing(1, purpose="x")


def test_no_git_refused(sealed_repo, monkeypatch):
    monkeypatch.setattr(loader_mod, "git_state", lambda root: (None, None))
    with pytest.raises(LoaderError, match="dirty"):
        loader_mod.load_testing(1, purpose="x")


def test_changed_test_file_refused_after_logging(sealed_repo):
    path = output_path(sealed_repo.converted, "faulty_testing", 1)
    pq.write_table(_table(1, samples=TEST_SAMPLES, seed=999), path)
    with pytest.raises(LoaderError, match="conversion report"):
        loader_mod.load_testing(1, purpose="x")
    assert len(sealed_repo.log()) == 1


def test_changed_report_refused(sealed_repo):
    report = sealed_repo.converted / "conversion_report_faulty_testing.json"
    doc = json.loads(report.read_text())
    doc["files"]["faulty_testing/fault_01.parquet"]["sha256"] = "0" * 64
    report.write_text(json.dumps(doc))
    with pytest.raises(LoaderError, match="SHA-256 in the manifest"):
        loader_mod.load_testing(1, purpose="x")


def test_missing_test_file_refused(sealed_repo):
    with pytest.raises(LoaderError, match="not found"):
        loader_mod.load_testing(2, purpose="x")


@pytest.mark.parametrize("fault", [16, 17, 20])
def test_training_file_faults_16_to_20_stay_refused_even_in_eval_mode(sealed_repo, fault):
    # S0 answer 5: the unknown-fault test uses the testing file only.
    with pytest.raises(LoaderError, match="sealed"):
        loader_mod.load_faulty(fault, "dev")
    assert sealed_repo.log() == []


@pytest.mark.parametrize("fault, purpose, match", [(21, "x", "faults 0-20"), (-1, "x", "faults 0-20"),
                                                   (True, "x", "must be an int"), ("1", "x", "must be an int"),
                                                   (1, "", "purpose"), (1, "  ", "purpose"), (1, None, "purpose")])
def test_bad_test_requests_refused_before_logging(sealed_repo, fault, purpose, match):
    with pytest.raises(LoaderError, match=match):
        loader_mod.load_testing(fault, purpose=purpose)
    assert sealed_repo.log() == []


def test_purpose_is_required():
    with pytest.raises(TypeError):
        loader_mod.load_testing(1)