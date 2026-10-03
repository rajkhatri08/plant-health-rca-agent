"""Cost check for case building (week 5, S6): how long `python -m eval.cases
forest_ceiling` will take for all 12 known faults, timed on a small batch first.

    python -m eval.time_cases [--fault 1] [--runs 20] [--model …] [--limits …] [--watch …] [--normals …]

Loads one fault's forest_ceiling pool (the loader reads the whole pool), then scores the
first --runs run numbers through the same path as eval/cases.py (cases.score_pool). It
times the inputs, the load and the scoring separately and projects the full build:

    12 x (load + 445 x seconds per run)        plus the inputs once

Builder side, timings only: it writes nothing (no case files, no run record; a cost
estimate isn't a reported result) and prints only seconds and counts, never values. It
reads only forest_ceiling runs of a known fault. The projection assumes every fault's
pool loads as fast as this one and that detected and missed runs cost about the same
(missed runs skip the features, so it errs high when many are missed).
"""

import argparse
import sys
import time
from pathlib import Path

from dataset import loader
from dataset.loader import Runs
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import cases, evidence_normals, run_record

POOL = "forest_ceiling"
FULL_RUNS = 445                         # forest_ceiling numbers (dataset/splits.yaml)
DEFAULT_RUNS = 20


def project(t_inputs, t_load, t_score, n_scored, faults=len(cases.KNOWN_FAULTS), full_runs=FULL_RUNS) -> dict:
    """Seconds per run and the projected total for the full build, in seconds."""
    if n_scored < 1:
        raise cases.CasesError("nothing was scored, so there's nothing to project from")
    per_run = t_score / n_scored
    return {"per_run_s": per_run, "per_fault_s": t_load + full_runs * per_run,
            "total_s": t_inputs + faults * (t_load + full_runs * per_run)}


def run(fault=1, n_runs=DEFAULT_RUNS, model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT,
        watch_path=cw.DEFAULT_OUT, normals_path=evidence_normals.DEFAULT_OUT, *, repo_root=None,
        clock=time.perf_counter):
    cases.check_request(POOL, (fault,))
    if n_runs < 1:
        raise cases.CasesError("--runs must be at least 1")
    repo_root = Path(repo_root or run_record.REPO_ROOT)

    t0 = clock()
    inp = cases.load_inputs(model_path, limits_path, watch_path, normals_path, repo_root)
    t1 = clock()
    pool = loader.load_faulty(fault, POOL)
    if pool.pool != POOL:
        raise cases.CasesError(f"asked for {POOL}, the loader gave {pool.pool}")
    t2 = clock()
    keep = sorted(pool.runs)[:n_runs]
    batch = Runs(pool.name, pool.fault, pool.pool, pool.columns, {k: pool.runs[k] for k in keep})
    per_run = cases.score_pool(inp, batch)
    t3 = clock()

    est = project(t1 - t0, t2 - t1, t3 - t2, len(keep))
    print(f"inputs {t1 - t0:.1f} s; load fault {fault} ({len(pool.runs)} runs) {t2 - t1:.1f} s; "
          f"scored {len(keep)} runs ({sum(r['detected'] for r in per_run)} detected) in {t3 - t2:.1f} s")
    print(f"{est['per_run_s']:.2f} s per run; about {est['per_fault_s'] / 60:.1f} min per fault; "
          f"projected {len(cases.KNOWN_FAULTS)} x {FULL_RUNS} runs: about {est['total_s'] / 60:.0f} min")
    return est


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fault", type=int, default=1)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--watch", type=Path, default=cw.DEFAULT_OUT)
    parser.add_argument("--normals", type=Path, default=evidence_normals.DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        run(args.fault, args.runs, args.model, args.limits, args.watch, args.normals)
    except (ValueError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, evidence_normals.NormalsError, cases.CasesError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())