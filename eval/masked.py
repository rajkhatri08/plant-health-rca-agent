"""The masked-fault list (decision 62; PROTOCOL, Loops).

    python -m eval.masked [--allow-dirty]

A fault is masked when a control loop holds its measurement while its valve absorbs the
fault. Per loop (library/loops.yaml), on one run:
- the window is the settled half of the 4 h after onset: samples onset + 41 .. onset + 80
  (2 to 4 h). Compensation is what the loop leaves behind once it has acted, so an onset
  transient in the measurement doesn't disqualify a fault the loop then holds.
- "held": the loop's controlled measurement is never outside its normal band for
  PERSIST consecutive samples in the window
- "absorbed": the loop's end valve (a cascade master's is the valve at the bottom of its
  cascade) is outside its normal band for PERSIST consecutive samples somewhere in it
- masked = held and absorbed
The normal band of a tag is the central 99% of the calibration pool's scored samples
(0.5th to 99.5th percentile, pooled, after the warm-up). For a proportional-only loop,
"held" means inside that band, not at the setpoint.

A fault is masked by loop L when at least MASKED_SHARE of its selection runs meet the
rule for L, and masked when any loop masks it. It's decided on the 100 selection runs
(dataset/selection.yaml, forest-ceiling numbers), never on dev, so dev stays an
independent check.

This labels faults for reporting; it isn't a detector. So it may look ahead within the
window. Nothing it produces reaches app/ or library/.

Writes a masked_faults run record: per fault, every loop's share of masked runs, the
masking loops and the verdict; also, as a sanity figure, the share of calibration runs
(normal, fake onset at sample 20, the same settled half-window, in-sample for the bands)
the rule would call masked.
Prints only the masked list and the record's path. Never loads dev.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from app.detector import loops as loop_map
from dataset import loader, selection
from eval import metrics, run_record
from ingest import tags as tagmap

WARMUP = 9                                  # decision 52
BAND = (0.5, 99.5)                          # central 99% of the calibration pool
PERSIST = 3                                 # consecutive samples (App 3's calibrated n)
MASKED_SHARE = 0.5                          # share of selection runs
ONSET = metrics.TRAIN_ONSET
WINDOW = metrics.WINDOW_SAMPLES             # 4 h
SETTLE = WINDOW // 2                        # judge only samples onset + 41 .. onset + 80
FAULTS = tuple(loader.OPEN_FAULTS)          # 1..15


class MaskedError(RuntimeError):
    pass


def normal_bands(runs, columns, warmup=WARMUP, band=BAND) -> dict:
    """{column index: (lo, hi)}: the band percentiles of the pooled scored samples.
    runs is a list of 2-D arrays (samples x all columns). Raises ValueError if runs is
    empty or the warm-up doesn't end inside every run."""
    if not runs:
        raise ValueError("no runs to set the bands")
    if any(not 0 <= warmup < len(r) for r in runs):
        raise ValueError(f"the warm-up ({warmup}) doesn't end inside every run")
    out = {}
    for c in columns:
        x = np.concatenate([np.asarray(r[warmup:, c], dtype=np.float64) for r in runs])
        if not np.isfinite(x).all():
            raise ValueError(f"column {c} holds NaN or inf")
        lo, hi = np.percentile(x, band)
        out[c] = (float(lo), float(hi))
    return out


def outside_for(x, lo, hi, n=PERSIST) -> bool:
    """True if x is outside [lo, hi] (strictly below lo or above hi) for n consecutive
    samples somewhere. The band's edges count as inside."""
    if n < 1:
        raise ValueError("n must be at least 1")
    out = (np.asarray(x) < lo) | (np.asarray(x) > hi)
    run = 0
    for o in out:
        run = run + 1 if o else 0
        if run >= n:
            return True
    return False


def run_masked(run, meas_col, valve_col, bands, onset=ONSET, window=WINDOW, n=PERSIST,
               settle=SETTLE) -> bool:
    """The rule for one loop on one run (samples x all columns): the measurement is held
    and the valve absorbs, within samples onset + settle + 1 .. onset + window (the
    settled half by default). A run of consecutive samples outside the band counts only
    from onset + settle + 1 on."""
    if not 0 <= settle < window:
        raise ValueError(f"settle ({settle}) must be in 0 .. window - 1 ({window - 1})")
    if len(run) < onset + window:
        raise ValueError(f"the run has {len(run)} samples; the window needs {onset + window}")
    w = slice(onset + settle, onset + window)
    held = not outside_for(run[w, meas_col], *bands[meas_col], n)
    absorbed = outside_for(run[w, valve_col], *bands[valve_col], n)
    return held and absorbed


