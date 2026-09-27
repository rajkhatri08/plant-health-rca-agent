"""One-time conversion of the four raw RData files to Parquet.

Raj runs this; Claude Code never runs it (decision 33).

    python -m dataset.convert <name> [--crosscheck]

<name> is one of fault_free_training, fault_free_testing, faulty_training,
faulty_testing: one raw file per run, so memory is released between files.
Open data (fault_free_training, and faulty_training faults 1-15) goes to
<repo>/data. Everything else goes to the sealed folder outside the repo.
Prints only counts, checksums and versions, never values.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from dataset.rdata_stream import RDataError, read_frame

REPO_ROOT = Path(__file__).resolve().parents[1]
SEALED_ROOT = Path.home() / "PycharmProjects" / "plant-health-sealed"
DEFAULT_RAW_DIR = SEALED_ROOT / "raw"
DEFAULT_SEALED_DIR = SEALED_ROOT / "converted"

ID_COLUMNS = ("faultNumber", "simulationRun", "sample")
VARIABLES = tuple([f"xmeas_{i}" for i in range(1, 42)] + [f"xmv_{i}" for i in range(1, 12)])
COLUMNS = ID_COLUMNS + VARIABLES
NAMES = ("fault_free_training", "fault_free_testing", "faulty_training", "faulty_testing")
INT16 = np.iinfo(np.int16)

# The open-data rule, restated at the write call independently of route().
_OPEN_WRITES = frozenset([("fault_free_training", 0)]
                         + [("faulty_training", f) for f in range(1, 16)])


class ConversionError(RuntimeError):
    pass


def route(name, fault):
    """Where one fault's rows from one raw file go: "open" or "sealed"."""
    if name == "fault_free_training" and fault == 0:
        return "open"
    if name == "faulty_training" and 1 <= fault <= 15:
        return "open"
    return "sealed"


def output_path(side_dir, name, fault):
    if name.startswith("fault_free"):
        return side_dir / f"{name}.parquet"
    return side_dir / name / f"fault_{fault:02d}.parquet"


def report_path(side_dir, name):
    return side_dir / f"conversion_report_{name}.json"


