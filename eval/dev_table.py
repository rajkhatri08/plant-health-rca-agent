"""Per-fault detection table on dev (PROTOCOL, Detection metrics and Alarm comparison;
decisions 49, 57, 58, 60).

    python -m eval.dev_table [--limits data/models/pca_static_limits.json]
                             [--model data/models/pca_static.npz]
                             [--lead-vs data/models/alarms_realistic_limits.json | --no-lead]
    python -m eval.dev_table --limits data/models/alarms_<list>_limits.json
                             --row grouped|ungrouped
    (either form: [--allow-dirty])

Scores the dev runs of open faults 1-15 and the normal dev runs with one calibrated
detector: App 3's PCA (through calibration's alert path, app/detector/alerting.py), or
one row of the conventional-alarm baseline (eval/baselines/alarms.py). The detector's
kind comes from its limits file, which must be the output of exactly one calibration
run record. Loads nothing but dev: the loader has no path to the test split or to
faults 16-20.

Per fault: detection rate, detections before divergence from the fault-free twin
(decision 57, on the detector's own input tags), median delay (IQR), share still
flagged, and the operator load in the 2-h notification window (decision 60):
notifications per episode, per 10 minutes, the peak 10-minute count, the flood share,
and chattering. For App 3, lead time against the realistic list's grouped alarm row
(decisions 58, 60). The chance rate and false alerts per 24 h come from the normal dev
runs (fake onset at sample 20). Each rate, median delay and median lead time gets a 95%
run-number bootstrap interval (B = 2000, percentile). Every interval uses the same seed,
so every statistic sees the same run-number draws (rule 3). Summary: the mean rate over
faults 1-15 except 3, 9 and 15, and the mean over those three separately, each fault
weighted equally. Right place and Masked read "—" until their sessions build them.

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
from eval.baselines import alarms as al
from ingest import tags as tagmap

BOOTSTRAP_SEED = 20261001
FAULTS = tuple(loader.OPEN_FAULTS)                     # 1..15; 16-20 are sealed
EXCLUDED = (3, 9, 15)                                  # near-undetectable, reported separately
SUMMARY_FAULTS = tuple(f for f in FAULTS if f not in EXCLUDED)
ONSET = metrics.TRAIN_ONSET                            # dev runs are training runs
FIRST, LAST = ONSET + 1, ONSET + metrics.NOTIFY_SAMPLES     # the notification window
FAMILIES = {1: "feed composition", 2: "feed composition", 8: "feed composition",
            6: "feed supply", 7: "feed supply", 10: "feed temperature",
            4: "reactor cooling", 11: "reactor cooling", 14: "reactor cooling",
            5: "condenser cooling", 12: "condenser cooling", 13: "reaction kinetics"}
PENDING = "—"                                          # a column not built yet
ROWS = ("grouped", "ungrouped")
LEAD_ROW = "grouped"                                   # lead time is against grouped alarms
LEAD_LIST = "realistic"                                # ... on the realistic list (decision 60)
DEFAULT_TABLES = run_record.REPO_ROOT / "data" / "tables"
DEFAULT_LEAD = run_record.REPO_ROOT / "data" / "models" / f"alarms_{LEAD_LIST}_limits.json"


class DevTableError(RuntimeError):
    pass


# ---------- detectors ----------

class PCADetector:
    """App 3's static PCA: one plant stream."""

    def __init__(self, lim, model):
        if lim["lags"] != 0:
            raise DevTableError(f"lagged scoring (lags = {lim['lags']}) isn't built yet (week 3 session 8)")
        self.name, self.warmup, self.lim, self.model = lim["detector"], lim["warmup"], lim, model
        self.input_tags = tuple(model.tags)
        self.config = {"n": lim["n"], "gap": lim["gap"], "q": lim["q"], "lags": lim["lags"],
                       "model_sha256": lim["model_sha256"]}

    def score(self, runs):
        """{run number: (alert track, [notification samples per point])}; one point."""
        tracks = drv.tracks(drv.score_runs(self.model, runs), (self.lim["t2_lim"], self.lim["spe_lim"]),
                            self.lim["n"], self.lim["gap"], self.warmup)
        return {k: (t, [metrics.notifications(t, self.warmup)]) for k, t in tracks.items()}


