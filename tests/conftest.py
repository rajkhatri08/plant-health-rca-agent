import hashlib
import subprocess

import numpy as np
import pytest
import yaml

import dataset.convert as convert_mod
import dataset.loader as loader_mod
import eval.run_record as run_record_mod
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
    # Same for the loader (it copies these at import). Tests that need open data opt in.
    monkeypatch.setattr(loader_mod, "REPO_ROOT", nowhere / "repo")
    monkeypatch.setattr(loader_mod, "SEALED_ROOT", nowhere / "sealed")
    # Run records: never the real eval/runs/. Tests that need a record use a git_repo.
    monkeypatch.setattr(run_record_mod, "REPO_ROOT", nowhere / "repo")
    # No test ever runs with EVAL_MODE set.
    monkeypatch.delenv("EVAL_MODE", raising=False)


class NetworkBlocked(RuntimeError):
    """A test tried to reach the network, or to read .env (week 6 S3 guard). Not an
    OSError, so no retry logic mistakes it for a transient failure."""


_LOCAL_HOSTS = {None, "localhost", "127.0.0.1", "::1", b"localhost"}


def _is_local(address):
    if isinstance(address, (str, bytes)):                  # an AF_UNIX path
        return True
    host = address[0]
    return host in _LOCAL_HOSTS or str(host).startswith("127.")


@pytest.fixture(autouse=True)
def _no_network_no_key(monkeypatch):
    """No test sees GEMINI_API_KEY, reads .env, or reaches anything but loopback, so no test
    (and no CI run) can call the model or spend money. tests/test_guard.py proves each."""
    import socket

    import dotenv

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo, real_create = socket.getaddrinfo, socket.create_connection

    def connect(self, address):
        if not _is_local(address):
            raise NetworkBlocked(f"a test tried to connect to {address!r}")
        return real_connect(self, address)

    def connect_ex(self, address):
        if not _is_local(address):
            raise NetworkBlocked(f"a test tried to connect to {address!r}")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host not in _LOCAL_HOSTS and not str(host).startswith("127."):
            raise NetworkBlocked(f"a test tried to resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    def create_connection(address, *args, **kwargs):
        if not _is_local(address):
            raise NetworkBlocked(f"a test tried to connect to {address!r}")
        return real_create(address, *args, **kwargs)

    def load_dotenv(*args, **kwargs):
        raise NetworkBlocked("a test tried to read .env")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(dotenv, "load_dotenv", load_dotenv)


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


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=test", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    """A committed, clean git repo with a data manifest and splits file (for run records)."""
    root = tmp_path / "gitrepo"
    (root / "dataset").mkdir(parents=True)
    (root / "dataset" / "manifest.yaml").write_text("dataset: {doi: fake}\n")
    (root / "dataset" / "splits.yaml").write_text("pools: {}\n")
    (root / "code.py").write_text("x = 1\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """Tests commit in throwaway repos. Give those commits a name and email, so the suite
    doesn't depend on this machine's git identity (GitHub's runner has none)."""
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "t@t")