def convert(name, *, repo_root, raw_dir, sealed_dir, crosscheck=False, chunk_values=1 << 20):
    repo_root, raw_dir, sealed_dir = Path(repo_root), Path(raw_dir), Path(sealed_dir)
    open_dir = repo_root / "data"
    spec = _load_spec(repo_root, name)
    commit, dirty = git_state(repo_root)

    # 0. Log the access before the raw file is opened, so failed runs are recorded too.
    _append_access_log(repo_root, spec["file"], commit, dirty)

    # 1. Guards.
    if sealed_dir.resolve().is_relative_to(repo_root.resolve()):
        raise ConversionError("the sealed output folder must be outside the repo")
    if crosscheck and name != "fault_free_training":
        raise ConversionError("--crosscheck is only for fault_free_training (memory)")
    side_dirs = {"open": open_dir, "sealed": sealed_dir}
    planned = [output_path(side_dirs[route(name, f)], name, f) for f in spec["faults"]]
    planned += [report_path(side_dirs[s], name) for s in {route(name, f) for f in spec["faults"]}]
    existing = [p for p in planned if p.exists()]
    if existing:
        raise ConversionError(f"{len(existing)} output file(s) already exist, e.g. {existing[0]}; "
                              "delete them to redo this conversion")

    # 2. Check the raw file.
    raw_path = raw_dir / spec["file"]
    if not raw_path.is_file():
        raise ConversionError(f"raw file not found: {raw_path}")
    print(f"{name}: checking MD5 of {spec['file']}")
    if file_hash(raw_path, "md5") != spec["md5"]:
        raise ConversionError(f"MD5 mismatch for {spec['file']}; nothing was parsed")
    print("  MD5 matches the manifest")

    n_expected = len(spec["faults"]) * spec["runs_per_fault"] * spec["samples_per_run"]
    print(f"  expected rows: {n_expected}; memory needed: about "
          f"{_gb(n_expected * len(COLUMNS) * 4)} GB of {_gb(_physical_ram())} GB RAM")

    # 3. Read, streamed, then check names and ids.
    try:
        frame = read_frame(raw_path, chunk_values=chunk_values)
    except RDataError as e:
        raise ConversionError(f"could not read {spec['file']}: {e}") from None
    if frame.name != name:
        raise ConversionError(f"the file holds an object named {frame.name!r}, expected {name!r}")
    missing = [c for c in COLUMNS if c not in frame.columns]
    extra = [c for c in frame.columns if c not in COLUMNS]
    if missing or extra:
        raise ConversionError(f"column mismatch: {len(missing)} missing {missing[:5]}, "
                              f"{len(extra)} unexpected {extra[:5]}")
    ids = {}
    for col in ID_COLUMNS:
        st = frame.stats[col]
        if st.nonfinite or not st.integral or st.min < INT16.min or st.max > INT16.max:
            raise ConversionError(f"id column {col} is not whole numbers within int16 range")
        ids[col] = frame.columns.pop(col).astype(np.int16)
    nonfinite = {c: frame.stats[c].nonfinite for c in VARIABLES}
    bad = {c: n for c, n in nonfinite.items() if n}
    print(f"  rows read: {frame.nrows}; non-finite values: "
          + (", ".join(f"{c}={n}" for c, n in bad.items()) if bad else "none in all 52 variables"))

    # 4. Validate faults, runs and samples before anything is written.
    segments = _validate(ids, spec, frame.nrows)

    if crosscheck:
        _crosscheck(raw_path, name, frame, ids)

    # 5. Route and write, one fault at a time.
    versions = library_versions()
    sides = {}
    for fault, idx in segments:
        side = route(name, fault)
        table = pa.table({**{c: ids[c][idx] for c in ID_COLUMNS},
                          **{c: frame.columns[c][idx] for c in VARIABLES}})
        path = output_path(side_dirs[side], name, fault)
        if side == "open":
            _write_open(table, name, fault, path, repo_root)
        else:
            _write_sealed(table, path, sealed_dir, repo_root)
        entry = sides.setdefault(side, {"faults": {}, "files": {}, "nonfinite": dict.fromkeys(VARIABLES, 0)})
        entry["faults"][fault] = {"runs": spec["runs_per_fault"],
                                  "samples_per_run": spec["samples_per_run"], "rows": table.num_rows}
        entry["files"][str(path.relative_to(side_dirs[side]))] = {
            "rows": table.num_rows, "sha256": file_hash(path, "sha256")}
        for c in VARIABLES:
            entry["nonfinite"][c] += int(np.count_nonzero(~np.isfinite(frame.columns[c][idx])))
        print(f"  fault {fault}: {spec['runs_per_fault']} runs x {spec['samples_per_run']} samples "
              f"= {table.num_rows} rows -> {side}")
        del table

    # 6. Reports, one per side.
    snippet = {"library_versions": versions, "open_reports": {}, "sealed_reports": {}}
    for side, entry in sides.items():
        report = {
            "name": name, "side": side, "raw_file": spec["file"], "raw_md5": "matches manifest",
            "time": _now(), "commit": commit, "dirty": dirty, "versions": versions,
            "rows": sum(f["rows"] for f in entry["faults"].values()),
            "faults": entry["faults"], "nonfinite": entry["nonfinite"], "files": entry["files"],
        }
        path = report_path(side_dirs[side], name)
        path.write_text(json.dumps(report, indent=2) + "\n")
        if side == "open":
            snippet["open_reports"][name] = {"commit": commit, "dirty": dirty, "files": entry["files"]}
        else:
            snippet["sealed_reports"][name] = file_hash(path, "sha256")
        print(f"  {side} report: {path}")
    for side, entry in sides.items():
        for rel, f in entry["files"].items():
            print(f"  {side} {rel}: {f['rows']} rows, sha256 {f['sha256']}")
    print("\nFor dataset/manifest.yaml (conversion section):")
    print(yaml.safe_dump(snippet, sort_keys=False))
    return snippet


