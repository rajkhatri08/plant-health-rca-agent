"""Dev false alerts per 24 h at the calibrated setting (PROTOCOL, Detection metrics).

    python -m eval.check_dev [--limits data/models/pca_static_limits.json]
                             [--model data/models/pca_static.npz]
                             [--watch data/models/pca_static_watch.json] [--allow-dirty]

A sanity reading on the normal dev runs, not a selection step: nothing here feeds back
into calibration. Uses the same alert path as calibration (app/detector/alerting.py)
and the protocol's bootstrap over run numbers (B = 2000, percentile interval).

Checks that the model matches the limits file and that the limits file came from one
calibrate_pca run record. Writes a dev_false_alerts run record. Prints only counts,
hours, the rate, its interval and the record's path.

With --watch (a watch file from eval/calibrate_watch.py, made from these limits and this
model), it also reads the Watch band on the same normal dev runs (decision 66): the share
of scored samples with any group in Watch, and each group's own share, at the calibrated
W_g. That's a sanity reading too; nothing is tuned on it.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from app.detector import pca
from dataset import loader
from eval import calibrate as cal
from eval import calibrate_driver as drv
from eval import metrics, run_record

BOOTSTRAP_SEED = 20260930


def calibration_record_for(limits_path, repo_root):
    """Path of the single calibrate_pca record whose limits output is this file."""
    sha = run_record.sha256(limits_path)
    matches = [p for p in sorted((Path(repo_root) / run_record.RUNS_DIR).glob("*_calibrate_pca.json"))
               if json.loads(p.read_text()).get("outputs", {}).get("limits", {}).get("sha256") == sha]
    if len(matches) != 1:
        raise drv.CalibrationError(f"expected one calibrate_pca record for {limits_path}, "
                                   f"found {len(matches)}")
    return matches[0]


def run(limits_path=drv.DEFAULT_OUT, model_path=drv.DEFAULT_MODEL, *, watch_path=None,
        allow_dirty=False, repo_root=None, n_boot=metrics.BOOTSTRAP_N):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    cal_record = calibration_record_for(limits_path, repo_root)
    lim = json.loads(Path(limits_path).read_text())
    if run_record.sha256(model_path) != lim["model_sha256"]:
        raise drv.CalibrationError(f"{model_path} isn't the model these limits were calibrated for")
    model = pca.load(model_path)
    warmup = lim["warmup"]
    watch = None
    if watch_path is not None:
        # Imported here: calibrate_watch imports this module for calibration_record_for.
        from eval import calibrate_watch as cw
        watch_record, watch_doc = cw.load_watch(watch_path, limits_path, model, repo_root)

    dev = loader.load_normal("dev")
    scored = drv.score_runs(model, dev, lags=lim["lags"])
    alert = drv.tracks(scored, (lim["t2_lim"], lim["spe_lim"]), lim["n"], lim["gap"], warmup,
                       lim["lags"])
    runs = [metrics.ScoredRun(0, k, a) for k, a in alert.items()]
    count, hours, per_24h = metrics.false_alerts_per_24h(runs, warmup)
    low, high = metrics.bootstrap_ci(runs, lambda rs: metrics.false_alerts_per_24h(rs, warmup)[2],
                                     np.random.default_rng(BOOTSTRAP_SEED), n=n_boot)
    config_watch = {}
    if watch_path is not None:
        names = list(watch_doc["groups"])
        by_group, _ = cw.rbc_runs(model, lim, dev, names)
        w = np.array([watch_doc["groups"][g]["w"] for g in names])
        any_share, per = cal.watch_shares([by_group[k] for k in sorted(by_group)], w, warmup)
        watch = {"p": watch_doc["p"], "cap": watch_doc["cap"], "any_group_share": any_share,
                 "group_shares": {g: float(s) for g, s in zip(names, per)}}
        config_watch = {"watch_record": watch_record.relative_to(repo_root).as_posix(),
                        "watch_sha256": run_record.sha256(watch_path)}
    record = run_record.write(
        "dev_false_alerts",
        config={"detector": lim["detector"], "pool": "dev", "warmup": warmup,
                "lags": lim["lags"], "n": lim["n"], "gap": lim["gap"], "q": lim["q"],
                "calibration_record": cal_record.relative_to(repo_root).as_posix(),
                "limits_sha256": run_record.sha256(limits_path),
                "bootstrap": {"resamples": n_boot, "level": 0.95, "method": "percentile"},
                **config_watch},
        seeds={"bootstrap": BOOTSTRAP_SEED},
        metrics={"runs": len(runs), "notifications": count, "hours": hours,
                 "per_24h": per_24h, "ci95": [low, high],
                 "budget_per_24h": cal.BUDGET_PER_24H,
                 **({"watch": watch} if watch else {})},
        outputs={}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"dev: {len(runs)} normal runs, {hours:.1f} h scored, {count} notifications")
    print(f"false alerts per 24 h: {per_24h:.3f} (95% interval {low:.3f} to {high:.3f}; "
          f"budget {cal.BUDGET_PER_24H})")
    if watch:
        print(f"Watch (p = {watch['p']}): any group {watch['any_group_share']:.4f} of scored "
              f"samples (cap {watch['cap']} on calibration); "
              + ", ".join(f"{g} {s:.4f}" for g, s in watch["group_shares"].items()))
    print(f"run record: {record}")
    return count, hours, per_24h, (low, high)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--watch", type=Path, default=None,
                        help="a watch file (eval/calibrate_watch.py) for the Watch shares on dev")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.limits, args.model, watch_path=args.watch, allow_dirty=args.allow_dirty)
    except (ValueError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())