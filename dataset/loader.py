"""Loads open training runs by run-number pool (decision 49).

Builder side: columns keep their raw names. Only the open files under <repo>/data can
be loaded. The test split and faults 16-20 are always refused in week 1; loading them
under EVAL_MODE, with an access-log line, is built in week 7.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import yaml

from dataset import splits
from dataset.convert import ID_COLUMNS, REPO_ROOT, SEALED_ROOT, VARIABLES, file_hash, output_path

NORMAL_POOLS = tuple(splits.POOL_SIZES)
FAULTY_POOLS = ("dev", "authoring", "forest_ceiling")
OPEN_FAULTS = range(1, 16)
QUARANTINED_FAULTS = range(16, 21)
SEALED_MESSAGE = ("is sealed: loading it under EVAL_MODE is built in week 7, "
                  "and this loader refuses it whatever EVAL_MODE says")


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


def load_testing(*args, **kwargs):
    raise LoaderError(f"the test split {SEALED_MESSAGE}")


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
    values = values[order].reshape(n_runs, n_samples, len(VARIABLES))
    return Runs(name=name, fault=fault, pool=pool, columns=VARIABLES,
                runs={int(k): values[k - 1] for k in numbers})
