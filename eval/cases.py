"""Diagnosis cases: App 3's scoring path on faulty training runs, by fault and pool
(decisions 49, 68, 70). Builder side: it reads labels and run numbers.

    python -m eval.cases <pool> [--faults 1 2 4 ...] [--model data/models/pca_static.npz]
                         [--limits data/models/pca_static_limits.json]
                         [--watch data/models/pca_static_watch.json]
                         [--normals data/models/evidence_normals.json] [--allow-dirty]

pool is one of POOLS (authoring, dev, forest_ceiling); faults are the known faults
(KNOWN_FAULTS, PROTOCOL "Cases"), all 12 by default. Per run it scores App 3 exactly as
evaluation does, and exactly as eval/authoring.py did before S3 (it now calls this):
- the alert track (calibrate_driver.score_runs and tracks) and the first notification in
  the detection window (metrics.detection)
- group and tag RBC over the Watch boundaries (calibrate_watch.rbc_runs)
- the features at the notification (location), +30 min (provisional) and +60 min
  (revised), through app/detector/features.py, the code the agent's tools will use

Analyzers are stored as held series. Their published values are recovered here: the
samples where the held value changes must all fall on one schedule, every update interval
(library/tags.yaml), and the publications are every sample on that schedule. If a change
falls off the schedule, the run is refused rather than guessed at.

Writes data/cases/<stamp>_<pool>/fault_NN.json (gitignored: it holds labels and run
numbers) and a cases run record holding each file's SHA-256. Readers find cases through the
record. Prints only counts and paths. Refuses a dirty tree unless --allow-dirty (checked
before any loading), and never overwrites.

score_normal gives decision 70's false-alert cases on normal runs: every notification
after the warm-up, with its features. The dev diagnosis table (eval/diag_table.py) uses it;
the command line here builds faulty runs only.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.detector import features
from dataset import loader
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import dev_table, evidence_normals, metrics, run_record
from ingest import tags as tagmap

KNOWN_FAULTS = (1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14)     # PROTOCOL, Diagnosis: Cases
POOLS = ("authoring", "dev", "forest_ceiling")
ONSET = metrics.TRAIN_ONSET
SAMPLE_MIN = metrics.SAMPLE_MIN
DEFAULT_DIR = run_record.REPO_ROOT / "data" / "cases"


class CasesError(RuntimeError):
    pass


@dataclass(frozen=True)
class Inputs:
    """Everything the scoring path needs, loaded once and checked against its records."""
    model: object
    lim: dict
    bands: dict
    plant: object
    names: list                 # group names, in the Watch file's order
    w_group: np.ndarray
    w_tag: np.ndarray
    interval: dict              # analyzer tag -> update interval in samples
    records: dict               # calibration, watch and normals record paths, repo-relative
    limits_sha256: str


def load_inputs(model_path, limits_path, watch_path, normals_path, repo_root) -> Inputs:
    repo_root = Path(repo_root)
    cal_record, lim, model = cw.load_pair(limits_path, model_path, repo_root)
    watch_record, watch = cw.load_watch(watch_path, limits_path, model, repo_root)
    normals_record, bands = evidence_normals.load_normals(normals_path, repo_root)
    names = list(watch["groups"])
    return Inputs(
        model=model, lim=lim, bands=bands, plant=features.plant_from_files(model.tags), names=names,
        w_group=np.array([watch["groups"][g]["w"] for g in names]),
        w_tag=np.array([watch["tags"][t] for t in model.tags]),
        interval={r["tag"]: r["update_interval_min"] // SAMPLE_MIN for r in tagmap.register()
                  if r["kind"] == "analyzer"},
        records={"calibration_record": cal_record.relative_to(repo_root).as_posix(),
                 "watch_record": watch_record.relative_to(repo_root).as_posix(),
                 "normals_record": normals_record.relative_to(repo_root).as_posix()},
        limits_sha256=run_record.sha256(limits_path))


def publications_from_held(series, interval):
    """[(sample, value), ...] from a held analyzer series (1-based samples). The changes
    must all fall on one schedule s = phase (mod interval); the publications are every
    sample on it. Raises CasesError if a change is off the schedule, or if there's none
    to set the phase."""
    x = np.asarray(series, dtype=np.float64)
    changes = [i + 1 for i in range(1, len(x)) if x[i] != x[i - 1]]
    if not changes:
        raise CasesError("a held analyzer series never changes; its schedule can't be found")
    phase = changes[0] % interval
    off = [s for s in changes if s % interval != phase]
    if off:
        raise CasesError(f"held values change off the {interval}-sample schedule at samples {off[:5]}")
    return [(s, float(x[s - 1])) for s in range(1, len(x) + 1) if s % interval == phase]


def _prepare(inp: Inputs, runs):
    """The alert tracks, group and tag RBC and column indices for a set of runs."""
    model, lim = inp.model, inp.lim
    scored = drv.score_runs(model, runs)
    tracks = drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], lim["warmup"])
    by_group, by_tag = cw.rbc_runs(model, lim, runs, inp.names)
    fast_cols = tagmap.column_indices(runs.columns, model.tags)
    an_cols = dict(zip(inp.plant.analyzers, tagmap.column_indices(runs.columns, inp.plant.analyzers)))
    return tracks, by_group, by_tag, fast_cols, an_cols


def _features_at(inp: Inputs, x, t, k, by_group, by_tag, fast_cols, an_cols):
    pubs = {tag: publications_from_held(x[:, c], inp.interval[tag]) for tag, c in an_cols.items()}
    return features.extract(inp.plant, x[:, fast_cols], pubs, inp.bands, t, inp.lim["n"],
                            by_group[k] / inp.w_group, by_tag[k] / inp.w_tag, inp.names)


def score_pool(inp: Inputs, runs) -> list:
    """Per run, by run number: {run, detected, notification_sample, delay_min} and, when
    detected, the features at the first notification after onset."""
    tracks, by_group, by_tag, fast_cols, an_cols = _prepare(inp, runs)
    per_run = []
    for k in sorted(runs.runs):
        det = metrics.detection(tracks[k], ONSET, warmup=inp.lim["warmup"])
        row = {"run": int(k), "detected": bool(det.detected),
               "notification_sample": int(det.sample) if det.detected else None,
               "delay_min": float(det.delay_min) if det.detected else None}
        if det.detected:
            row["features"] = _features_at(inp, runs.runs[k], det.sample, k, by_group, by_tag, fast_cols, an_cols)
        per_run.append(row)
    return per_run


def score_normal(inp: Inputs, runs) -> list:
    """Decision 70's false-alert cases. Per normal run, by run number: {run, notifications:
    [{sample, features}, ...]} for every notification after the warm-up (a normal run has no
    onset, so every one is a false alert), each with its features as at a real alert."""
    tracks, by_group, by_tag, fast_cols, an_cols = _prepare(inp, runs)
    out = []
    for k in sorted(runs.runs):
        notes = metrics.notifications(tracks[k], inp.lim["warmup"])
        out.append({"run": int(k), "notifications": [
            {"sample": int(t), "features": _features_at(inp, runs.runs[k], t, k, by_group, by_tag, fast_cols, an_cols)}
            for t in notes]})
    return out


def check_request(pool, faults):
    if pool not in POOLS:
        raise CasesError(f"pool must be one of {POOLS}, got {pool!r}")
    faults = tuple(faults)
    if not faults or len(set(faults)) != len(faults) or not set(faults) <= set(KNOWN_FAULTS):
        raise CasesError(f"faults must be distinct known faults {KNOWN_FAULTS}, got {faults}")
    return faults


def run(pool, faults=KNOWN_FAULTS, model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT,
        watch_path=cw.DEFAULT_OUT, normals_path=evidence_normals.DEFAULT_OUT, *, out_root=DEFAULT_DIR,
        allow_dirty=False, repo_root=None, now=None):
    faults = check_request(pool, faults)
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(out_root) / f"{stamp}_{pool}"
    if out_dir.exists():
        raise FileExistsError(f"{out_dir} exists; cases are never overwritten")
    inp = load_inputs(model_path, limits_path, watch_path, normals_path, repo_root)

    record_rel = (run_record.RUNS_DIR / f"{stamp}_cases.json").as_posix()
    paths, summary = {}, {}
    out_dir.mkdir(parents=True)
    for f in faults:
        runs = loader.load_faulty(f, pool)
        if runs.pool != pool:
            raise CasesError(f"asked for pool {pool}, the loader gave {runs.pool}")
        per_run = score_pool(inp, runs)
        doc = {"fault": f, "family": dev_table.FAMILIES[f], "pool": pool,
               "runs": [int(k) for k in sorted(runs.runs)], "commit": commit, "dirty": dirty,
               "record": record_rel, "inputs": inp.records, "per_run": per_run}
        paths[f] = out_dir / f"fault_{f:02d}.json"
        with open(paths[f], "x") as fh:
            json.dump(doc, fh)
        summary[f"fault_{f:02d}"] = {"runs": len(per_run), "detected": sum(r["detected"] for r in per_run)}

    record = run_record.write(
        "cases",
        config={"pool": pool, "faults": list(faults), **inp.records,
                "limits_sha256": inp.limits_sha256, "readings": dict(features.READINGS)},
        seeds={}, metrics=summary,
        outputs={f"fault_{f:02d}": paths[f] for f in faults},
        commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    if Path(record) != repo_root / record_rel:
        raise CasesError(f"the case files name {record_rel}, but the record is {record}")
    for f in faults:
        s = summary[f"fault_{f:02d}"]
        print(f"fault {f:2d}: {s['detected']} of {s['runs']} {pool} runs detected -> {paths[f]}")
    print(f"run record: {record}")
    return paths, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pool", choices=POOLS)
    parser.add_argument("--faults", type=int, nargs="+", default=list(KNOWN_FAULTS))
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--watch", type=Path, default=cw.DEFAULT_OUT)
    parser.add_argument("--normals", type=Path, default=evidence_normals.DEFAULT_OUT)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.pool, args.faults, args.model, args.limits, args.watch, args.normals,
            allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, evidence_normals.NormalsError, CasesError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())