def loop_columns(columns, loops):
    """{loop id: (measurement column, end-valve column)} for one set of raw columns."""
    ids = list(loops)
    meas = tagmap.column_indices(columns, [loops[i].controlled for i in ids])
    valves = tagmap.column_indices(columns, [loop_map.end_valve(loops, i) for i in ids])
    return {i: (m, v) for i, m, v in zip(ids, meas, valves)}


def shares(runs, cols, bands, onset=ONSET) -> dict:
    """{loop id: share of runs the rule calls masked for that loop}."""
    return {i: float(np.mean([run_masked(r, m, v, bands, onset) for r in runs]))
            for i, (m, v) in cols.items()}


def verdict(loop_shares, threshold=MASKED_SHARE) -> list:
    """The loops that mask a fault: share >= threshold, in loop-map order."""
    return [i for i, s in loop_shares.items() if s >= threshold]


def run(*, allow_dirty=False, repo_root=None):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    loops = loop_map.load()
    chosen = selection.load(repo_root)

    calib = loader.load_normal("calibration")
    cols = loop_columns(calib.columns, loops)
    needed = sorted({c for pair in cols.values() for c in pair})
    cal_runs = [calib.runs[k] for k in sorted(calib.runs)]
    bands = normal_bands(cal_runs, needed)
    normal_shares = shares(cal_runs, cols, bands)
    normal_any = float(np.mean([any(run_masked(r, m, v, bands) for m, v in cols.values())
                                for r in cal_runs]))
    del calib, cal_runs

    per_fault, masked = {}, {}
    for f in FAULTS:
        faulty = loader.load_faulty(f, "forest_ceiling")
        missing = [k for k in chosen["numbers"] if k not in faulty.runs]
        if missing:
            raise MaskedError(f"selection runs {missing[:5]} missing for fault {f}")
        f_cols = loop_columns(faulty.columns, loops)
        if f_cols != cols:
            raise MaskedError(f"fault {f}'s columns don't match the calibration pool's")
        s = shares([faulty.runs[k] for k in chosen["numbers"]], cols, bands)
        by = verdict(s)
        per_fault[f"fault_{f:02d}"] = {"masked": bool(by), "by": ", ".join(by) if by else None,
                                       "max_share": max(s.values()), "shares": s}
        if by:
            masked[f] = by

    record = run_record.write(
        "masked_faults",
        config={"band_percentiles": list(BAND), "persist": PERSIST, "masked_share": MASKED_SHARE,
                "onset": ONSET, "window": WINDOW, "judged_samples": [ONSET + SETTLE + 1, ONSET + WINDOW],
                "warmup": WARMUP, "faults": list(FAULTS),
                "selection_runs": len(chosen["numbers"]), "loops": len(loops),
                "loop_map_sha256": run_record.sha256(loop_map.LOOPS_FILE)},
        seeds={"selection": chosen["seed"]},
        metrics={"masked_faults": sorted(masked), "faults": per_fault,
                 "normal_calibration": {"any_loop": normal_any, "max_loop": max(normal_shares.values()),
                                        "shares": normal_shares}},
        outputs={}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"{len(chosen['numbers'])} selection runs x {len(FAULTS)} faults; {len(loops)} loops; "
          f"band {BAND[0]}-{BAND[1]}th percentile, {PERSIST} consecutive samples in samples "
          f"{ONSET + SETTLE + 1}-{ONSET + WINDOW}, masked at >= {MASKED_SHARE:.0%} of runs")
    for f, by in masked.items():
        print(f"masked: fault {f} by {', '.join(by)}")
    if not masked:
        print("masked: none")
    print(f"normal calibration runs the rule would call masked (any loop): {normal_any:.3f}")
    print(f"run record: {record}")
    return per_fault


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(allow_dirty=args.allow_dirty)
    except (ValueError, loader.LoaderError, run_record.RunRecordError, selection.SelectionError,
            loop_map.LoopMapError, MaskedError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())