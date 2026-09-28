"""Per-fault detection table on dev (PROTOCOL, Detection metrics; decisions 49, 57).

    python -m eval.dev_table [--limits data/models/pca_static_limits.json]
                             [--model data/models/pca_static.npz] [--allow-dirty]

Scores the dev runs of open faults 1-15 and the normal dev runs with a calibrated
detector, through the same alert path as calibration (app/detector/alerting.py). Loads
nothing but dev: the loader has no path to the test split or to faults 16-20.

Per fault: detection rate, detections before divergence from the fault-free twin
(decision 57), median delay (IQR) and share still flagged. The chance rate and false
alerts per 24 h come from the normal dev runs (fake onset at sample 20). Each rate and
each median delay gets a 95% run-number bootstrap interval (B = 2000, percentile).
Every interval uses the same seed, so every statistic sees the same run-number draws
(rule 3). Summary: the mean rate over faults 1-15 except 3, 9 and 15, and the mean over
those three separately, each fault weighted equally.
Right place, Masked and Lead time read "—" until their sessions build them.

Writes a dev_table_<detector> run record holding every number, and a Markdown rendering
of that record to data/tables/ (gitignored). Prints only the paths and one summary line.
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.detector import pca
from dataset import loader
from eval import calibrate_driver as drv
from eval import check_dev, metrics, run_record
from ingest import tags as tagmap

BOOTSTRAP_SEED = 20261001
FAULTS = tuple(loader.OPEN_FAULTS)                     # 1..15; 16-20 are sealed
EXCLUDED = (3, 9, 15)                                  # near-undetectable, reported separately
SUMMARY_FAULTS = tuple(f for f in FAULTS if f not in EXCLUDED)
ONSET = metrics.TRAIN_ONSET                            # dev runs are training runs
FAMILIES = {1: "feed composition", 2: "feed composition", 8: "feed composition",
            6: "feed supply", 7: "feed supply", 10: "feed temperature",
            4: "reactor cooling", 11: "reactor cooling", 14: "reactor cooling",
            5: "condenser cooling", 12: "condenser cooling", 13: "reaction kinetics"}
PENDING = "—"                                          # a column not built yet
DEFAULT_TABLES = run_record.REPO_ROOT / "data" / "tables"


class DevTableError(RuntimeError):
    pass


def _ci(runs, value, stat, n_boot):
    """Bootstrap interval of stat over run numbers. value maps (fault, run number) to
    the per-run number stat needs. Every call starts from the same seed."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    return list(metrics.bootstrap_ci(runs, lambda rs: stat([value[(r.fault, r.run)] for r in rs]),
                                     rng, n=n_boot))


def _rate(flags):
    return sum(flags) / len(flags)


def _median(delays):
    return metrics.delay_summary(delays)[0]


def fault_row(fault, tracks, inputs, twins, warmup, n_boot):
    """(row, per-run detected flags) for one fault. tracks, inputs and twins are keyed
    by run number; inputs and twins hold only the detector's input columns (decision 57)."""
    numbers = sorted(tracks)
    runs = [metrics.ScoredRun(fault, k, tracks[k]) for k in numbers]
    det = {k: metrics.detection(tracks[k], ONSET, warmup=warmup) for k in numbers}
    div = {k: metrics.first_divergence(inputs[k], twins[k]) for k in numbers}
    early = [k for k in numbers if div[k] is not None and div[k] <= ONSET]
    if early:
        raise DevTableError(f"fault {fault}: runs {early[:5]} differ from their twins at or before "
                            f"sample {ONSET}; decision 49 says samples 1-{ONSET} are copies")
    detected = [k for k in numbers if det[k].detected]
    median, q1, q3 = metrics.delay_summary([det[k].delay_min for k in numbers])
    before, of = metrics.before_divergence_share([det[k] for k in numbers], [div[k] for k in numbers])
    flagged = [metrics.share_still_flagged(tracks[k], det[k].sample) for k in detected]
    hit = {(fault, k): det[k].detected for k in numbers}
    delay = {(fault, k): det[k].delay_min for k in numbers}
    row = {
        "family": FAMILIES.get(fault, PENDING),
        "runs": len(numbers),
        "detected": len(detected),
        "rate": len(detected) / len(numbers),
        "rate_ci95": _ci(runs, hit, _rate, n_boot),
        "before_divergence": before,
        "before_divergence_of": of,
        "delay_median_min": median,
        "delay_q1_min": q1,
        "delay_q3_min": q3,
        "delay_median_ci95": _ci(runs, delay, _median, n_boot),
        "share_still_flagged": float(np.mean(flagged)) if flagged else None,
        "share_still_flagged_runs": len(flagged),
    }
    return row, hit


