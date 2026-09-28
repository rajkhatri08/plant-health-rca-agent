"""The masked-fault list (decision 62; PROTOCOL, Loops).

    python -m eval.masked [--allow-dirty]

Everything is judged on the settled half of the 4 h after onset, samples onset + 41 ..
onset + 80 (2 to 4 h): compensation is what the loops leave behind once they have acted,
so an onset transient doesn't count. A tag is "out" when it is outside its normal band
for PERSIST consecutive samples in that half. The normal band of a tag is the central
99% of the calibration pool's scored samples (0.5th to 99.5th percentile, pooled, after
the warm-up); the band's edges count as inside.

The label (plant level). A run is masked when no measurement or analyzer in the register
is out, while at least one valve is: the plant looks normal and only the valves show the
fault. A fault is masked when at least MASKED_SHARE of its selection runs are. Its
absorbing valves are the valves out in at least MASKED_SHARE of its masked runs (or, if
none reaches that, the most frequent ones).

Diagnosis evidence (per loop, library/loops.yaml). A loop absorbs the fault on a run
when its controlled measurement is held (not out) and its end valve (a cascade master's
is the valve at the bottom of its cascade) is out. For a proportional-only loop, "held"
means inside the band, not at the setpoint. A loop absorbs a fault when it does on at
least MASKED_SHARE of the runs. This says which loops compensated; it isn't the label,
because one loop (the recycle-flow loop) absorbs nearly every plant-wide disturbance,
visible or not (the superseded any-loop rule, eval/runs/20260928T154511Z_masked_faults.json).

Decided on the 100 selection runs (dataset/selection.yaml, forest-ceiling numbers), never
on dev, so dev stays an independent check. This labels faults for reporting; it isn't a
detector, so it may look ahead within the window. Nothing it produces reaches app/ or
library/.

Writes a masked_faults run record: per fault, the plant-level share and verdict, the
absorbing valves, each valve's share of the masked runs, and the per-loop shares; also,
as a sanity figure, the share of calibration runs (normal, fake onset at sample 20, the
same half-window, in-sample for the bands) the plant-level rule calls masked, and the
per-loop shares there. Prints only the masked list and the record's path. Never loads dev.
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
RULE = "plant"                              # the label's rule (decision 62, amended)
HELD_KINDS = ("measurement", "analyzer")    # must all stay in their bands
VALVE_KIND = "valve"                        # at least one must be out


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


def _judged(run, onset, window, settle):
    """The slice of samples onset + settle + 1 .. onset + window, after checks."""
    if not 0 <= settle < window:
        raise ValueError(f"settle ({settle}) must be in 0 .. window - 1 ({window - 1})")
    if len(run) < onset + window:
        raise ValueError(f"the run has {len(run)} samples; the window needs {onset + window}")
    return slice(onset + settle, onset + window)


def plant_masked(run, held_cols, valve_cols, bands, onset=ONSET, window=WINDOW, n=PERSIST,
                 settle=SETTLE) -> tuple[bool, list]:
    """The label's rule on one run (samples x all columns): (masked, valve columns out).
    masked when no held column (every measurement and analyzer) is out and at least one
    valve column is, within samples onset + settle + 1 .. onset + window. A run of
    consecutive samples outside the band counts only from onset + settle + 1 on."""
    w = _judged(run, onset, window, settle)
    if any(outside_for(run[w, c], *bands[c], n) for c in held_cols):
        return False, []
    out = [c for c in valve_cols if outside_for(run[w, c], *bands[c], n)]
    return bool(out), out


def absorbing_valves(out_lists, names, threshold=MASKED_SHARE) -> tuple[list, dict]:
    """(absorbing valve names, {valve name: share of masked runs it was out in}).
    out_lists holds, for each masked run, the valve columns that were out; names maps a
    column to its tag. Absorbing: out in at least threshold of the masked runs, or, if
    none reaches it, the most frequent (ties included). Both empty without masked runs."""
    if not out_lists:
        return [], {}
    counts = {}
    for out in out_lists:
        for c in out:
            counts[names[c]] = counts.get(names[c], 0) + 1
    share = {v: counts[v] / len(out_lists) for v in sorted(counts)}
    top = [v for v, s in share.items() if s >= threshold]
    if not top:
        best = max(share.values())
        top = [v for v, s in share.items() if s == best]
    return top, share


def run_masked(run, meas_col, valve_col, bands, onset=ONSET, window=WINDOW, n=PERSIST,
               settle=SETTLE) -> bool:
    """Diagnosis evidence for one loop on one run (samples x all columns): its
    measurement is held and its end valve is out, within samples onset + settle + 1 ..
    onset + window (the settled half by default)."""
    w = _judged(run, onset, window, settle)
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
    """The loops that absorb a fault: share >= threshold, in loop-map order."""
    return [i for i, s in loop_shares.items() if s >= threshold]


def plant_columns(columns) -> tuple[list, dict]:
    """(held columns: every measurement and analyzer in the register, {valve column:
    valve tag}) for one set of raw columns."""
    rows = tagmap.register()
    held = [r["tag"] for r in rows if r["kind"] in HELD_KINDS]
    valves = [r["tag"] for r in rows if r["kind"] == VALVE_KIND]
    held_cols = tagmap.column_indices(columns, held)
    valve_cols = tagmap.column_indices(columns, valves)
    return held_cols, dict(zip(valve_cols, valves))


def run(*, allow_dirty=False, repo_root=None):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    loops = loop_map.load()
    chosen = selection.load(repo_root)

    calib = loader.load_normal("calibration")
    cols = loop_columns(calib.columns, loops)
    held_cols, valve_names = plant_columns(calib.columns)
    needed = sorted(set(held_cols) | set(valve_names) | {c for pair in cols.values() for c in pair})
    cal_runs = [calib.runs[k] for k in sorted(calib.runs)]
    bands = normal_bands(cal_runs, needed)
    normal_plant = float(np.mean([plant_masked(r, held_cols, valve_names, bands)[0] for r in cal_runs]))
    normal_loops = shares(cal_runs, cols, bands)
    del calib, cal_runs

    per_fault, masked = {}, {}
    for f in FAULTS:
        faulty = loader.load_faulty(f, "forest_ceiling")
        missing = [k for k in chosen["numbers"] if k not in faulty.runs]
        if missing:
            raise MaskedError(f"selection runs {missing[:5]} missing for fault {f}")
        if loop_columns(faulty.columns, loops) != cols or plant_columns(faulty.columns) != (held_cols, valve_names):
            raise MaskedError(f"fault {f}'s columns don't match the calibration pool's")
        runs = [faulty.runs[k] for k in chosen["numbers"]]
        results = [plant_masked(r, held_cols, valve_names, bands) for r in runs]
        share = float(np.mean([m for m, _ in results]))
        is_masked = share >= MASKED_SHARE
        valves, valve_shares = absorbing_valves([out for m, out in results if m], valve_names)
        loop_shares = shares(runs, cols, bands)
        absorbing_loops = verdict(loop_shares)
        per_fault[f"fault_{f:02d}"] = {
            "masked": is_masked,
            "masked_share": share,
            "absorbing_valves": ", ".join(valves) if is_masked and valves else None,
            "valve_shares": valve_shares,
            "absorbing_loops": ", ".join(absorbing_loops) if absorbing_loops else None,
            "loop_shares": loop_shares,
        }
        if is_masked:
            masked[f] = valves

    record = run_record.write(
        "masked_faults",
        config={"rule": RULE, "band_percentiles": list(BAND), "persist": PERSIST,
                "masked_share": MASKED_SHARE, "onset": ONSET, "window": WINDOW,
                "judged_samples": [ONSET + SETTLE + 1, ONSET + WINDOW], "warmup": WARMUP,
                "faults": list(FAULTS), "selection_runs": len(chosen["numbers"]),
                "held_tags": len(held_cols), "valves": len(valve_names), "loops": len(loops),
                "loop_map_sha256": run_record.sha256(loop_map.LOOPS_FILE)},
        seeds={"selection": chosen["seed"]},
        metrics={"masked_faults": sorted(masked), "faults": per_fault,
                 "normal_calibration": {"plant": normal_plant,
                                        "max_loop": max(normal_loops.values()),
                                        "loop_shares": normal_loops}},
        outputs={}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"{len(chosen['numbers'])} selection runs x {len(FAULTS)} faults; {len(held_cols)} held tags, "
          f"{len(valve_names)} valves; band {BAND[0]}-{BAND[1]}th percentile, {PERSIST} consecutive "
          f"samples in samples {ONSET + SETTLE + 1}-{ONSET + WINDOW}, masked at >= {MASKED_SHARE:.0%} of runs")
    for f, valves in masked.items():
        print(f"masked: fault {f}, absorbed by {', '.join(valves)}")
    if not masked:
        print("masked: none")
    print(f"normal calibration runs the plant-level rule calls masked: {normal_plant:.3f}")
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