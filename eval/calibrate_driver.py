"""Calibrate the static PCA detector: limit, persistence and grouping (decisions 53-55).

    python -m eval.calibrate_driver [--model data/models/pca_static.npz]
                                    [--out data/models/pca_static_limits.json] [--allow-dirty]

Steps:
1. Find the model's fit record in eval/runs/ by the model's SHA-256, and take the
   warm-up from it (so calibration can't use a different warm-up from the fit).
2. Score the calibration pool once (T² and SPE per run, whole runs).
3. For every (n, G): q = calibrate.lowest_stable_q on the calibration pool.
4. Score the selection runs (dataset/selection.yaml, forest-ceiling numbers) of the
   selection faults once; for every eligible (n, G), the mean detection rate at its q.
5. calibrate.choose picks (n, G, q). Write the limits file and a run record listing every
   setting's q, score, whether q is at the grid floor, and its share of the budget
   (decision 55).

Never loads dev (normal or faulty). Refuses a dirty tree unless --allow-dirty. Prints
only counts, the chosen setting and the record's path.
"""

import argparse
import functools
import json
import sys
from pathlib import Path

from app.detector import alerting, pca
from dataset import loader, selection
from eval import calibrate as cal
from eval import fit_pca, metrics, run_record
from ingest import tags as tagmap

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = fit_pca.DEFAULT_OUT
DEFAULT_OUT = REPO_ROOT / "data" / "models" / "pca_static_limits.json"
DETECTOR = "pca_static"
LAGS = 0                                    # static PCA has no lags


class CalibrationError(RuntimeError):
    pass


def fit_record_for(model_path, repo_root):
    """(path, record) of the single fit_pca record whose model output has this file's
    SHA-256. Refuses when there is none or more than one."""
    sha = run_record.sha256(model_path)
    matches = []
    for p in sorted((Path(repo_root) / run_record.RUNS_DIR).glob("*_fit_pca.json")):
        rec = json.loads(p.read_text())
        if rec.get("outputs", {}).get("model", {}).get("sha256") == sha:
            matches.append((p, rec))
    if len(matches) != 1:
        raise CalibrationError(f"expected one fit_pca record for {model_path} "
                               f"(sha256 {sha[:12]}…), found {len(matches)}")
    return matches[0]


def score_runs(model, runs, numbers=None):
    """{run number: (T², SPE)} over whole runs, columns in the model's tag order."""
    cols = tagmap.column_indices(runs.columns, model.tags)
    numbers = sorted(runs.runs) if numbers is None else numbers
    missing = [k for k in numbers if k not in runs.runs]
    if missing:
        raise CalibrationError(f"run numbers {missing[:5]} aren't in {runs.pool} for fault {runs.fault}")
    return {k: pca.scores(model, runs.runs[k][:, cols]) for k in numbers}


def tracks(scored, limits, n, gap, warmup):
    """Alert tracks for every scored run at these limits."""
    return {k: alerting.alert_track(alerting.plant_ratio(t2, spe, *limits), n, gap, warmup, LAGS)
            for k, (t2, spe) in scored.items()}


