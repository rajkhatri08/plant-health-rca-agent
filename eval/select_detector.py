"""Static PCA or DPCA: decision 63's selection rule, applied to the two calibrations.

    python -m eval.select_detector [--static data/models/pca_static_limits.json]
                                   [--dynamic data/models/pca_dynamic_limits.json]
                                   [--allow-dirty]

Each limits file leads to the one calibrate_pca run record that wrote it (as in
check_dev and dev_table), so a superseded record can't be picked by mistake. The rule
reads each record's selection score (metrics.chosen.score: the mean detection rate over
the 12 selection faults on the 100 selection runs, at that detector's own n, G and q).
DPCA replaces static PCA only if its score is more than MARGIN higher; otherwise the
simpler static PCA stays. Nothing is recomputed and no run data is loaded.

The two calibrations must be comparable: same selection faults, selection runs, budget,
warm-up, data manifest and splits, and both from a clean tree. If their q grids differ
(static PCA was calibrated before decision 59's finer grid top), a clean
check_grid_refinement record for the static limits must show the chosen setting
unchanged on the finer grid.

Writes a select_detector run record and prints the scores, the difference and the verdict.
"""

import argparse
import json
import sys
from pathlib import Path

from eval import calibrate_driver as drv
from eval import check_dev, run_record

MARGIN = 0.03              # decision 63: "more than 3 points", on the 0-1 scale
# Selection scores are means of detection rates over 12 faults x 100 runs, so they move
# in steps of 1/1200. TOLERANCE only absorbs float rounding in the difference (0.53 - 0.5
# is 0.030000000000000027), so a difference of exactly 3 points keeps static PCA.
TOLERANCE = 1e-9
STATIC, DYNAMIC = "pca_static", "pca_dynamic"
MUST_MATCH = ("selection_faults", "selection_runs", "budget_per_24h", "warmup")
DEFAULT_STATIC = drv.DEFAULT_OUT
DEFAULT_DYNAMIC = drv.DEFAULT_OUT.parent / "pca_dynamic_limits.json"


class SelectionError(RuntimeError):
    pass


def verdict(static_score, dynamic_score, margin=MARGIN):
    """(difference, chosen detector). DPCA only when it is more than margin higher."""
    difference = dynamic_score - static_score
    return difference, (DYNAMIC if difference > margin + TOLERANCE else STATIC)


def _calibration(limits_path, repo_root, detector):
    """(record path, record) of the calibrate_pca run that wrote limits_path."""
    path = check_dev.calibration_record_for(limits_path, repo_root)
    rec = json.loads(path.read_text())
    if rec["config"]["detector"] != detector:
        raise SelectionError(f"{limits_path} is {rec['config']['detector']}, expected {detector}")
    if rec["dirty"] is not False:
        raise SelectionError(f"{path.name} came from a dirty tree; its score can't be used")
    return path, rec


def _grid_check(static_path, static_limits, repo_root):
    """The one clean check_grid_refinement record for these static limits, showing the
    chosen setting unchanged on the finer grid (decision 59)."""
    rel = static_path.relative_to(repo_root).as_posix()
    sha = run_record.sha256(static_limits)
    runs = Path(repo_root) / run_record.RUNS_DIR
    matches = []
    for p in sorted(runs.glob("*_check_grid_refinement.json")):
        cfg = json.loads(p.read_text())["config"]
        if cfg.get("calibration_record") == rel and cfg.get("limits_sha256") == sha:
            matches.append(p)
    if len(matches) != 1:
        raise SelectionError(f"the q grids differ, and there are {len(matches)} "
                             f"check_grid_refinement records for {rel} (need one)")
    rec = json.loads(matches[0].read_text())
    if rec["dirty"] is not False or rec["metrics"].get("unchanged") is not True:
        raise SelectionError(f"{matches[0].name} doesn't show static PCA's setting unchanged "
                             "on the finer grid (from a clean tree)")
    return matches[0]


def run(static_limits=DEFAULT_STATIC, dynamic_limits=DEFAULT_DYNAMIC, *, allow_dirty=False,
        repo_root=None):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before reading anything
    s_path, s_rec = _calibration(static_limits, repo_root, STATIC)
    d_path, d_rec = _calibration(dynamic_limits, repo_root, DYNAMIC)
    s_cfg, d_cfg = s_rec["config"], d_rec["config"]
    if s_cfg["lags"] != 0:
        raise SelectionError(f"static PCA's record has lags = {s_cfg['lags']}")
    for key in MUST_MATCH:
        if s_cfg[key] != d_cfg[key]:
            raise SelectionError(f"the calibrations differ in {key}: {s_cfg[key]} and {d_cfg[key]}")
    if s_rec["data"] != d_rec["data"]:
        raise SelectionError("the calibrations used different data manifests or splits files")
    grid_path = None
    if s_cfg["q_grid"] != d_cfg["q_grid"]:
        grid_path = _grid_check(s_path, static_limits, repo_root)

    s_score = s_rec["metrics"]["chosen"]["score"]
    d_score = d_rec["metrics"]["chosen"]["score"]
    difference, chosen = verdict(s_score, d_score)
    rel = lambda p: p.relative_to(repo_root).as_posix()    # noqa: E731
    record = run_record.write(
        "select_detector",
        config={"rule": "decision 63", "margin": MARGIN, "tolerance": TOLERANCE,
                "static_calibration_record": rel(s_path),
                "dynamic_calibration_record": rel(d_path),
                "static_limits_sha256": run_record.sha256(static_limits),
                "dynamic_limits_sha256": run_record.sha256(dynamic_limits),
                "grid_check_record": rel(grid_path) if grid_path else None,
                "selection_faults": s_cfg["selection_faults"],
                "selection_runs": s_cfg["selection_runs"]},
        seeds={},
        metrics={"static_score": s_score, "dynamic_score": d_score, "difference": difference,
                 "dynamic_lags": d_cfg["lags"], "verdict": chosen},
        outputs={}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"selection score: static PCA {s_score:.4f}, DPCA (L = {d_cfg['lags']}) {d_score:.4f}, "
          f"difference {difference:+.4f} against a margin of {MARGIN}")
    print(f"verdict (decision 63): {chosen}")
    print(f"run record: {record}")
    return chosen, difference


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--static", type=Path, default=DEFAULT_STATIC)
    parser.add_argument("--dynamic", type=Path, default=DEFAULT_DYNAMIC)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.static, args.dynamic, allow_dirty=args.allow_dirty)
    except (FileNotFoundError, KeyError, run_record.RunRecordError, drv.CalibrationError,
            SelectionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
