"""Does the finer top of the q grid (decision 59) change the static-PCA calibration?

    python -m eval.check_grid_refinement [--limits data/models/pca_static_limits.json]
                                         [--model data/models/pca_static.npz] [--allow-dirty]

calibrate.lowest_stable_q scans the grid from the top down and stops at the first
failure. So for each (n, G), the new grid's answer follows from the nine new points
alone (99.991 ... 99.999) and the old answer in the calibrate_pca record:
- all nine pass: the scan continues into the old grid, so the stable q is the old one
  (or 99.991, if the old grid's top already failed)
- otherwise: lowest_stable_q over the nine points alone (a new point, or None)
This runs lowest_stable_q over the nine new points only, on the calibration pool, with
the same limits and alert path as the calibration driver. Nothing is re-calibrated.

If every setting's stable q is unchanged, the selection scores (which depend only on
n, G and q) and the chosen setting are unchanged too. Writes a check_grid_refinement
run record, prints the verdict, and exits 1 if anything changed. Never loads dev.
"""

import argparse
import json
import sys
from pathlib import Path

from app.detector import alerting, pca
from dataset import loader
from eval import calibrate as cal
from eval import calibrate_driver as drv
from eval import check_dev, run_record

OLD_TOP = 99.99
NEW_POINTS = tuple(q for q in cal.Q_GRID if q > OLD_TOP)           # 99.991 .. 99.999


def new_stable_q(old_q, top_q, new_points=NEW_POINTS):
    """The stable q on the refined grid, from the old answer and lowest_stable_q over
    the new points alone (top_q)."""
    if top_q == new_points[0]:                  # every new point passes
        return new_points[0] if old_q is None else old_q
    return top_q                                # a new point failed: the scan stops above it


def run(limits_path=drv.DEFAULT_OUT, model_path=drv.DEFAULT_MODEL, *, allow_dirty=False,
        repo_root=None, new_points=NEW_POINTS):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    cal_path = check_dev.calibration_record_for(limits_path, repo_root)
    cal_rec = json.loads(cal_path.read_text())
    lim = json.loads(Path(limits_path).read_text())
    if run_record.sha256(model_path) != lim["model_sha256"]:
        raise drv.CalibrationError(f"{model_path} isn't the model these limits were calibrated for")
    warmup, lags = lim["warmup"], lim["lags"]
    model = pca.load(model_path)

    scored = drv.score_runs(model, loader.load_normal("calibration"))
    numbers = sorted(scored)
    t2_runs = [scored[k][0] for k in numbers]
    spe_runs = [scored[k][1] for k in numbers]

    def ratio_runs_at(q):
        limits = cal.limits_at(t2_runs, spe_runs, q, warmup)
        return {k: alerting.plant_ratio(t2, spe, *limits) for k, (t2, spe) in scored.items()}

    per_q = {}                                  # ratio tracks per new point, built once
    def cached(q):
        if q not in per_q:
            per_q[q] = ratio_runs_at(q)
        return per_q[q]

    settings, changed = {}, []
    for key, row in cal_rec["metrics"]["settings"].items():
        n, gap = (int(x) for x in key[1:].split("_g"))
        top = cal.lowest_stable_q(cached, n, gap, warmup, lags, new_points)
        new_q = new_stable_q(row["q"], top, new_points)
        settings[key] = {"old_q": row["q"], "new_q": new_q, "new_points_stable_from": top}
        if new_q != row["q"]:
            changed.append(key)
    chosen = cal_rec["metrics"]["chosen"]
    unchanged = not changed
    record = run_record.write(
        "check_grid_refinement",
        config={"detector": lim["detector"], "warmup": warmup, "lags": lags,
                "new_points": list(new_points), "old_top": OLD_TOP,
                "calibration_record": cal_path.relative_to(repo_root).as_posix(),
                "limits_sha256": run_record.sha256(limits_path),
                "model_sha256": lim["model_sha256"], "calibration_runs": len(numbers)},
        seeds={},
        metrics={"settings_checked": len(settings), "changed": len(changed),
                 "all_new_points_pass": sum(s["new_points_stable_from"] == new_points[0]
                                            for s in settings.values()),
                 "unchanged": unchanged,
                 "chosen": {"n": chosen["n"], "gap": chosen["gap"], "q": chosen["q"],
                            "still_chosen": unchanged},
                 "settings": settings},
        outputs={}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"{len(settings)} settings checked at {len(new_points)} new grid points "
          f"({new_points[0]} .. {new_points[-1]}) on {len(numbers)} calibration runs")
    if unchanged:
        print(f"unchanged: every stable q is the same, so the chosen setting stands "
              f"(n = {chosen['n']}, G = {chosen['gap']}, q = {chosen['q']})")
    else:
        print(f"CHANGED: {len(changed)} settings, e.g. {changed[:5]}; re-calibrate static PCA")
    print(f"run record: {record}")
    return unchanged, settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        unchanged, _ = run(args.limits, args.model, allow_dirty=args.allow_dirty)
    except (ValueError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0 if unchanged else 1


if __name__ == "__main__":
    sys.exit(main())