def mean_rate(hit, faults, n_boot):
    """Mean detection rate over faults, each weighted equally, with a joint run-number
    bootstrap: a drawn number brings that run of every fault along (rule 3). Raises
    ValueError unless every fault has the same run numbers."""
    numbers = {f: sorted(k for (g, k) in hit if g == f) for f in faults}
    if any(numbers[f] != numbers[faults[0]] or not numbers[f] for f in faults):
        raise ValueError("every fault needs the same, non-empty set of run numbers")
    runs = [metrics.ScoredRun(f, k, None) for (f, k) in hit if f in faults]

    def stat(rs):
        by_fault = {}
        for r in rs:
            by_fault.setdefault(r.fault, []).append(hit[(r.fault, r.run)])
        return float(np.mean([_rate(by_fault[f]) for f in faults]))

    point = stat(runs)
    low, high = metrics.bootstrap_ci(runs, stat, np.random.default_rng(BOOTSTRAP_SEED), n=n_boot)
    return {"faults": list(faults), "rate": point, "rate_ci95": [low, high]}


def normal_row(tracks, warmup, n_boot):
    """False alerts per 24 h and the chance rate on the normal dev runs (rule 4)."""
    runs = [metrics.ScoredRun(0, k, tracks[k]) for k in sorted(tracks)]
    count, hours, per_24h = metrics.false_alerts_per_24h(runs, warmup)
    per_run = {(0, r.run): metrics.false_alerts_per_24h([r], warmup)[:2] for r in runs}
    lucky = {(0, r.run): metrics.chance_rate([r], ONSET, warmup=warmup) == 1.0 for r in runs}

    def rate_24h(pairs):                     # pooled count over pooled hours, as the metric
        return sum(c for c, _ in pairs) / sum(h for _, h in pairs) * 24

    return {
        "runs": len(runs),
        "notifications": count,
        "hours": hours,
        "per_24h": per_24h,
        "per_24h_ci95": _ci(runs, per_run, rate_24h, n_boot),
        "chance_rate": metrics.chance_rate(runs, ONSET, warmup=warmup),
        "chance_rate_ci95": _ci(runs, lucky, _rate, n_boot),
    }


def _num(v, digits=2):
    if v is None:
        return PENDING
    if v in ("inf", math.inf):
        return "∞"
    return f"{v:.{digits}f}"


def _minutes(v):
    return "∞" if v in ("inf", math.inf) else f"{v:g}"