class AlarmDetector:
    """One row (grouped or ungrouped) of a conventional-alarm list (decision 58)."""

    def __init__(self, lim, row):
        if row not in ROWS:
            raise DevTableError(f"an alarm detector needs --row, one of {ROWS}; got {row!r}")
        self.list, self.row, self.warmup = lim["list"], row, lim["warmup"]
        self.name = f"{lim['detector']}_{row}"
        r = lim[row]
        self.n, self.gap = r["n"], r["gap"]
        self.lo, self.hi = np.array(r["lo"]), np.array(r["hi"])
        self.band = np.array(lim["band"])
        self.hl_tags, self.valve_tags = tuple(lim["hl_tags"]), tuple(lim["valve_tags"])
        self.input_tags = self.hl_tags + self.valve_tags
        hl = [al.ANALYZER_ON_DELAY if a else self.n for a in lim["hl_analyzer"]]
        self.on_delays = hl + hl + [self.n] * len(self.valve_tags)   # highs, lows, valves
        self.config = {"list": self.list, "row": row, "n": self.n, "gap": self.gap, "q": r["q"],
                       "lags": lim["lags"], "hl_tags": len(self.hl_tags),
                       "valve_at_limit": len(self.valve_tags)}

    def points(self, x_hl, x_valves):
        high, low = al.hysteresis(x_hl, self.lo, self.hi, self.band)
        return np.hstack([high, low] + ([al.at_limit(x_valves)] if self.valve_tags else []))

    def score(self, runs):
        hl_cols = tagmap.column_indices(runs.columns, self.hl_tags)
        v_cols = tagmap.column_indices(runs.columns, self.valve_tags) if self.valve_tags else []
        out = {}
        for k, x in runs.runs.items():
            pts = self.points(x[:, hl_cols], x[:, v_cols] if v_cols else None)
            per_point = al.point_tracks(pts, self.on_delays, self.gap, self.warmup)
            track = al.plant_track(pts, self.on_delays, self.gap, self.warmup)
            out[k] = (track, [metrics.notifications(per_point[:, j], self.warmup)
                              for j in range(per_point.shape[1])])
        return out


def _record_for(limits_path, repo_root, pattern):
    """The single run record matching pattern whose limits output is this file."""
    sha = run_record.sha256(limits_path)
    matches = [p for p in sorted((Path(repo_root) / run_record.RUNS_DIR).glob(pattern))
               if json.loads(p.read_text()).get("outputs", {}).get("limits", {}).get("sha256") == sha]
    if len(matches) != 1:
        raise DevTableError(f"expected one {pattern} record for {limits_path}, found {len(matches)}")
    return matches[0]


def load_detector(limits_path, model_path, row, repo_root):
    """(detector, calibration record path, limits SHA-256). Reads no run data."""
    lim = json.loads(Path(limits_path).read_text())
    if lim["detector"].startswith("alarms_"):
        record = _record_for(limits_path, repo_root, f"*_calibrate_{lim['detector']}.json")
        return AlarmDetector(lim, row), record, run_record.sha256(limits_path)
    if row is not None:
        raise DevTableError(f"--row is only for alarm detectors, not {lim['detector']}")
    record = check_dev.calibration_record_for(limits_path, repo_root)
    if run_record.sha256(model_path) != lim["model_sha256"]:
        raise drv.CalibrationError(f"{model_path} isn't the model these limits were calibrated for")
    return PCADetector(lim, pca.load(model_path)), record, run_record.sha256(limits_path)


# ---------- statistics ----------

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


def operator_load(per_point_by_run):
    """Decision 60's counts over one fault's runs, in the notification window.
    per_point_by_run maps a run number to that run's notification samples per point."""
    episodes, periods, chatter_points, chatter_notes, total = [], [], [], 0, 0
    for k in sorted(per_point_by_run):
        per_point = [[s for s in notes if FIRST <= s <= LAST] for notes in per_point_by_run[k]]
        pooled = sorted(s for notes in per_point for s in notes)
        counts = metrics.period_counts(pooled, ONSET)
        chattering = [metrics.is_chattering(notes, FIRST, LAST) for notes in per_point]
        episodes.append(len(pooled))
        periods.extend(counts)
        chatter_points.append(sum(chattering))
        chatter_notes += sum(len(notes) for notes, c in zip(per_point, chattering) if c)
        total += len(pooled)
    return {
        "per_episode_mean": float(np.mean(episodes)),
        "per_episode_max": max(episodes),
        "per_10min_mean": float(np.mean(periods)),
        "peak_10min": max(periods),
        "flood_share": sum(c > metrics.FLOOD_ABOVE for c in periods) / len(periods),
        "chattering_points_per_run": float(np.mean(chatter_points)),
        "chattering_share": chatter_notes / total if total else None,
    }


def lead_row(fault, app, base, n_boot):
    """Lead time of App 3 over the baseline for one fault (decisions 58, 60). app and
    base map run number to Detection. The interval resamples the both-detected runs."""
    numbers = sorted(app)
    lt = metrics.lead_time([app[k] for k in numbers], [base[k] for k in numbers])
    both = [k for k in numbers if app[k].detected and base[k].detected]
    ci = None
    if both:
        runs = [metrics.ScoredRun(fault, k, None) for k in both]
        pair = {(fault, k): (app[k], base[k]) for k in both}
        ci = _ci(runs, pair, lambda ps: metrics.lead_time([a for a, _ in ps], [b for _, b in ps]).median_min,
                 n_boot)
    return {"median_min": lt.median_min, "median_ci95": ci, "both": lt.both,
            "only_app": lt.only_app, "only_base": lt.only_base, "neither": lt.neither}


