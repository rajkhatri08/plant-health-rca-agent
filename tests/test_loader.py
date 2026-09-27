"""The loader (decision 49): runs by pool, one assignment for every file, sealed data refused.

Runs on a synthetic open-data repo under tmp_path. Values encode where they came from:
column 0 = run number, column 1 = sample, column 2 = fault.
"""

import hashlib
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


@pytest.mark.parametrize("args", [(), ("fault_free_testing",), ("faulty_testing", 1)])
def test_test_split_refused(repo, args):
    with pytest.raises(LoaderError, match="sealed"):
        loader_mod.load_testing(*args)


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