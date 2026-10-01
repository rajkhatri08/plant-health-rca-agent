"""Authoring evidence: signature features on the authoring runs only (LEAKAGE wall 3;
decisions 49, 67, 68).

    python -m eval.authoring [--model data/models/pca_static.npz]
                             [--limits data/models/pca_static_limits.json]
                             [--watch data/models/pca_static_watch.json]
                             [--normals data/models/evidence_normals.json] [--allow-dirty]

For each of FAULTS, loads the authoring pool: the same 5 non-dev run numbers for every
fault (dataset/splits.yaml). Nothing else: no dev, no selection runs, no other fault. Per
run it scores App 3 exactly as evaluation does:
- the alert track (calibrate_driver.score_runs and tracks) and the first notification in
  the detection window (metrics.detection)
- group and tag RBC over the Watch boundaries (calibrate_watch.rbc_runs)
- the features at the notification (location), +30 min (provisional) and +60 min
  (revised), through app/detector/features.py, the code the agent's tools will use

Analyzers are stored as held series. Their published values are recovered here: the
samples where the held value changes must all fall on one schedule, every update interval
(library/tags.yaml), and the publications are every sample on that schedule. If a change
falls off the schedule, the run is refused rather than guessed at.

Writes eval/provenance/fault_NN.yaml per fault (builder side, never library/): the runs
used, each run's detection and features, and per feature the count of each state over the
detected runs. That is what the entry's signature is written from. Also writes an
authoring run record naming every input's checksum and holding each provenance file's
SHA-256. Prints only counts and paths. Refuses a dirty tree unless --allow-dirty, and
never overwrites a provenance file.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

from app.detector import features
from dataset import loader
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import dev_table, evidence_normals, metrics, run_record
from ingest import tags as tagmap

FAULTS = (1, 4, 5, 6, 13)                  # Raj's first entries (Q11): one per family
POOL = "authoring"
AUTHORING_RUNS = 5
ONSET = metrics.TRAIN_ONSET
SAMPLE_MIN = metrics.SAMPLE_MIN
DEFAULT_DIR = run_record.REPO_ROOT / "eval" / "provenance"


class AuthoringError(RuntimeError):
    pass


def load_authoring(fault):
    """The authoring pool for one fault, and nothing else."""
    if fault not in FAULTS:
        raise AuthoringError(f"fault {fault} isn't one of the authored faults {FAULTS}")
    runs = loader.load_faulty(fault, POOL)
    if runs.pool != POOL or len(runs.runs) != AUTHORING_RUNS:
        raise AuthoringError(f"expected {AUTHORING_RUNS} authoring runs for fault {fault}, got "
                             f"{len(runs.runs)} from {runs.pool}")
    return runs


def publications_from_held(series, interval):
    """[(sample, value), ...] from a held analyzer series (1-based samples). The changes
    must all fall on one schedule s = phase (mod interval); the publications are every
    sample on it. Raises AuthoringError if a change is off the schedule, or if there's
    none to set the phase."""
    x = np.asarray(series, dtype=np.float64)
    changes = [i + 1 for i in range(1, len(x)) if x[i] != x[i - 1]]
    if not changes:
        raise AuthoringError("a held analyzer series never changes; its schedule can't be found")
    phase = changes[0] % interval
    off = [s for s in changes if s % interval != phase]
    if off:
        raise AuthoringError(f"held values change off the {interval}-sample schedule at samples {off[:5]}")
    return [(s, float(x[s - 1])) for s in range(1, len(x) + 1) if s % interval == phase]


def _counts(items):
    """{feature: {state: count}} over the detected runs' values."""
    out = {}
    for item in items:
        for key, state in item.items():
            out.setdefault(key, {})
            out[key][str(state)] = out[key].get(str(state), 0) + 1
    return {k: dict(sorted(v.items())) for k, v in out.items()}


def summarise(per_run):
    """Per feature, the count of each state over the detected runs."""
    got = [r["features"] for r in per_run if r["detected"]]
    summary = {"detected": len(got), "runs": len(per_run),
               "location": {"top_group": _counts([{"top_group": f["location"]["top_group"]} for f in got])["top_group"]
                            if got else {},
                            "top_tags": _counts([{t: "in top 3" for t in f["location"]["top_tags"]} for f in got])}}
    for name in features.READINGS:
        have = [f[name] for f in got if name in f]
        summary[name] = {"tags": _counts([f["tags"] for f in have]),
                         "loops": _counts([f["loops"] for f in have]),
                         "analyzers": _counts([f["analyzers"] for f in have]),
                         "masked": _counts([{"masked": f["masked"]} for f in have]).get("masked", {})}
    return summary


