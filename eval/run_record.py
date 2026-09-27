"""Run records: every reported number comes from one (CLAUDE.md; PROTOCOL, Reporting).

A record is one JSON file, eval/runs/<UTC stamp>_<name>.json, committed with the code.
It holds the commit, whether the tree was dirty, the config, the seeds, the SHA-256 of
the data manifest and the splits file, library versions, the SHA-256 of each file the
run wrote, and the metrics.

Rules:
- A dirty tree (or no git) is refused unless allow_dirty is passed; the record then says
  dirty: true, so a number from it can't pass as clean. eval/runs/ itself doesn't count.
- Metrics are numbers, strings, booleans or short lists of numbers (at most MAX_LIST).
  No arrays of data values. ±inf is written as the string "inf" / "-inf" (a delay median
  can be +inf); NaN is refused.
- A record is never overwritten.
"""

import hashlib
import json
import math
import platform
import re
import subprocess
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = Path("eval") / "runs"
MAX_LIST = 64
_NAME = re.compile(r"^[a-z0-9][a-z0-9_]*$")


class RunRecordError(RuntimeError):
    pass


def git_state(repo_root):
    """(commit, dirty). Dirty counts every tracked or untracked change except eval/runs/.
    (None, None) if git fails."""
    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True,
                                  text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--", ".", f":(exclude){RUNS_DIR.as_posix()}")
    if commit is None or status is None:
        return None, None
    return commit.strip(), bool(status.strip())


def check_clean(repo_root=None, allow_dirty=False):
    """Refuse a dirty tree or a missing git state unless allow_dirty. Returns (commit, dirty).
    Call it before the work, so a refused run costs nothing."""
    repo_root = Path(repo_root or REPO_ROOT)
    commit, dirty = git_state(repo_root)
    if (commit is None or dirty) and not allow_dirty:
        raise RunRecordError("the working tree is dirty (or git state is unknown); commit first, "
                             "or pass --allow-dirty and the record will say dirty: true")
    return commit, (True if commit is None else dirty)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _scalar(key, v):
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if math.isnan(v):
            raise RunRecordError(f"metric {key} is NaN")
        return v if math.isfinite(v) else ("inf" if v > 0 else "-inf")
    if isinstance(v, str) or v is None:
        return v
    raise RunRecordError(f"metric {key} has type {type(v).__name__}; records hold numbers only")


def clean_metrics(metrics, prefix=""):
    """Metrics as JSON-ready values, refusing anything that could carry data values.
    Nested dicts are allowed; errors name the full key (e.g. limits.t2)."""
    out = {}
    for k, v in metrics.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out[k] = clean_metrics(v, prefix=f"{key}.")
        elif isinstance(v, (list, tuple, np.ndarray)):
            if np.ndim(v) != 1 or len(v) > MAX_LIST:
                raise RunRecordError(f"metric {key}: lists must be flat with at most {MAX_LIST} "
                                     "numbers; records never hold data values")
            out[k] = [_scalar(key, x) for x in v]
        else:
            out[k] = _scalar(key, v)
    return out


def library_versions():
    return {"python": platform.python_version(), "numpy": metadata.version("numpy")}


def write(name, *, config, seeds, metrics, outputs, commit, dirty, repo_root=None, now=None):
    """Write eval/runs/<stamp>_<name>.json and return its path.

    outputs maps a label to a file the run wrote; each is recorded by path (relative to
    the repo when inside it) and SHA-256. commit and dirty come from check_clean()."""
    if not _NAME.match(name):
        raise RunRecordError(f"record name must match {_NAME.pattern}, got {name!r}")
    repo_root = Path(repo_root or REPO_ROOT)
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    def rel(p):
        p = Path(p).resolve()
        return p.relative_to(repo_root.resolve()).as_posix() if p.is_relative_to(repo_root.resolve()) else str(p)

    manifest = repo_root / "dataset" / "manifest.yaml"
    splits = repo_root / "dataset" / "splits.yaml"
    for p in (manifest, splits):
        if not p.is_file():
            raise RunRecordError(f"{rel(p)} not found; a record needs its checksum")
    record = {
        "name": name,
        "time": now.isoformat(timespec="seconds"),
        "commit": commit,
        "dirty": dirty,
        "config": clean_metrics(config),
        "seeds": clean_metrics(seeds),
        "data": {"manifest_sha256": sha256(manifest), "splits_sha256": sha256(splits)},
        "library_versions": library_versions(),
        "outputs": {label: {"path": rel(p), "sha256": sha256(p)} for label, p in outputs.items()},
        "metrics": clean_metrics(metrics),
    }
    path = repo_root / RUNS_DIR / f"{stamp}_{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x") as f:                        # "x": never overwrite a record
            json.dump(record, f, indent=2, allow_nan=False)
            f.write("\n")
    except FileExistsError:
        raise RunRecordError(f"{rel(path)} already exists") from None
    return path