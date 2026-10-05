"""The two detection curves PROTOCOL asks for (Detection metrics, Delay; week 7 S1e).

    python -m eval.curves amoc [--split dev|test] [--limits …] [--model …]
    python -m eval.curves plot eval/runs/<stamp>_<dev|test>_table_pca_static.json
    python -m eval.curves plot eval/runs/<stamp>_<amoc|test_amoc>.json

- The cumulative detection curve: per fault, the share of runs detected within h minutes of
  onset, for h on HORIZONS_MIN (every 6 minutes to the 4-h useful window; 40 points, so a
  record can hold it). Misses never count. dev_table computes it from the same detections as
  the table and stores it in the dev_table / test_table record, per fault and as the
  equal-weight mean over the summary faults.
- The AMOC curve (Raj's sweep, amoc_sweep): App 3's static PCA only (Raj, S1e), at its
  calibrated n and G, over every q on the calibration grid. Each point is the false alerts
  per 24 h on the split's normal runs and the pooled median delay over every run of the
  split's summary faults (misses +inf, PROTOCOL's delay convention; Raj, S1e), with the
  detection rate beside it. The operating point is the calibrated q. The amoc command writes
  an amoc (dev) or test_amoc (test) record with every point; on test it loads the testing
  files through the split (Raj runs it with EVAL_MODE=1, never Claude).

Every figure is drawn from a run record (CLAUDE.md: every reported number comes from a run
record), into data/plots/ (gitignored). Prints only paths and one summary line.
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from dataset import loader
from eval import calibrate as cal
from eval import calibrate_driver as drv
from eval import metrics, run_record
from eval import split as split_mod

HORIZONS_MIN = tuple(range(6, metrics.WINDOW_SAMPLES * metrics.SAMPLE_MIN + 1, 6))     # 6, 12, ... 240
EXCLUDED = (3, 9, 15)
DEFAULT_PLOTS = run_record.REPO_ROOT / "data" / "plots"


class CurvesError(RuntimeError):
    pass


# ---------- the cumulative detection curve (Claude's) ----------

def cumulative_detection(delays_min, horizons_min=HORIZONS_MIN) -> list:
    """[share of runs detected within h minutes of onset, for each h]. delays_min holds one
    delay per run (metrics.detection's delay_min; +inf for a miss). Raises ValueError on an
    empty list or a negative or NaN delay."""
    d = np.asarray(list(delays_min), dtype=np.float64)
    if d.size == 0:
        raise ValueError("no runs")
    if np.isnan(d).any() or (d < 0).any():
        raise ValueError("delays must be minutes >= 0, or +inf for a miss")
    return [float(np.count_nonzero(d <= h) / d.size) for h in horizons_min]


def cumulative_block(delays_by_fault, summary_faults, horizons_min=HORIZONS_MIN) -> dict:
    """The record's "cumulative" block: {"horizons_min", "faults": {fault_NN: [...]},
    "summary": [...]} with the summary the equal-weight mean over summary_faults."""
    faults = {f"fault_{f:02d}": cumulative_detection(d, horizons_min) for f, d in sorted(delays_by_fault.items())}
    mean = np.mean([faults[f"fault_{f:02d}"] for f in summary_faults], axis=0)
    return {"horizons_min": list(horizons_min), "faults": faults, "summary": [float(x) for x in mean],
            "summary_faults": list(summary_faults)}


# ---------- the AMOC sweep (Raj's) ----------

def amoc_sweep(cal_scored, normal_scored, fault_scored, n, gap, warmup, onset, q_grid, lags=0) -> list:
    """One AMOC point per q in q_grid, in grid order (Raj implements this; week 7 S1e).

    Inputs (each {run number: (T² array, SPE array)} over whole runs, index 0 = sample 1,
    as calibrate_driver.score_runs gives them):
    - cal_scored: the calibration pool, which sets the limits at each q
    - normal_scored: the split's normal runs (false alerts)
    - fault_scored: {fault: {run number: (T², SPE)}}, the split's summary faults (delays)
    n, gap, warmup, lags: the calibrated persistence, off-delay, warm-up and lags; onset: the
    split's last pre-fault sample (20 on dev, 160 on test); q_grid: strictly increasing.

    For each q:
    - limits: calibrate.limits_at over the calibration pool's T² and SPE (warm-up excluded)
    - alert tracks: calibrate_driver.tracks(scored, limits, n, gap, warmup, lags)
    - per_24h: metrics.false_alerts_per_24h over the normal runs' tracks, as fault 0
    - delay_min: the median of metrics.delay_summary over every fault run's
      metrics.detection(track, onset, warmup=warmup).delay_min, pooled across faults
      (misses +inf, so +inf when more than half are missed)
    - detection_rate: the share of those fault runs detected

    Returns [{"q", "per_24h", "delay_min", "detection_rate"}, ...] (floats; delay_min may be
    math.inf). Raises ValueError if q_grid is empty or not strictly increasing, or if
    normal_scored or fault_scored is empty."""
    raise NotImplementedError("Raj implements amoc_sweep (week 7 S1e)")


def operating_point(points, q):
    """The point at the calibrated q; it must be on the grid."""
    for p in points:
        if p["q"] == q:
            return p
    raise CurvesError(f"the calibrated q = {q} isn't on the sweep's grid")


# ---------- the AMOC run ----------

def run_amoc(limits_path=drv.DEFAULT_OUT, model_path=drv.DEFAULT_MODEL, *, split="dev", allow_dirty=False,
             repo_root=None, q_grid=cal.Q_GRID, now=None, out=print):
    """Score once, sweep (amoc_sweep), and write the amoc / test_amoc record. The detector is
    App 3's static PCA, from its limits and their calibration record (dev_table.load_detector)."""
    from eval import dev_table                     # its detector loading and checks
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    det, cal_record, limits_sha = dev_table.load_detector(limits_path, model_path, None, repo_root)
    if not isinstance(det, dev_table.PCADetector) or det.lags != 0:
        raise CurvesError("the AMOC curve is for App 3's static PCA only (Raj, S1e)")
    lim = det.lim
    if lim["q"] not in q_grid:
        raise CurvesError(f"the calibrated q = {lim['q']} isn't on the grid")
    name = "test_amoc" if split == "test" else "amoc"
    sp = split_mod.get(split, name)
    summary = tuple(f for f in sp.faults if f not in EXCLUDED)

    cal_scored = drv.score_runs(det.model, loader.load_normal("calibration"))   # open data on either split
    normal_scored = drv.score_runs(det.model, sp.load_normal())
    fault_scored = {f: drv.score_runs(det.model, sp.load_faulty(f)) for f in summary}
    points = amoc_sweep(cal_scored, normal_scored, fault_scored, lim["n"], lim["gap"], lim["warmup"],
                        sp.onset, q_grid)
    if [p["q"] for p in points] != list(q_grid):
        raise CurvesError("the sweep must give one point per grid q, in grid order")
    op = operating_point(points, lim["q"])
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    metrics_ = {"points": {repr(p["q"]): {k: p[k] for k in ("per_24h", "delay_min", "detection_rate")}
                           for p in points},
                "operating_point": {"q": lim["q"], **{k: op[k] for k in ("per_24h", "delay_min", "detection_rate")}},
                "infinite_delay_points": sum(math.isinf(p["delay_min"]) for p in points)}
    config = {"detector": det.name, "split": sp.name, "onset": sp.onset, "n": lim["n"], "gap": lim["gap"],
              "warmup": lim["warmup"], "q_grid": {"first": q_grid[0], "last": q_grid[-1], "points": len(q_grid)},
              "summary_faults": list(summary), "normal_runs": len(normal_scored),
              "calibration_record": cal_record.relative_to(repo_root).as_posix(), "limits_sha256": limits_sha,
              "delay": "pooled median over every summary-fault run, misses +inf (Raj, S1e)"}
    record = run_record.write(name, config=config, seeds={}, metrics=metrics_, outputs={}, commit=commit,
                              dirty=dirty, repo_root=repo_root, now=now)
    out(f"{sp.name}: {len(points)} AMOC points; operating point q = {lim['q']}: "
        f"{op['per_24h']:.3f} false alerts per 24 h, delay {op['delay_min']} min\nrun record: {record}")
    return metrics_, record