def run(model_path=DEFAULT_MODEL, out=DEFAULT_OUT, *, allow_dirty=False, repo_root=None,
        q_grid=cal.Q_GRID, gap_range=cal.GAP_RANGE):
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} already exists; delete it to recalibrate")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    fit_path, fit = fit_record_for(model_path, repo_root)
    warmup = fit["config"]["warmup"]
    model = pca.load(model_path)
    chosen_selection = selection.load(repo_root)

    # 2-3. Calibration pool: the limits per q are cached; ratios are rebuilt per step.
    cal_scored = score_runs(model, loader.load_normal("calibration"))
    numbers = sorted(cal_scored)
    t2_runs = [cal_scored[k][0] for k in numbers]
    spe_runs = [cal_scored[k][1] for k in numbers]
    limits = functools.cache(lambda q: cal.limits_at(t2_runs, spe_runs, q, warmup))

    def ratio_runs_at(q):
        return {k: alerting.plant_ratio(t2, spe, *limits(q)) for k, (t2, spe) in cal_scored.items()}

    def budget(q, n, gap):
        runs = [metrics.ScoredRun(0, k, a) for k, a in tracks(cal_scored, limits(q), n, gap, warmup).items()]
        return metrics.false_alerts_per_24h(runs, warmup)

    settings = {}
    for n in cal.n_range(LAGS, warmup):
        for gap in gap_range:
            settings[(n, gap)] = cal.lowest_stable_q(ratio_runs_at, n, gap, warmup, LAGS, q_grid)

    # 4. Selection runs, scored once.
    sel_scored = {f: score_runs(model, loader.load_faulty(f, "forest_ceiling"),
                                chosen_selection["numbers"])
                  for f in cal.SELECTION_FAULTS}

    def fault_tracks(q, n, gap):
        return {f: list(tracks(s, limits(q), n, gap, warmup).values()) for f, s in sel_scored.items()}

    candidates, table = {}, {}
    for (n, gap), q in settings.items():
        row = {"q": q, "score": None, "at_floor": None, "budget_share": None}
        if q is not None:
            score = cal.selection_score(fault_tracks(q, n, gap), warmup)
            candidates[(n, gap)] = (q, score)
            row.update(score=score, at_floor=q == q_grid[0],
                       budget_share=budget(q, n, gap)[2] / cal.BUDGET_PER_24H)
        else:
            candidates[(n, gap)] = (None, 0.0)
        table[f"n{n}_g{gap}"] = row

    # 5. Choose, write, record.
    n, gap, q = cal.choose(candidates)
    t2_lim, spe_lim = limits(q)
    count, hours, per_24h = budget(q, n, gap)
    rates = {f"fault_{f:02d}": sum(metrics.detection(t, metrics.TRAIN_ONSET, warmup=warmup).detected
                                   for t in ts) / len(ts)
             for f, ts in fault_tracks(q, n, gap).items()}
    limits_doc = {"detector": DETECTOR, "model_sha256": run_record.sha256(model_path),
                  "warmup": warmup, "lags": LAGS, "n": n, "gap": gap, "q": q,
                  "t2_lim": t2_lim, "spe_lim": spe_lim}
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x") as f:
        json.dump(limits_doc, f, indent=2)
        f.write("\n")
    record = run_record.write(
        "calibrate_pca",
        config={"detector": DETECTOR, "warmup": warmup, "lags": LAGS,
                "q_grid": {"first": q_grid[0], "last": q_grid[-1], "points": len(q_grid)},
                "n_range": list(cal.n_range(LAGS, warmup)), "gap_range": list(gap_range),
                "budget_per_24h": cal.BUDGET_PER_24H,
                "selection_faults": list(cal.SELECTION_FAULTS),
                "selection_runs": len(chosen_selection["numbers"]),
                "calibration_runs": len(numbers),
                "fit_record": fit_path.relative_to(repo_root).as_posix(),
                "model_sha256": limits_doc["model_sha256"]},
        seeds={"selection": chosen_selection["seed"]},
        metrics={"chosen": {"n": n, "gap": gap, "q": q, "t2_lim": t2_lim, "spe_lim": spe_lim,
                            "score": candidates[(n, gap)][1], "at_floor": q == q_grid[0]},
                 "calibration": {"notifications": count, "hours": hours, "per_24h": per_24h,
                                 "budget_share": per_24h / cal.BUDGET_PER_24H},
                 "selection_rates": rates,
                 "eligible_settings": sum(q is not None for q in settings.values()),
                 "settings": table},
        outputs={"limits": out}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"calibration pool: {len(numbers)} runs; selection: {len(chosen_selection['numbers'])} "
          f"runs x {len(cal.SELECTION_FAULTS)} faults; warm-up {warmup}")
    print(f"eligible settings: {sum(q is not None for q in settings.values())} of {len(settings)}")
    print(f"chosen: n = {n}, G = {gap}, q = {q}{' (grid floor)' if q == q_grid[0] else ''}")
    print(f"saved {out}\nrun record: {record}")
    return limits_doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.model, args.out, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError,
            run_record.RunRecordError, selection.SelectionError, CalibrationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())