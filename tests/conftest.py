import hashlib

import numpy as np
import pytest
import yaml

import dataset.convert as convert_mod
from tests.rdata_writer import write_rdata


@pytest.fixture(autouse=True)
def _no_real_paths(tmp_path, monkeypatch):
    """Point the converter's defaults at paths that don't exist, so no test (and no
    pytest run by Claude Code) can reach the real repo data/, eval/ or sealed folder."""
    nowhere = tmp_path / "does-not-exist"
    monkeypatch.setattr(convert_mod, "REPO_ROOT", nowhere / "repo")
    monkeypatch.setattr(convert_mod, "SEALED_ROOT", nowhere / "sealed")
    monkeypatch.setattr(convert_mod, "DEFAULT_RAW_DIR", nowhere / "sealed" / "raw")
    monkeypatch.setattr(convert_mod, "DEFAULT_SEALED_DIR", nowhere / "sealed" / "converted")


FAULTY = [1, 2, 16]
SAMPLES = {"fault_free_training": 3, "fault_free_testing": 4,
           "faulty_training": 3, "faulty_testing": 4}
RUNS = 2


def make_columns(name, *, runs=RUNS, samples=None, faults=None, seed=0, shuffle=True):
    """A small frame with the real column names, rows in shuffled order."""
    samples = samples or SAMPLES[name]
    faults = faults if faults is not None else ([0] if name.startswith("fault_free") else FAULTY)
    f, r, s = np.meshgrid(faults, np.arange(1, runs + 1), np.arange(1, samples + 1), indexing="ij")
    cols = {"faultNumber": f.ravel().astype(float), "simulationRun": r.ravel().astype(float),
            "sample": s.ravel().astype(float)}
    rng = np.random.default_rng(seed)
    for c in convert_mod.VARIABLES:
        cols[c] = rng.normal(50.0, 10.0, f.size)
    if shuffle:
        perm = rng.permutation(f.size)
        cols = {k: v[perm] for k, v in cols.items()}
    return cols


class FakeRepo:
    def __init__(self, root):
        self.root = root / "repo"
        self.raw = root / "sealed" / "raw"
        self.sealed = root / "sealed" / "converted"
        (self.root / "dataset").mkdir(parents=True)
        self.raw.mkdir(parents=True)
        self.manifest = {"raw_files": {
            name: {"file": f"{name}.RData", "md5": "0" * 32,
                   "faults": [0] if name.startswith("fault_free") else FAULTY,
                   "runs_per_fault": RUNS, "samples_per_run": SAMPLES[name]}
            for name in convert_mod.NAMES}}
        self.save_manifest()

    def save_manifest(self):
        (self.root / "dataset" / "manifest.yaml").write_text(yaml.safe_dump(self.manifest))

    def add_raw(self, name, columns=None, *, object_name=None, **writer_kwargs):
        columns = columns if columns is not None else make_columns(name)
        path = write_rdata(self.raw / f"{name}.RData", object_name or name, columns, **writer_kwargs)
        self.manifest["raw_files"][name]["md5"] = hashlib.md5(path.read_bytes()).hexdigest()
        self.save_manifest()
        return path

    def convert(self, name, **kwargs):
        return convert_mod.convert(name, repo_root=self.root, raw_dir=self.raw,
                                   sealed_dir=self.sealed, chunk_values=5, **kwargs)

    def log_lines(self):
        log = self.root / "eval" / "test_access.log"
        return log.read_text().splitlines() if log.exists() else []


@pytest.fixture
def fake_repo(tmp_path):
    return FakeRepo(tmp_path)