def _validate(ids, spec, nrows):
    """Assert the fault set, runs per fault and samples per run. Returns, per fault,
    the row indices sorted by (run, sample)."""
    fault, run, sample = (ids[c] for c in ID_COLUMNS)
    order = np.lexsort((sample, run, fault))
    fault_sorted = fault[order]
    present = [int(f) for f in np.unique(fault_sorted)]
    if present != sorted(spec["faults"]):
        raise ConversionError(f"fault numbers found {present}, expected {sorted(spec['faults'])}")
    n_runs, n_samples = spec["runs_per_fault"], spec["samples_per_run"]
    if nrows != len(present) * n_runs * n_samples:
        raise ConversionError(f"{nrows} rows, expected {len(present) * n_runs * n_samples}")
    expected_samples = np.arange(1, n_samples + 1)
    segments = []
    for f in present:
        lo, hi = np.searchsorted(fault_sorted, [f, f + 1])
        idx = order[lo:hi]
        found_runs = len(np.unique(run[idx]))
        if found_runs != n_runs:
            raise ConversionError(f"fault {f}: {found_runs} runs, expected {n_runs}")
        if idx.size != n_runs * n_samples:
            raise ConversionError(f"fault {f}: {idx.size} rows, expected {n_runs * n_samples}")
        r = run[idx].reshape(n_runs, n_samples)
        s = sample[idx].reshape(n_runs, n_samples)
        if not (r == r[:, :1]).all() or not (s == expected_samples).all():
            raise ConversionError(f"fault {f}: runs do not each have samples 1..{n_samples}")
        segments.append((f, idx))
    return segments


def _crosscheck(raw_path, name, frame, ids):
    import pyreadr

    ref = pyreadr.read_r(str(raw_path))[name]
    differing = sum(
        not np.array_equal(ids[c], ref[c].to_numpy(dtype=np.float64).astype(np.int16))
        for c in ID_COLUMNS
    ) + sum(
        not np.array_equal(frame.columns[c], ref[c].to_numpy(dtype=np.float64).astype(np.float32),
                           equal_nan=True)
        for c in VARIABLES
    )
    del ref
    print(f"  crosscheck against pyreadr: identical: {'yes' if differing == 0 else 'no'} "
          f"({len(COLUMNS)} columns compared, {differing} differ)")
    if differing:
        raise ConversionError("crosscheck failed; nothing was written")


def _write_open(table, name, fault, path, repo_root):
    if (name, fault) not in _OPEN_WRITES:
        raise ConversionError(f"refusing to write {name} fault {fault} to open data")
    if not path.resolve().is_relative_to((Path(repo_root) / "data").resolve()):
        raise ConversionError("refusing an open write outside <repo>/data")
    _write(table, path)


def _write_sealed(table, path, sealed_dir, repo_root):
    target = path.resolve()
    if not target.is_relative_to(Path(sealed_dir).resolve()) or target.is_relative_to(
            Path(repo_root).resolve()):
        raise ConversionError("refusing a sealed write outside the sealed folder")
    _write(table, path)


def _write(table, path):
    if path.exists():
        raise ConversionError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _load_spec(repo_root, name):
    if name not in NAMES:
        raise ConversionError(f"unknown raw file name {name!r}")
    manifest = yaml.safe_load((repo_root / "dataset" / "manifest.yaml").read_text())
    return manifest["raw_files"][name]


def git_state(repo_root):
    """(commit, dirty). Dirty looks only at dataset/*.py and requirements.txt, so the
    access log and manifest edits between runs don't count. None if git fails."""
    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True,
                                  text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--", "dataset/*.py", "requirements.txt")
    return (commit.strip() if commit else None), (None if status is None else bool(status.strip()))


def _append_access_log(repo_root, raw_file, commit, dirty):
    log = repo_root / "eval" / "test_access.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    line = {"time": _now(), "action": "convert", "raw_file": raw_file,
            "commit": commit, "dirty": dirty}
    with log.open("a") as f:
        f.write(json.dumps(line) + "\n")


def library_versions():
    versions = {"python": platform.python_version()}
    for pkg, dist in [("pyreadr", "pyreadr"), ("pandas", "pandas"), ("pyarrow", "pyarrow"),
                      ("numpy", "numpy"), ("pyyaml", "PyYAML")]:
        versions[pkg] = metadata.version(dist)
    return versions


def file_hash(path, algo):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _physical_ram():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        return 0


def _gb(n_bytes):
    return round(n_bytes / 1e9, 1)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", choices=NAMES)
    parser.add_argument("--crosscheck", action="store_true",
                        help="also load with pyreadr and compare (fault_free_training only)")
    args = parser.parse_args(argv)
    try:
        convert(args.name, repo_root=REPO_ROOT, raw_dir=DEFAULT_RAW_DIR,
                sealed_dir=DEFAULT_SEALED_DIR, crosscheck=args.crosscheck)
    except (ConversionError, OSError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())