def render(record, record_path):
    """The Markdown table, built only from a run record (as saved) and its repo path."""
    cfg, m = record["config"], record["metrics"]
    nrm = m["normal"]
    chance = f"{_num(nrm['chance_rate'])} ({_num(nrm['chance_rate_ci95'][0])}–{_num(nrm['chance_rate_ci95'][1])})"
    lines = [
        f"# Dev detection table: {cfg['detector']}",
        "",
        f"Run record `{record_path}`, commit {record['commit'][:12]}"
        f"{' (dirty)' if record['dirty'] else ''}. Dev pool, {nrm['runs']} run numbers; "
        f"n = {cfg['n']}, G = {cfg['gap']}, q = {cfg['q']}, warm-up {cfg['warmup']}. "
        f"Intervals: 95% run-number bootstrap, B = {cfg['bootstrap']['resamples']}, "
        f"seed {record['seeds']['bootstrap']}.",
        "",
        "| Fault | Family | Masked | Detected (any / right place) | Chance rate | "
        "Detected before divergence | Median delay, min (IQR) | Share still flagged | "
        "Lead time vs grouped alarms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for f in FAULTS:
        r = m["faults"][f"fault_{f:02d}"]
        lo, hi = r["rate_ci95"]
        dlo, dhi = r["delay_median_ci95"]
        lines.append(
            f"| {f}{' (excluded)' if f in EXCLUDED else ''} | {r['family']} | {PENDING} | "
            f"{_num(r['rate'])} ({_num(lo)}–{_num(hi)}) / {PENDING} | {chance} | "
            f"{r['before_divergence']} of {r['before_divergence_of']} | "
            f"{_minutes(r['delay_median_min'])} ({_minutes(r['delay_q1_min'])}–{_minutes(r['delay_q3_min'])}); "
            f"median interval {_minutes(dlo)}–{_minutes(dhi)} | "
            f"{_num(r['share_still_flagged'])} ({r['share_still_flagged_runs']} runs) | {PENDING} |")
    for key, label in (("summary", "Mean, faults 1–15 except 3, 9, 15"),
                       ("excluded", "Mean, faults 3, 9, 15")):
        s = m[key]
        lines.append(f"| {label} | | | {_num(s['rate'])} ({_num(s['rate_ci95'][0])}–"
                     f"{_num(s['rate_ci95'][1])}) / {PENDING} | {chance} | | | | |")
    lo, hi = nrm["per_24h_ci95"]
    lines.append(f"| Normal operation | | | false alerts per 24 h: {_num(nrm['per_24h'], 3)} "
                 f"({_num(lo, 3)}–{_num(hi, 3)}), {nrm['notifications']} in "
                 f"{_num(nrm['hours'], 1)} h | | | | | |")
    return "\n".join(lines) + "\n"


def run(limits_path=drv.DEFAULT_OUT, model_path=drv.DEFAULT_MODEL, *, allow_dirty=False,
        repo_root=None, tables_dir=None, n_boot=metrics.BOOTSTRAP_N):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    tables_dir = Path(tables_dir or DEFAULT_TABLES)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    cal_record = check_dev.calibration_record_for(limits_path, repo_root)
    lim = json.loads(Path(limits_path).read_text())
    if run_record.sha256(model_path) != lim["model_sha256"]:
        raise drv.CalibrationError(f"{model_path} isn't the model these limits were calibrated for")
    if lim["lags"] != 0:
        raise DevTableError(f"lagged scoring (lags = {lim['lags']}) isn't built yet (week 3 session 8)")
    detector, warmup = lim["detector"], lim["warmup"]
    now = datetime.now(timezone.utc)
    table_path = tables_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_dev_table_{detector}.md"
    if table_path.exists():
        raise FileExistsError(f"{table_path} already exists")
    model = pca.load(model_path)
    limits = (lim["t2_lim"], lim["spe_lim"])

    normal = loader.load_normal("dev")
    cols = tagmap.column_indices(normal.columns, model.tags)          # the detector's inputs
    normal_tracks = drv.tracks(drv.score_runs(model, normal), limits, lim["n"], lim["gap"], warmup)
    rows, hit = {}, {}
    for f in FAULTS:
        faulty = loader.load_faulty(f, "dev")
        if sorted(faulty.runs) != sorted(normal.runs):
            raise DevTableError(f"fault {f}'s dev run numbers aren't the normal dev numbers")
        tracks = drv.tracks(drv.score_runs(model, faulty), limits, lim["n"], lim["gap"], warmup)
        inputs = {k: faulty.runs[k][:, cols] for k in tracks}
        twins = {k: normal.runs[k][:, cols] for k in tracks}
        rows[f"fault_{f:02d}"], fault_hit = fault_row(f, tracks, inputs, twins, warmup, n_boot)
        hit.update(fault_hit)

    results = {"faults": rows,
               "summary": mean_rate(hit, SUMMARY_FAULTS, n_boot),
               "excluded": mean_rate(hit, EXCLUDED, n_boot),
               "normal": normal_row(normal_tracks, warmup, n_boot)}
    config = {"detector": detector, "pool": "dev", "warmup": warmup, "lags": lim["lags"],
              "n": lim["n"], "gap": lim["gap"], "q": lim["q"], "onset": ONSET,
              "window": metrics.WINDOW_SAMPLES, "faults": list(FAULTS),
              "summary_faults": list(SUMMARY_FAULTS),
              "calibration_record": cal_record.relative_to(repo_root).as_posix(),
              "limits_sha256": run_record.sha256(limits_path),
              "model_sha256": lim["model_sha256"],
              "bootstrap": {"resamples": n_boot, "level": 0.95, "method": "percentile"}}
    seeds = {"bootstrap": BOOTSTRAP_SEED}

    # The table is rendered from the values exactly as the record stores them, then the
    # record is written with the table's checksum. Both share one timestamp.
    name = f"dev_table_{detector}"
    record_rel = (run_record.RUNS_DIR / f"{now.strftime('%Y%m%dT%H%M%SZ')}_{name}.json").as_posix()
    stored = {"commit": commit, "dirty": dirty, "config": run_record.clean_metrics(config),
              "seeds": run_record.clean_metrics(seeds), "metrics": run_record.clean_metrics(results)}
    tables_dir.mkdir(parents=True, exist_ok=True)
    with open(table_path, "x") as fh:
        fh.write(render(stored, record_rel))
    record = run_record.write(name, config=config, seeds=seeds, metrics=results,
                              outputs={"table": table_path}, commit=commit, dirty=dirty,
                              repo_root=repo_root, now=now)
    if Path(record) != repo_root / record_rel:
        raise DevTableError(f"the table names {record_rel}, but the record is {record}")
    s = results["summary"]
    print(f"dev: {len(normal.runs)} run numbers x {len(FAULTS)} faults; detector {detector}")
    print(f"mean detection, faults 1-15 except 3, 9, 15: {s['rate']:.3f} "
          f"(95% interval {s['rate_ci95'][0]:.3f} to {s['rate_ci95'][1]:.3f})")
    print(f"table: {table_path}\nrun record: {record}")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.limits, args.model, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError,
            run_record.RunRecordError, drv.CalibrationError, DevTableError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())