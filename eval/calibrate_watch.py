"""Calibrate the Watch band: one shared percentile p, each group's W_g and each tag's W_i
(decisions 64-66).

    python -m eval.calibrate_watch [--model data/models/pca_static.npz]
                                   [--limits data/models/pca_static_limits.json]
                                   [--out data/models/pca_static_watch.json] [--allow-dirty]

Steps:
1. The limits file must come from one calibrate_pca run record and match the model.
   Static PCA only: RBC isn't built for DPCA (decision 64).
2. M = rbc.index_matrix(model, T²lim, SPElim). Groups are the register's equipment groups
   over the model's tags (app/detector/groups.py).
3. Score the calibration pool once: whole-run group RBC and tag RBC.
4. p = calibrate.watch_limit on the group RBC: the lowest stable grid value with at most
   2% of the calibration pool's scored samples having any group in Watch. None stops here.
5. W_g and W_i = calibrate.watch_limits_at at p, on the group RBC and the tag RBC. W_i sets
   no band; it only normalises the top-tags ranking (decision 65).
6. Write the watch file and a calibrate_watch run record: p, whether it's the grid floor,
   every W_g and W_i, and the any-group and per-group Watch shares on the calibration pool.

Never loads dev or faulty runs. Refuses a dirty tree unless --allow-dirty. Prints only
counts, p, the shares and the record's path.
"""

import argparse
import json
import sys
from pathlib import Path

from app.detector import groups as groups_mod
from app.detector import pca, rbc
from dataset import loader
from eval import calibrate as cal
from eval import calibrate_driver as drv
from eval import check_dev, run_record
from ingest import tags as tagmap

DEFAULT_OUT = drv.DEFAULT_OUT.parent / "pca_static_watch.json"


def load_pair(limits_path, model_path, repo_root):
    """(calibration record path, limits, model) for a static PCA limits file and its model.
    Reads no run data."""
    cal_record = check_dev.calibration_record_for(limits_path, repo_root)
    lim = json.loads(Path(limits_path).read_text())
    if lim["lags"] != 0:
        raise drv.CalibrationError(f"RBC isn't built for DPCA (decision 64); these limits have "
                                   f"{lim['lags']} lags")
    if run_record.sha256(model_path) != lim["model_sha256"]:
        raise drv.CalibrationError(f"{model_path} isn't the model these limits were calibrated for")
    return cal_record, lim, pca.load(model_path)


def rbc_runs(model, lim, runs, names):
    """({run number: group RBC}, {run number: tag RBC}) over whole runs (index 0 = sample 1),
    with groups in the order of names."""
    M = rbc.index_matrix(model, lim["t2_lim"], lim["spe_lim"])
    table = groups_mod.load(model.tags)
    cols = tagmap.column_indices(runs.columns, model.tags)
    group_cols = [table[g] for g in names]
    by_group, by_tag = {}, {}
    for k in sorted(runs.runs):
        X = runs.runs[k][:, cols]
        by_group[k] = rbc.group_rbc(model, M, X, group_cols)
        by_tag[k] = rbc.tag_rbc(model, M, X)
    return by_group, by_tag


def watch_record_for(watch_path, repo_root):
    """Path of the single calibrate_watch record whose watch output is this file."""
    sha = run_record.sha256(watch_path)
    matches = [p for p in sorted((Path(repo_root) / run_record.RUNS_DIR).glob("*_calibrate_watch.json"))
               if json.loads(p.read_text()).get("outputs", {}).get("watch", {}).get("sha256") == sha]
    if len(matches) != 1:
        raise drv.CalibrationError(f"expected one calibrate_watch record for {watch_path}, "
                                   f"found {len(matches)}")
    return matches[0]


def load_watch(watch_path, limits_path, model, repo_root):
    """(record path, watch file) for a watch file made from these limits and this model,
    with the model's current groups. Reads no run data."""
    record = watch_record_for(watch_path, repo_root)
    doc = json.loads(Path(watch_path).read_text())
    if doc["limits_sha256"] != run_record.sha256(limits_path):
        raise drv.CalibrationError(f"{watch_path} was calibrated for other limits")
    table = groups_mod.load(model.tags)
    if list(doc["groups"]) != list(table) or any(
            doc["groups"][g]["tags"] != [model.tags[i] for i in table[g]] for g in table):
        raise drv.CalibrationError(f"{watch_path}'s groups aren't the register's groups for this model")
    return record, doc


def run(model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT, out=DEFAULT_OUT, *,
        allow_dirty=False, repo_root=None, q_grid=cal.Q_GRID, cap=cal.WATCH_CAP):
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} already exists; delete it to recalibrate")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    cal_record, lim, model = load_pair(limits_path, model_path, repo_root)
    warmup = lim["warmup"]
    table = groups_mod.load(model.tags)
    names = list(table)

    runs = loader.load_normal("calibration")
    by_group, by_tag = rbc_runs(model, lim, runs, names)
    numbers = sorted(by_group)
    group_runs = [by_group[k] for k in numbers]
    tag_runs = [by_tag[k] for k in numbers]

    p = cal.watch_limit(group_runs, warmup, cap=cap, q_grid=q_grid)
    if p is None:
        raise drv.CalibrationError(f"no grid value keeps any-group Watch at or below {cap:.0%} "
                                   "of the calibration samples (decision 66)")
    w_group = cal.watch_limits_at(group_runs, p, warmup)
    w_tag = cal.watch_limits_at(tag_runs, p, warmup)
    any_share, per_group = cal.watch_shares(group_runs, w_group, warmup)

    doc = {"detector": lim["detector"], "model_sha256": lim["model_sha256"],
           "limits_sha256": run_record.sha256(limits_path), "warmup": warmup,
           "p": p, "cap": cap,
           "groups": {g: {"tags": [model.tags[i] for i in table[g]], "w": float(w)}
                      for g, w in zip(names, w_group)},
           "tags": {t: float(w) for t, w in zip(model.tags, w_tag)}}
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    scored = sum(len(r) - warmup for r in group_runs)
    record = run_record.write(
        "calibrate_watch",
        config={"detector": lim["detector"], "warmup": warmup, "cap": cap,
                "q_grid": {"first": q_grid[0], "last": q_grid[-1], "points": len(q_grid)},
                "calibration_runs": len(numbers),
                "calibration_record": cal_record.relative_to(repo_root).as_posix(),
                "limits_sha256": doc["limits_sha256"], "model_sha256": doc["model_sha256"],
                "groups": {g: len(table[g]) for g in names}},
        seeds={},
        metrics={"p": p, "at_floor": p == q_grid[0], "scored_samples": scored,
                 "w_group": {g: doc["groups"][g]["w"] for g in names},
                 "w_tag": doc["tags"],
                 "calibration": {"any_group_share": any_share,
                                 "group_shares": {g: float(s) for g, s in zip(names, per_group)}}},
        outputs={"watch": out}, commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"calibration pool: {len(numbers)} runs, {scored} scored samples; "
          f"{len(names)} groups, {len(model.tags)} tags")
    print(f"p = {p}{' (grid floor)' if p == q_grid[0] else ''}; any-group Watch share "
          f"{any_share:.4f} (cap {cap})")
    print("group shares: " + ", ".join(f"{g} {s:.4f}" for g, s in zip(names, per_group)))
    print(f"saved {out}\nrun record: {record}")
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.model, args.limits, args.out, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError,
            run_record.RunRecordError, drv.CalibrationError, groups_mod.GroupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())