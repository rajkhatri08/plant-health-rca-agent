"""Loads open training runs by run-number pool (decision 49), and the sealed test split
for a pre-registered run (LEAKAGE wall 3; week 7).

Builder side: columns keep their raw names.
- load_normal / load_faulty: only the open files under <repo>/data. Faults 16-20 of the
  training file are refused always (S0 answer 5: the unknown-fault test uses the testing
  file only).
- load_testing(fault, purpose=...): the testing file's runs, from the sealed folder. Only
  when EVAL_MODE is "1" (Raj sets it for a pre-registered run) and the tree is clean. Every
  attempt that gets past the mode check appends one line to eval/test_access.log before
  the file is opened, so a refused or failed load is logged too. The file must match the
  SHA-256 in its sealed conversion report, and the report the SHA-256 in the manifest.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import yaml

from dataset import splits
from dataset.convert import (ID_COLUMNS, REPO_ROOT, SEALED_ROOT, VARIABLES, file_hash, output_path,
                             report_path)

NORMAL_POOLS = tuple(splits.POOL_SIZES)
FAULTY_POOLS = ("dev", "authoring", "forest_ceiling")
OPEN_FAULTS = range(1, 16)
QUARANTINED_FAULTS = range(16, 21)
TEST_FAULTS = range(0, 21)          # 0 is the normal testing file; 1-20 the faulty testing file
SEALED_MESSAGE = ("is sealed: faults 16-20 load only from the testing file, through "
                  "load_testing under EVAL_MODE")
ACCESS_LOG = Path("eval") / "test_access.log"
RUNS_DIR = Path("eval") / "runs"


class LoaderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Runs:
    name: str
    fault: int
    pool: str
    columns: tuple
    runs: dict  # run number -> float32 array, samples x len(columns)


def load_normal(pool):
    if pool not in NORMAL_POOLS:
        raise LoaderError(f"unknown normal pool {pool!r}; one of {NORMAL_POOLS}")
    return _load("fault_free_training", 0, pool, _assignment()["pools"][pool])


def load_faulty(fault, pool):
    if isinstance(fault, bool) or not isinstance(fault, int):
        raise LoaderError(f"fault must be an int, got {fault!r}")
    if fault in QUARANTINED_FAULTS:
        raise LoaderError(f"fault {fault} {SEALED_MESSAGE}")
    if fault not in OPEN_FAULTS:
        raise LoaderError(f"fault {fault} isn't an open fault (1-15); normal runs use load_normal")
    if pool not in FAULTY_POOLS:
        raise LoaderError(f"faulty runs come only from {FAULTY_POOLS}, not {pool!r} (decision 49)")
    data = _assignment()
    numbers = data["pools"]["dev"] if pool == "dev" else data[pool]
    return _load("faulty_training", fault, pool, numbers)


def eval_mode(environ=None):
    """True only when EVAL_MODE is exactly "1". Raj sets it for a pre-registered run; tests
    never set it (they pass a dict here, or replace this function)."""
    environ = os.environ if environ is None else environ
    return environ.get("EVAL_MODE") == "1"


def load_testing(fault, *, purpose):
    """All 500 runs of one testing-file fault (0 = normal), pool "test". See the module
    docstring for the guards; purpose (for example "dev_table pca_static") goes in the
    access log."""
    if isinstance(fault, bool) or not isinstance(fault, int):
        raise LoaderError(f"fault must be an int, got {fault!r}")
    if fault not in TEST_FAULTS:
        raise LoaderError(f"the testing files hold faults 0-20, not {fault}")
    if not isinstance(purpose, str) or not purpose.strip():
        raise LoaderError("a test load needs a purpose, written to the access log")
    if not eval_mode():
        raise LoaderError("the test split is sealed: it loads only with EVAL_MODE=1, which Raj "
                          "sets for a pre-registered run")
    name = "fault_free_testing" if fault == 0 else "faulty_testing"
    commit, dirty = git_state(REPO_ROOT)
    _append_access_log(name, fault, purpose, commit, dirty)          # before any check or open
    if commit is None or dirty:
        raise LoaderError("refusing a test load on a dirty tree (or with no git state); commit first")

    sealed_dir = SEALED_ROOT / "converted"
    path = output_path(sealed_dir, name, fault)
    if not path.resolve().is_relative_to(sealed_dir.resolve()):
        raise LoaderError(f"refusing a test path outside the sealed folder: {path}")
    if not path.is_file():
        raise LoaderError(f"sealed data file not found: {path}")
    manifest = yaml.safe_load((REPO_ROOT / "dataset" / "manifest.yaml").read_text())
    report = report_path(sealed_dir, name)
    try:
        expected_report = manifest["conversion"]["sealed_reports"][name]
    except (KeyError, TypeError):
        raise LoaderError(f"no checksum for the {name} report in dataset/manifest.yaml") from None
    if not report.is_file() or file_hash(report, "sha256") != expected_report:
        raise LoaderError(f"the {name} conversion report doesn't match its SHA-256 in the manifest")
    rel = str(path.relative_to(sealed_dir))
    try:
        expected_sha = json.loads(report.read_text())["files"][rel]["sha256"]
    except (KeyError, TypeError, ValueError):
        raise LoaderError(f"no checksum for {rel} in the {name} conversion report") from None
    if file_hash(path, "sha256") != expected_sha:
        raise LoaderError(f"{rel} doesn't match its SHA-256 in the conversion report")

    spec = manifest["raw_files"][name]
    values = _read(path, rel, fault, spec["runs_per_fault"], spec["samples_per_run"])
    return Runs(name=name, fault=fault, pool="test", columns=VARIABLES,
                runs={k: values[k - 1] for k in range(1, spec["runs_per_fault"] + 1)})


def git_state(repo_root):
    """(commit, dirty), the same rule as eval/run_record.py: every tracked or untracked change
    counts except eval/runs/ and the access log. (None, None) if git fails. Kept here because
    dataset/ imports nothing from eval/."""
    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True,
                                  text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--", ".", f":(exclude){RUNS_DIR.as_posix()}",
                 f":(exclude){ACCESS_LOG.as_posix()}")
    if commit is None or status is None:
        return None, None
    return commit.strip(), bool(status.strip())


def _append_access_log(name, fault, purpose, commit, dirty):
    log = REPO_ROOT / ACCESS_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    line = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "action": "load",
            "file": name, "fault": fault, "purpose": purpose, "commit": commit, "dirty": dirty}
    with log.open("a") as f:
        f.write(json.dumps(line) + "\n")


def check_path(path):
    """The resolved path (symlinks followed) must be under <repo>/data and not under the
    sealed folder."""
    target = Path(path).resolve()
    if target.is_relative_to(SEALED_ROOT.resolve()):
        raise LoaderError(f"refusing a path in the sealed folder: {path}")
    if not target.is_relative_to((REPO_ROOT / "data").resolve()):
        raise LoaderError(f"refusing a path outside <repo>/data: {path}")
    return target


def _assignment():
    try:
        return splits.load(REPO_ROOT)
    except (splits.SplitsError, OSError) as e:
        raise LoaderError(f"run-number pools unavailable: {e}") from None


def _load(name, fault, pool, numbers):
    data_dir = REPO_ROOT / "data"
    path = output_path(data_dir, name, fault)
    check_path(path)
    if not path.is_file():
        raise LoaderError(f"open data file not found: {path}")

    manifest = yaml.safe_load((REPO_ROOT / "dataset" / "manifest.yaml").read_text())
    spec = manifest["raw_files"][name]
    rel = str(path.relative_to(data_dir))
    try:
        expected_sha = manifest["conversion"]["open_reports"][name]["files"][rel]["sha256"]
    except (KeyError, TypeError):
        raise LoaderError(f"no checksum for {rel} in dataset/manifest.yaml") from None
    if file_hash(path, "sha256") != expected_sha:
        raise LoaderError(f"{rel} doesn't match its SHA-256 in the manifest")

    n_runs, n_samples = spec["runs_per_fault"], spec["samples_per_run"]
    if n_runs != splits.N_RUNS:
        raise LoaderError(f"{name} has {n_runs} runs per fault; the pools cover {splits.N_RUNS}")
    values = _read(path, rel, fault, n_runs, n_samples)
    return Runs(name=name, fault=fault, pool=pool, columns=VARIABLES,
                runs={int(k): values[k - 1] for k in numbers})


def _read(path, rel, fault, n_runs, n_samples):
    """The file's values as runs x samples x VARIABLES (float32), after checking it holds
    exactly runs 1..n_runs, each with samples 1..n_samples, all of this fault."""
    table = pq.read_table(path, columns=list(ID_COLUMNS + VARIABLES))
    f, run, sample = (table[c].to_numpy().astype(np.int64) for c in ID_COLUMNS)
    if table.num_rows != n_runs * n_samples or not (f == fault).all():
        raise LoaderError(f"{rel}: expected {n_runs * n_samples} rows, all fault {fault}")
    order = np.lexsort((sample, run))
    r = run[order].reshape(n_runs, n_samples)
    s = sample[order].reshape(n_runs, n_samples)
    if not (r == np.arange(1, n_runs + 1)[:, None]).all() or not (s == np.arange(1, n_samples + 1)).all():
        raise LoaderError(f"{rel}: runs aren't 1..{n_runs}, each with samples 1..{n_samples}")

    values = np.column_stack([table[c].to_numpy() for c in VARIABLES]).astype(np.float32, copy=False)
    return values[order].reshape(n_runs, n_samples, len(VARIABLES))