def fault_row(fault, tracks, inputs, twins, warmup, n_boot, per_point=None):
    """(row, per-run detections) for one fault. tracks, inputs and twins are keyed by
    run number; inputs and twins hold only the detector's input columns (decision 57).
    per_point, if given, maps run number to notification samples per alarm point."""
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
    if per_point is not None:
        row["load"] = operator_load(per_point)
    return row, det


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


# ---------- rendering ----------

def _num(v, digits=2):
    if v is None:
        return PENDING
    if v in ("inf", math.inf):
        return "∞"
    return f"{v:.{digits}f}"


def _minutes(v):
    if v is None:
        return PENDING
    return "∞" if v in ("inf", math.inf) else f"{v:g}"


def _lead(lead):
    if not lead:
        return PENDING
    ci = lead.get("median_ci95")
    interval = f" ({_minutes(ci[0])}–{_minutes(ci[1])})" if ci else ""
    return (f"{_minutes(lead['median_min'])}{interval}; both {lead['both']}, only App 3 "
            f"{lead['only_app']}, only alarms {lead['only_base']}, neither {lead['neither']}")


def render(record, record_path):
    """The Markdown tables, built only from a run record (as saved) and its repo path."""
    cfg, m = record["config"], record["metrics"]
    nrm = m["normal"]
    chance = f"{_num(nrm['chance_rate'])} ({_num(nrm['chance_rate_ci95'][0])}–{_num(nrm['chance_rate_ci95'][1])})"
    lead_vs = cfg.get("lead_vs")
    lines = [
        f"# Dev detection table: {cfg['detector']}",
        "",
        f"Run record `{record_path}`, commit {record['commit'][:12]}"
        f"{' (dirty)' if record['dirty'] else ''}. Dev pool, {nrm['runs']} run numbers; "
        f"n = {cfg['n']}, G = {cfg['gap']}, q = {cfg['q']}, warm-up {cfg['warmup']}. "
        f"Intervals: 95% run-number bootstrap, B = {cfg['bootstrap']['resamples']}, "
        f"seed {record['seeds']['bootstrap']}."
        + (f" Lead time (minutes, positive when App 3 is earlier) is against {lead_vs['detector']}."
           if lead_vs else ""),
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
            f"{_num(r['share_still_flagged'])} ({r['share_still_flagged_runs']} runs) | "
            f"{_lead(r.get('lead'))} |")
    for key, label in (("summary", "Mean, faults 1–15 except 3, 9, 15"),
                       ("excluded", "Mean, faults 3, 9, 15")):
        s = m[key]
        lines.append(f"| {label} | | | {_num(s['rate'])} ({_num(s['rate_ci95'][0])}–"
                     f"{_num(s['rate_ci95'][1])}) / {PENDING} | {chance} | | | | |")
    lo, hi = nrm["per_24h_ci95"]
    lines.append(f"| Normal operation | | | false alerts per 24 h: {_num(nrm['per_24h'], 3)} "
                 f"({_num(lo, 3)}–{_num(hi, 3)}), {nrm['notifications']} in "
                 f"{_num(nrm['hours'], 1)} h | | | | | |")
    if all("load" in m["faults"][f"fault_{f:02d}"] for f in FAULTS):
        lines += [
            "",
            f"## Operator load, first 2 h after onset (decision 60)",
            "",
            "Means are over the fault's runs; flood is a 10-minute period with more than "
            f"{metrics.FLOOD_ABOVE} notifications; chattering is {metrics.CHATTER_TIMES} or more "
            f"turn-ons of one alarm point within {metrics.CHATTER_SPAN} samples.",
            "",
            "| Fault | Notifications per episode (max) | Per 10 min | Peak 10 min | Flood share | "
            "Chattering points per run | Share from chattering |",
            "|---|---|---|---|---|---|---|",
        ]
        for f in FAULTS:
            ld = m["faults"][f"fault_{f:02d}"]["load"]
            lines.append(
                f"| {f}{' (excluded)' if f in EXCLUDED else ''} | {_num(ld['per_episode_mean'], 1)} "
                f"({ld['per_episode_max']}) | {_num(ld['per_10min_mean'])} | {ld['peak_10min']} | "
                f"{_num(ld['flood_share'])} | {_num(ld['chattering_points_per_run'])} | "
                f"{_num(ld['chattering_share'])} |")
    return "\n".join(lines) + "\n"