def run(model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT, watch_path=cw.DEFAULT_OUT,
        normals_path=evidence_normals.DEFAULT_OUT, *, out_dir=DEFAULT_DIR, allow_dirty=False,
        repo_root=None):
    out_dir = Path(out_dir)
    paths = {f: out_dir / f"fault_{f:02d}.yaml" for f in FAULTS}
    existing = [str(p) for p in paths.values() if p.exists()]
    if existing:
        raise FileExistsError(f"provenance files exist: {existing}; they are never overwritten")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    cal_record, lim, model = cw.load_pair(limits_path, model_path, repo_root)
    watch_record, watch = cw.load_watch(watch_path, limits_path, model, repo_root)
    normals_record, bands = evidence_normals.load_normals(normals_path, repo_root)
    plant = features.plant_from_files(model.tags)
    names = list(watch["groups"])
    w_group = np.array([watch["groups"][g]["w"] for g in names])
    w_tag = np.array([watch["tags"][t] for t in model.tags])
    interval = {r["tag"]: r["update_interval_min"] // SAMPLE_MIN for r in tagmap.register()
                if r["kind"] == "analyzer"}
    warmup, n = lim["warmup"], lim["n"]

    now = datetime.now(timezone.utc)
    record_rel = (run_record.RUNS_DIR / f"{now.strftime('%Y%m%dT%H%M%SZ')}_authoring.json").as_posix()
    docs, summary_metrics = {}, {}
    for f in FAULTS:
        runs = load_authoring(f)
        scored = drv.score_runs(model, runs)
        tracks = drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), n, lim["gap"], warmup)
        by_group, by_tag = cw.rbc_runs(model, lim, runs, names)
        fast_cols = tagmap.column_indices(runs.columns, model.tags)
        an_cols = dict(zip(plant.analyzers, tagmap.column_indices(runs.columns, plant.analyzers)))
        per_run = []
        for k in sorted(runs.runs):
            x = runs.runs[k]
            det = metrics.detection(tracks[k], ONSET, warmup=warmup)
            row = {"run": int(k), "detected": bool(det.detected),
                   "notification_sample": int(det.sample) if det.detected else None,
                   "delay_min": float(det.delay_min) if det.detected else None}
            if det.detected:
                pubs = {t: publications_from_held(x[:, c], interval[t]) for t, c in an_cols.items()}
                row["features"] = features.extract(
                    plant, x[:, fast_cols], pubs, bands, det.sample, n,
                    by_group[k] / w_group, by_tag[k] / w_tag, names)
            per_run.append(row)
        docs[f] = {"fault": f, "family": dev_table.FAMILIES[f], "pool": POOL,
                   "runs": [int(k) for k in sorted(runs.runs)], "commit": commit, "dirty": dirty, "record": record_rel,
                   "inputs": {"calibration_record": cal_record.relative_to(repo_root).as_posix(),
                              "watch_record": watch_record.relative_to(repo_root).as_posix(),
                              "normals_record": normals_record.relative_to(repo_root).as_posix()},
                   "summary": summarise(per_run), "per_run": per_run}
        summary_metrics[f"fault_{f:02d}"] = {
            "detected": sum(r["detected"] for r in per_run),
            "notification_samples": [r["notification_sample"] or 0 for r in per_run]}

    out_dir.mkdir(parents=True, exist_ok=True)
    for f, doc in docs.items():
        with open(paths[f], "x") as fh:
            fh.write("# Builder side (LEAKAGE wall 3): authoring evidence for one fault. Never copy\n"
                     "# run numbers or fault numbers into library/.\n")
            yaml.safe_dump(doc, fh, sort_keys=False)
    record = run_record.write(
        "authoring",
        config={"faults": list(FAULTS), "pool": POOL, "runs": docs[FAULTS[0]]["runs"],
                "calibration_record": docs[FAULTS[0]]["inputs"]["calibration_record"],
                "watch_record": docs[FAULTS[0]]["inputs"]["watch_record"],
                "normals_record": docs[FAULTS[0]]["inputs"]["normals_record"],
                "limits_sha256": run_record.sha256(limits_path),
                "readings": dict(features.READINGS)},
        seeds={},
        metrics=summary_metrics,
        outputs={f"fault_{f:02d}": paths[f] for f in FAULTS},
        commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    if Path(record) != repo_root / record_rel:
        raise AuthoringError(f"the provenance files name {record_rel}, but the record is {record}")
    for f in FAULTS:
        print(f"fault {f:2d}: {summary_metrics[f'fault_{f:02d}']['detected']} of {AUTHORING_RUNS} "
              f"authoring runs detected -> {paths[f]}")
    print(f"run record: {record}")
    return docs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--watch", type=Path, default=cw.DEFAULT_OUT)
    parser.add_argument("--normals", type=Path, default=evidence_normals.DEFAULT_OUT)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.model, args.limits, args.watch, args.normals, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, evidence_normals.NormalsError, AuthoringError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