# ---------- plots, from records only ----------

def _finite(x):
    return x not in ("inf", math.inf) and x is not None


def plot(record_path, plots_dir=DEFAULT_PLOTS, out=print):
    """A PNG from a record: the cumulative detection curve from a dev_table / test_table
    record, or the AMOC curve from an amoc / test_amoc record. Returns the PNG's path."""
    import matplotlib
    matplotlib.use("Agg")                          # files only, no window
    import matplotlib.pyplot as plt

    record_path = Path(record_path)
    rec = json.loads(record_path.read_text())
    name, m = rec["name"], rec["metrics"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    if name.startswith(("dev_table_", "test_table_")):
        cum = m.get("cumulative")
        if not cum:
            raise CurvesError(f"{record_path} has no cumulative block (made before S1e)")
        h = cum["horizons_min"]
        for key, ys in cum["faults"].items():
            ax.plot(h, ys, color="0.75", linewidth=0.8)
        ax.plot(h, cum["summary"], color="C0", linewidth=2.2,
                label=f"mean, {len(cum['summary_faults'])} summary faults")
        ax.set(xlabel="minutes after onset", ylabel="share of runs detected", ylim=(0, 1.02),
               title=f"Cumulative detection: {rec['config']['detector']} ({rec['config']['pool']})")
        ax.legend(loc="lower right")
        kind = "cumulative"
    elif name in ("amoc", "test_amoc"):
        pts = [(float(q), v) for q, v in m["points"].items()]
        fin = [(v["per_24h"], v["delay_min"]) for _, v in sorted(pts) if _finite(v["delay_min"])]
        if fin:
            xs, ys = zip(*sorted(fin))
            ax.plot(xs, ys, color="C0", linewidth=1.6, label="App 3 (static PCA), q grid")
        op = m["operating_point"]
        if _finite(op["delay_min"]):
            ax.plot([op["per_24h"]], [op["delay_min"]], "o", color="C3", markersize=8,
                    label=f"operating point, q = {op['q']}")
        ax.set_xscale("symlog", linthresh=0.1)
        ax.set(xlabel="false alerts per 24 h (normal runs)", ylabel="median delay, min (pooled)",
               title=f"AMOC: {rec['config']['detector']} ({rec['config']['split']}); "
                     f"{m['infinite_delay_points']} points with infinite delay not drawn")
        ax.legend(loc="upper right")
        kind = "amoc"
    else:
        raise CurvesError(f"{record_path} is neither a detection table nor an AMOC record")
    fig.tight_layout()
    plots_dir = Path(plots_dir)
    plots_dir.mkdir(parents=True, exist_ok=True)
    png = plots_dir / f"{record_path.stem}_{kind}.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    out(f"plot: {png}")
    return png


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("amoc", help="sweep the q grid and write an amoc / test_amoc record")
    a.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    a.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    a.add_argument("--split", choices=split_mod.NAMES, default="dev")
    a.add_argument("--allow-dirty", action="store_true")
    p = sub.add_parser("plot", help="draw a PNG from a detection-table or AMOC record")
    p.add_argument("record", type=Path)
    p.add_argument("--plots", type=Path, default=DEFAULT_PLOTS)
    args = parser.parse_args(argv)
    from eval import dev_table
    try:
        if args.cmd == "amoc":
            run_amoc(args.limits, args.model, split=args.split, allow_dirty=args.allow_dirty)
        else:
            plot(args.record, args.plots)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, dev_table.DevTableError, CurvesError, NotImplementedError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())