# ---------- the run ----------

def run(limits_path=drv.DEFAULT_OUT, model_path=drv.DEFAULT_MODEL, *, row=None, lead_vs=None,
        allow_dirty=False, repo_root=None, tables_dir=None, n_boot=metrics.BOOTSTRAP_N):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    tables_dir = Path(tables_dir or DEFAULT_TABLES)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    det, cal_record, limits_sha = load_detector(limits_path, model_path, row, repo_root)
    base = None
    if lead_vs is not None:
        if isinstance(det, AlarmDetector):
            raise DevTableError("lead time is App 3's column; an alarm row has none")
        base, base_record, base_sha = load_detector(lead_vs, None, LEAD_ROW, repo_root)
        if base.list != LEAD_LIST:
            raise DevTableError(f"lead time is against the {LEAD_LIST} list, not {base.list} (decision 60)")
        if base.warmup != det.warmup:
            raise DevTableError(f"warm-ups differ: {det.warmup} and {base.warmup}")
    warmup = det.warmup
    now = datetime.now(timezone.utc)
    table_path = tables_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_dev_table_{det.name}.md"
    if table_path.exists():
        raise FileExistsError(f"{table_path} already exists")

    normal = loader.load_normal("dev")
    cols = tagmap.column_indices(normal.columns, det.input_tags)      # the detector's inputs
    normal_tracks = {k: t for k, (t, _) in det.score(normal).items()}
    rows, hit = {}, {}
    for f in FAULTS:
        faulty = loader.load_faulty(f, "dev")
        if sorted(faulty.runs) != sorted(normal.runs):
            raise DevTableError(f"fault {f}'s dev run numbers aren't the normal dev numbers")
        scored = det.score(faulty)
        tracks = {k: t for k, (t, _) in scored.items()}
        per_point = {k: p for k, (_, p) in scored.items()}
        inputs = {k: faulty.runs[k][:, cols] for k in tracks}
        twins = {k: normal.runs[k][:, cols] for k in tracks}
        row_, dets = fault_row(f, tracks, inputs, twins, warmup, n_boot, per_point)
        if base is not None:
            base_dets = {k: metrics.detection(t, ONSET, warmup=warmup)
                         for k, (t, _) in base.score(faulty).items()}
            row_["lead"] = lead_row(f, dets, base_dets, n_boot)
        rows[f"fault_{f:02d}"] = row_
        hit.update({(f, k): d.detected for k, d in dets.items()})

    results = {"faults": rows,
               "summary": mean_rate(hit, SUMMARY_FAULTS, n_boot),
               "excluded": mean_rate(hit, EXCLUDED, n_boot),
               "normal": normal_row(normal_tracks, warmup, n_boot)}
    config = {"detector": det.name, "pool": "dev", "warmup": warmup, **det.config,
              "onset": ONSET, "window": metrics.WINDOW_SAMPLES,
              "notification_window": [FIRST, LAST], "faults": list(FAULTS),
              "summary_faults": list(SUMMARY_FAULTS),
              "calibration_record": cal_record.relative_to(repo_root).as_posix(),
              "limits_sha256": limits_sha,
              "bootstrap": {"resamples": n_boot, "level": 0.95, "method": "percentile"}}
    if base is not None:
        config["lead_vs"] = {"detector": base.name,
                             "calibration_record": base_record.relative_to(repo_root).as_posix(),
                             "limits_sha256": base_sha}
    seeds = {"bootstrap": BOOTSTRAP_SEED}

    # The table is rendered from the values exactly as the record stores them, then the
    # record is written with the table's checksum. Both share one timestamp.
    name = f"dev_table_{det.name}"
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
    print(f"dev: {len(normal.runs)} run numbers x {len(FAULTS)} faults; detector {det.name}")
    print(f"mean detection, faults 1-15 except 3, 9, 15: {s['rate']:.3f} "
          f"(95% interval {s['rate_ci95'][0]:.3f} to {s['rate_ci95'][1]:.3f})")
    print(f"table: {table_path}\nrun record: {record}")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--row", choices=ROWS, default=None,
                        help="for an alarm limits file: which calibrated row to score")
    lead = parser.add_mutually_exclusive_group()
    lead.add_argument("--lead-vs", type=Path, default=None,
                      help=f"alarm limits for App 3's lead time (default {DEFAULT_LEAD.name} for PCA)")
    lead.add_argument("--no-lead", action="store_true", help="leave the lead-time column empty")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    is_alarm = args.row is not None
    lead_vs = None if (args.no_lead or is_alarm) else (args.lead_vs or DEFAULT_LEAD)
    try:
        run(args.limits, args.model, row=args.row, lead_vs=lead_vs, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError,
            run_record.RunRecordError, drv.CalibrationError, DevTableError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
