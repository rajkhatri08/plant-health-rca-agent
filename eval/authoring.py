"""Authoring evidence: signature features on the authoring runs only (LEAKAGE wall 3;
decisions 49, 67, 68).

    python -m eval.authoring [--model data/models/pca_static.npz]
                             [--limits data/models/pca_static_limits.json]
                             [--watch data/models/pca_static_watch.json]
                             [--normals data/models/evidence_normals.json] [--allow-dirty]

For each of FAULTS, loads the authoring pool: the same 5 non-dev run numbers for every
fault (dataset/splits.yaml). Nothing else: no dev, no selection runs, no other fault. Per
run it scores App 3 exactly as evaluation does, through eval/cases.py's shared path
(load_inputs, score_pool; S3 moved it there unchanged): the alert track and first
notification, group and tag RBC over the Watch boundaries, and the features at the
notification, +30 min and +60 min. Analyzer publications are recovered from the held
series there, and a change off the update schedule refuses the run.

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

import yaml

from app.detector import features
from dataset import loader
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import cases, dev_table, evidence_normals, run_record

FAULTS = (1, 4, 5, 6, 13)                  # Raj's first entries (Q11): one per family
POOL = "authoring"
AUTHORING_RUNS = 5
DEFAULT_DIR = run_record.REPO_ROOT / "eval" / "provenance"


AuthoringError = cases.CasesError          # one error type for the shared path and this driver
publications_from_held = cases.publications_from_held


def load_authoring(fault):
    """The authoring pool for one fault, and nothing else."""
    if fault not in FAULTS:
        raise AuthoringError(f"fault {fault} isn't one of the authored faults {FAULTS}")
    runs = loader.load_faulty(fault, POOL)
    if runs.pool != POOL or len(runs.runs) != AUTHORING_RUNS:
        raise AuthoringError(f"expected {AUTHORING_RUNS} authoring runs for fault {fault}, got "
                             f"{len(runs.runs)} from {runs.pool}")
    return runs


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
    inp = cases.load_inputs(model_path, limits_path, watch_path, normals_path, repo_root)

    now = datetime.now(timezone.utc)
    record_rel = (run_record.RUNS_DIR / f"{now.strftime('%Y%m%dT%H%M%SZ')}_authoring.json").as_posix()
    docs, summary_metrics = {}, {}
    for f in FAULTS:
        runs = load_authoring(f)
        per_run = cases.score_pool(inp, runs)
        docs[f] = {"fault": f, "family": dev_table.FAMILIES[f], "pool": POOL,
                   "runs": [int(k) for k in sorted(runs.runs)], "commit": commit, "dirty": dirty, "record": record_rel,
                   "inputs": dict(inp.records),
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
                "limits_sha256": inp.limits_sha256,
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
