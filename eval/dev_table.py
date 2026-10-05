"""Per-fault detection table on dev (PROTOCOL, Detection metrics and Alarm comparison;
decisions 49, 57, 58, 60).

    python -m eval.dev_table [--limits data/models/pca_static_limits.json]
                             [--model data/models/pca_static.npz]
                             [--lead-vs data/models/alarms_realistic_limits.json | --no-lead]
                             [--masked eval/runs/<stamp>_masked_faults.json]
                             [--watch data/models/pca_static_watch.json]
    python -m eval.dev_table --limits data/models/alarms_<list>_limits.json
                             --row grouped|ungrouped
    (either form: [--allow-dirty])

Scores the dev runs of open faults 1-15 and the normal dev runs with one calibrated
detector: App 3's PCA (through calibration's alert path, app/detector/alerting.py), or
one row of the conventional-alarm baseline (eval/baselines/alarms.py). The detector's
kind comes from its limits file, which must be the output of exactly one calibration
run record. By default it loads nothing but dev; --split test (below) is the only way in
to the test split and faults 16-20, through the loader's EVAL_MODE gate.

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
weighted equally. Masked comes from a masked_faults run record (eval/masked.py, decided on
the selection runs, decision 62): the plant-level verdict, naming the absorbing valves
when masked.

With --watch (App 3 only; a watch file from eval/calibrate_watch.py made from these
limits), attribution is read at each detected run's notification (decisions 64, 65):
groups ranked by RBC_g / W_g and tags by RBC_i / W_i, each the mean over the n samples
that triggered it (t - n + 1 .. t). Right place is the top group being one of the fault
family's groups (FAMILY_GROUPS), reported over all runs next to "any", with "k of
detected" beside it, and again 10 samples (30 min) later as a secondary figure. Faults
3, 9 and 15 have no family, so no right place. Per fault it also lists the three tags
most often ranked first and the most frequent top group. Without --watch, right place
reads "—".

Writes a dev_table_<detector> run record holding every number, and a Markdown rendering
of that record to data/tables/ (gitignored). Prints only the paths and one summary line.

--split test (week 7; Raj runs it with EVAL_MODE=1 for the frozen test run, never Claude):
the same table on the testing files through eval/split.py. All 500 runs per fault and the
500 normal testing runs (S0 answer 6), onset after sample 160, faults 1-20, every file load
access-logged. It needs --twin-check, a twin_check run record (eval/twin_check.py): the
before-divergence column is computed only when its verdict is "shared", and otherwise reads
"not reported" (PROTOCOL; decision 57; S1 Q3). The summary is faults 1-20 except 3, 9 and
15; right place is summarised over the 12 family faults (S1 Q4). Faults 16-20 have no label:
family and right place read "n/a", Masked "not labelled" (S0 answer 8). Writes a
test_table_<detector> record (aggregates only, like every record) and its table to
data/tables/.
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.detector import loops as loop_map
from app.detector import pca, rbc
from dataset import loader
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import check_dev, metrics, run_record
from eval import split as split_mod
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
FAMILY_GROUPS = {                                      # decision 65, fixed before any RBC result
    "feed composition": ("feed",),
    "feed supply": ("feed",),
    "feed temperature": ("stripper", "feed"),
    "reactor cooling": ("reactor",),
    "condenser cooling": ("condenser",),
    "reaction kinetics": ("reactor",),
}
UNLABELLED = tuple(loader.QUARANTINED_FAULTS)          # 16-20: test only, no family, no masked label
NOT_APPLICABLE = "n/a"
NOT_LABELLED = "not labelled"
NOT_REPORTED = "not reported"
TOP_TAGS = 3
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
    """App 3's PCA, static (L = 0) or dynamic (decision 63): one plant stream."""

    def __init__(self, lim, model):
        self.name, self.warmup, self.lim, self.model = lim["detector"], lim["warmup"], lim, model
        self.lags = lim["lags"]
        self.input_tags = drv.input_tags(model, self.lags)   # plant tags, the lag-0 block
        self.config = {"n": lim["n"], "gap": lim["gap"], "q": lim["q"], "lags": lim["lags"],
                       "model_sha256": lim["model_sha256"]}

    def score(self, runs):
        """{run number: (alert track, [notification samples per point])}; one point."""
        tracks = drv.tracks(drv.score_runs(self.model, runs, lags=self.lags),
                            (self.lim["t2_lim"], self.lim["spe_lim"]),
                            self.lim["n"], self.lim["gap"], self.warmup, self.lags)
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


def load_masked(record_path, repo_root):
    """(relative path, {fault key: {"masked", "valves"}}) from a masked_faults run record
    made with the plant-level rule (decision 62, amended) and the current loop map."""
    path = Path(record_path)
    if not path.name.endswith("_masked_faults.json"):
        raise DevTableError(f"{path} isn't a masked_faults run record")
    rec = json.loads(path.read_text())
    if rec["config"].get("rule") != "plant":
        raise DevTableError(f"{path} was made with the superseded any-loop rule; re-run eval.masked")
    if rec["config"].get("loop_map_sha256") != run_record.sha256(loop_map.LOOPS_FILE):
        raise DevTableError(f"{path} was made with a different loop map than library/loops.yaml")
    faults = rec["metrics"]["faults"]
    missing = [f"fault_{f:02d}" for f in FAULTS if f"fault_{f:02d}" not in faults]
    if missing:
        raise DevTableError(f"{path} has no verdict for {missing[:3]}")
    rel = path.resolve().relative_to(Path(repo_root).resolve()).as_posix()
    return rel, {k: {"masked": v["masked"], "valves": v["absorbing_valves"]} for k, v in faults.items()}


def load_twin_check(record_path, repo_root):
    """(relative path, shared?) from a twin_check run record (eval/twin_check.py)."""
    path = Path(record_path)
    if not path.name.endswith("_twin_check.json"):
        raise DevTableError(f"{path} isn't a twin_check run record")
    rec = json.loads(path.read_text())
    verdict = rec["metrics"].get("verdict")
    if rec["config"].get("split") != "test" or verdict not in ("shared", "not shared"):
        raise DevTableError(f"{path} isn't a test twin check with a verdict")
    return path.resolve().relative_to(Path(repo_root).resolve()).as_posix(), verdict == "shared"


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


def operator_load(per_point_by_run, onset=ONSET):
    """Decision 60's counts over one fault's runs, in the notification window after onset.
    per_point_by_run maps a run number to that run's notification samples per point."""
    first, last = onset + 1, onset + metrics.NOTIFY_SAMPLES
    episodes, periods, chatter_points, chatter_notes, total = [], [], [], 0, 0
    for k in sorted(per_point_by_run):
        per_point = [[s for s in notes if first <= s <= last] for notes in per_point_by_run[k]]
        pooled = sorted(s for notes in per_point for s in notes)
        counts = metrics.period_counts(pooled, onset)
        chattering = [metrics.is_chattering(notes, first, last) for notes in per_point]
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


def attribution_row(fault, group_ratios, tag_ratios, dets, n, names, tags, n_boot):
    """(row, right hits, right hits 30 min later) for one fault (decisions 64, 65).
    group_ratios and tag_ratios map run number to whole-run RBC / W arrays (samples x
    groups, samples x tags); dets maps run number to App 3's Detection. The hits map
    (fault, run number) to "detected with the right place"; they're None for a fault with
    no family."""
    numbers = sorted(dets)
    detected = [k for k in numbers if dets[k].detected]
    allowed = FAMILY_GROUPS.get(FAMILIES.get(fault))
    top_group, top_tag, right, right_30 = {}, {}, {}, {}
    for k in detected:
        t = dets[k].sample
        _, g_order = rbc.rank_at(group_ratios[k], t, n)
        _, t_order = rbc.rank_at(tag_ratios[k], t, n)
        top_group[k], top_tag[k] = names[g_order[0]], tags[t_order[0]]
        if allowed:
            right[k] = metrics.right_place(g_order, names, allowed)
            _, later = rbc.rank_at(group_ratios[k], t + metrics.SECONDARY_OFFSET, n)
            right_30[k] = metrics.right_place(later, names, allowed)

    tag_counts = {}
    for tag in top_tag.values():
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
    ranked = sorted(tag_counts, key=lambda tag: (-tag_counts[tag], tags.index(tag)))[:TOP_TAGS]
    group_counts = {g: list(top_group.values()).count(g) for g in names}
    best = max(names, key=lambda g: (group_counts[g], -names.index(g))) if detected else None
    row = {"detected": len(detected),
           "top_tags": {tag: tag_counts[tag] for tag in ranked},
           "top_group": best,
           "top_group_share": group_counts[best] / len(detected) if detected else None}
    if not allowed:
        return row, None, None

    runs = [metrics.ScoredRun(fault, k, None) for k in numbers]
    hits = {}
    for label, got in (("", right), ("_30min", right_30)):
        hit = {(fault, k): got.get(k, False) for k in numbers}
        row[f"right_place{label}"] = {"rate": _rate(list(hit.values())),
                                      "rate_ci95": _ci(runs, hit, _rate, n_boot),
                                      "right": sum(hit.values()), "of_detected": len(detected)}
        hits[label] = hit
    row["allowed_groups"] = list(allowed)
    return row, hits[""], hits["_30min"]


def fault_row(fault, tracks, inputs, twins, warmup, n_boot, per_point=None, onset=ONSET):
    """(row, per-run detections) for one fault. tracks, inputs and twins are keyed by
    run number; inputs and twins hold only the detector's input columns (decision 57).
    twins None: the twins aren't known to share streams, so before divergence is "not
    reported" (test, S1 Q3). per_point, if given, maps run number to notification samples
    per alarm point."""
    numbers = sorted(tracks)
    runs = [metrics.ScoredRun(fault, k, tracks[k]) for k in numbers]
    det = {k: metrics.detection(tracks[k], onset, warmup=warmup) for k in numbers}
    if twins is None:
        before, of = NOT_REPORTED, NOT_REPORTED
    else:
        div = {k: metrics.first_divergence(inputs[k], twins[k]) for k in numbers}
        early = [k for k in numbers if div[k] is not None and div[k] <= onset]
        if early:
            raise DevTableError(f"fault {fault}: runs {early[:5]} differ from their twins at or before "
                                f"sample {onset}; decision 49 says samples 1-{onset} are copies")
        before, of = metrics.before_divergence_share([det[k] for k in numbers], [div[k] for k in numbers])
    detected = [k for k in numbers if det[k].detected]
    median, q1, q3 = metrics.delay_summary([det[k].delay_min for k in numbers])
    flagged = [metrics.share_still_flagged(tracks[k], det[k].sample) for k in detected]
    hit = {(fault, k): det[k].detected for k in numbers}
    delay = {(fault, k): det[k].delay_min for k in numbers}
    row = {
        "family": FAMILIES.get(fault, NOT_APPLICABLE if fault in UNLABELLED else PENDING),
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
        row["load"] = operator_load(per_point, onset)
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


def normal_row(tracks, warmup, n_boot, onset=ONSET):
    """False alerts per 24 h and the chance rate on the split's normal runs (rule 4), with
    fake onsets at the split's onset."""
    runs = [metrics.ScoredRun(0, k, tracks[k]) for k in sorted(tracks)]
    count, hours, per_24h = metrics.false_alerts_per_24h(runs, warmup)
    per_run = {(0, r.run): metrics.false_alerts_per_24h([r], warmup)[:2] for r in runs}
    lucky = {(0, r.run): metrics.chance_rate([r], onset, warmup=warmup) == 1.0 for r in runs}

    def rate_24h(pairs):                     # pooled count over pooled hours, as the metric
        return sum(c for c, _ in pairs) / sum(h for _, h in pairs) * 24

    return {
        "runs": len(runs),
        "notifications": count,
        "hours": hours,
        "per_24h": per_24h,
        "per_24h_ci95": _ci(runs, per_run, rate_24h, n_boot),
        "chance_rate": metrics.chance_rate(runs, onset, warmup=warmup),
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


def _masked(m):
    if m == NOT_LABELLED:
        return NOT_LABELLED
    if not m:
        return PENDING
    return f"yes ({m['valves']})" if m["masked"] else "no"


def _right(rp, fault=None):
    """A right-place figure: the rate over all runs (interval), then k of detected.
    "n/a" for faults 16-20, which have no family."""
    if not rp:
        return NOT_APPLICABLE if fault in UNLABELLED else PENDING
    lo, hi = rp["rate_ci95"]
    return f"{_num(rp['rate'])} ({_num(lo)}–{_num(hi)}), {rp['right']} of {rp['of_detected']} detected"


def _lags_note(cfg):
    """The header's lag note for a dynamic detector (empty for others). L = 0 means the
    lag rule found no lag worth adding, so DPCA equals static PCA (decision 63)."""
    if not cfg["detector"].endswith("_dynamic"):
        return ""
    return f", L = {cfg['lags']} lags" + (" (L = 0: DPCA equals static PCA)" if cfg["lags"] == 0 else "")


def _before(r):
    if r["before_divergence"] == NOT_REPORTED:
        return NOT_REPORTED
    return f"{r['before_divergence']} of {r['before_divergence_of']}"


def render(record, record_path):
    """The Markdown tables, built only from a run record (as saved) and its repo path."""
    cfg, m = record["config"], record["metrics"]
    nrm = m["normal"]
    chance = f"{_num(nrm['chance_rate'])} ({_num(nrm['chance_rate_ci95'][0])}–{_num(nrm['chance_rate_ci95'][1])})"
    lead_vs = cfg.get("lead_vs")
    faults = cfg.get("faults", list(FAULTS))
    test = cfg.get("pool") == "test"
    span = f"faults {min(faults)}–{max(faults)} except 3, 9, 15"
    rp_label = "the 12 family faults" if cfg.get("right_place_faults") else span
    lines = [
        f"# {'Test' if test else 'Dev'} detection table: {cfg['detector']}",
        "",
        f"Run record `{record_path}`, commit {record['commit'][:12]}"
        f"{' (dirty)' if record['dirty'] else ''}. {'Test split' if test else 'Dev pool'}, "
        f"{nrm['runs']} run numbers; "
        f"n = {cfg['n']}, G = {cfg['gap']}, q = {cfg['q']}, warm-up {cfg['warmup']}"
        f"{_lags_note(cfg)}. "
        f"Intervals: 95% run-number bootstrap, B = {cfg['bootstrap']['resamples']}, "
        f"seed {record['seeds']['bootstrap']}."
        + (f" Lead time (minutes, positive when App 3 is earlier) is against {lead_vs['detector']}."
           if lead_vs else "")
        + (f" Masked (decided on the selection runs): `{cfg['masked_record']}`."
           if cfg.get("masked_record") else "")
        + (f" Right place (decision 65) is over all runs, then k of the detected runs; Watch "
           f"boundaries: `{cfg['attribution']['watch_record']}`." if cfg.get("attribution") else "")
        + (f" Twin check: `{cfg['twin_check']['record']}` ({cfg['twin_check']['verdict']})."
           if cfg.get("twin_check") else ""),
        "",
        "| Fault | Family | Masked | Detected (any / right place) | Chance rate | "
        "Detected before divergence | Median delay, min (IQR) | Share still flagged | "
        "Lead time vs grouped alarms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for f in faults:
        r = m["faults"][f"fault_{f:02d}"]
        lo, hi = r["rate_ci95"]
        dlo, dhi = r["delay_median_ci95"]
        lines.append(
            f"| {f}{' (excluded)' if f in EXCLUDED else ''} | {r['family']} | {_masked(r.get('masked'))} | "
            f"{_num(r['rate'])} ({_num(lo)}–{_num(hi)}) / {_right(r.get('attribution', {}).get('right_place'), f)} | {chance} | "
            f"{_before(r)} | "
            f"{_minutes(r['delay_median_min'])} ({_minutes(r['delay_q1_min'])}–{_minutes(r['delay_q3_min'])}); "
            f"median interval {_minutes(dlo)}–{_minutes(dhi)} | "
            f"{_num(r['share_still_flagged'])} ({r['share_still_flagged_runs']} runs) | "
            f"{_lead(r.get('lead'))} |")
    for key, label in (("summary", f"Mean, {span}"),
                       ("excluded", "Mean, faults 3, 9, 15")):
        s = m[key]
        rp = m.get("right_place", {}).get("summary") if key == "summary" else None
        right = (f"{_num(rp['rate'])} ({_num(rp['rate_ci95'][0])}–{_num(rp['rate_ci95'][1])})"
                 if rp else PENDING)
        lines.append(f"| {label} | | | {_num(s['rate'])} ({_num(s['rate_ci95'][0])}–"
                     f"{_num(s['rate_ci95'][1])}) / {right} | {chance} | | | | |")
    lo, hi = nrm["per_24h_ci95"]
    lines.append(f"| Normal operation | | | false alerts per 24 h: {_num(nrm['per_24h'], 3)} "
                 f"({_num(lo, 3)}–{_num(hi, 3)}), {nrm['notifications']} in "
                 f"{_num(nrm['hours'], 1)} h | | | | | |")
    if cfg.get("attribution"):
        at = cfg["attribution"]
        rp = m["right_place"]
        lines += [
            "",
            "## Attribution at the notification (decisions 64, 65)",
            "",
            f"Groups ranked by RBC_g / W_g and tags by RBC_i / W_i, each the mean over the "
            f"{at['window']} samples that triggered the notification (as-of only), with W at "
            f"p = {at['p']}. \"30 min later\" is the same reading {at['secondary_offset']} "
            "samples later. Right place: over all runs (interval), then k of the detected runs. "
            "Top group and top tags: over the detected runs.",
            "",
            "| Fault | Family groups | Right place | Right place 30 min later | Top group (share) | "
            "Top tags (runs ranked first) |",
            "|---|---|---|---|---|---|",
        ]
        for f in faults:
            a = m["faults"][f"fault_{f:02d}"]["attribution"]
            top = (f"{a['top_group']} ({_num(a['top_group_share'])})" if a["top_group"] else PENDING)
            tags_ = ", ".join(f"{t} ({c})" for t, c in a["top_tags"].items()) or PENDING
            groups = NOT_APPLICABLE if f in UNLABELLED else PENDING
            lines.append(
                f"| {f}{' (excluded)' if f in EXCLUDED else ''} | "
                f"{', '.join(a.get('allowed_groups', [])) or groups} | {_right(a.get('right_place'), f)} | "
                f"{_right(a.get('right_place_30min'), f)} | {top} | {tags_} |")
        for key, label in (("summary", "at the notification"), ("summary_30min", "30 min later")):
            s = rp[key]
            lines.append(f"| Mean, {rp_label}, {label} | | {_num(s['rate'])} "
                         f"({_num(s['rate_ci95'][0])}–{_num(s['rate_ci95'][1])}) | | | |")
    if all("load" in m["faults"][f"fault_{f:02d}"] for f in faults):
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
        for f in faults:
            ld = m["faults"][f"fault_{f:02d}"]["load"]
            lines.append(
                f"| {f}{' (excluded)' if f in EXCLUDED else ''} | {_num(ld['per_episode_mean'], 1)} "
                f"({ld['per_episode_max']}) | {_num(ld['per_10min_mean'])} | {ld['peak_10min']} | "
                f"{_num(ld['flood_share'])} | {_num(ld['chattering_points_per_run'])} | "
                f"{_num(ld['chattering_share'])} |")
    return "\n".join(lines) + "\n"


# ---------- the run ----------

def run(limits_path=drv.DEFAULT_OUT, model_path=drv.DEFAULT_MODEL, *, row=None, lead_vs=None,
        masked=None, watch=None, allow_dirty=False, repo_root=None, tables_dir=None,
        n_boot=metrics.BOOTSTRAP_N, split="dev", twin_check=None):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    tables_dir = Path(tables_dir or DEFAULT_TABLES)
    if split == "test" and twin_check is None:
        raise DevTableError("--split test needs --twin-check, a twin_check run record (decision 57)")
    if split != "test" and twin_check is not None:
        raise DevTableError("--twin-check is only for --split test; dev twins are checked run by run")
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    det, cal_record, limits_sha = load_detector(limits_path, model_path, row, repo_root)
    name = f"{'test' if split == 'test' else 'dev'}_table_{det.name}"
    sp = split_mod.get(split, name)
    onset, faults = sp.onset, sp.faults
    first, last = onset + 1, onset + metrics.NOTIFY_SAMPLES
    summary_faults = tuple(f for f in faults if f not in EXCLUDED)
    right_place_faults = tuple(f for f in summary_faults if f in FAMILIES)     # S1 Q4
    twin_rel, twins_shared = load_twin_check(twin_check, repo_root) if twin_check is not None else (None, True)
    base = None
    if lead_vs is not None:
        if isinstance(det, AlarmDetector):
            raise DevTableError("lead time is App 3's column; an alarm row has none")
        base, base_record, base_sha = load_detector(lead_vs, None, LEAD_ROW, repo_root)
        if base.list != LEAD_LIST:
            raise DevTableError(f"lead time is against the {LEAD_LIST} list, not {base.list} (decision 60)")
        if base.warmup != det.warmup:
            raise DevTableError(f"warm-ups differ: {det.warmup} and {base.warmup}")
    masked_rel, masked_by = load_masked(masked, repo_root) if masked is not None else (None, None)
    watch_doc = None
    if watch is not None:
        if not isinstance(det, PCADetector):
            raise DevTableError("attribution is App 3's; an alarm row has none")
        watch_record, watch_doc = cw.load_watch(watch, limits_path, det.model, repo_root)
        names = list(watch_doc["groups"])
        w_group = np.array([watch_doc["groups"][g]["w"] for g in names])
        w_tag = np.array([watch_doc["tags"][t] for t in det.model.tags])
        hit_right, hit_right_30 = {}, {}
    warmup = det.warmup
    now = datetime.now(timezone.utc)
    table_path = tables_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_{name}.md"
    if table_path.exists():
        raise FileExistsError(f"{table_path} already exists")

    normal = sp.load_normal()
    cols = tagmap.column_indices(normal.columns, det.input_tags)      # the detector's inputs
    normal_tracks = {k: t for k, (t, _) in det.score(normal).items()}
    rows, hit = {}, {}
    for f in faults:
        faulty = sp.load_faulty(f)
        if sorted(faulty.runs) != sorted(normal.runs):
            raise DevTableError(f"fault {f}'s {sp.name} run numbers aren't the normal {sp.name} numbers")
        scored = det.score(faulty)
        tracks = {k: t for k, (t, _) in scored.items()}
        per_point = {k: p for k, (_, p) in scored.items()}
        inputs = {k: faulty.runs[k][:, cols] for k in tracks}
        twins = {k: normal.runs[k][:, cols] for k in tracks} if twins_shared else None
        row_, dets = fault_row(f, tracks, inputs, twins, warmup, n_boot, per_point, onset)
        if base is not None:
            base_dets = {k: metrics.detection(t, onset, warmup=warmup)
                         for k, (t, _) in base.score(faulty).items()}
            row_["lead"] = lead_row(f, dets, base_dets, n_boot)
        if masked_by is not None:
            row_["masked"] = NOT_LABELLED if f in UNLABELLED else masked_by[f"fault_{f:02d}"]
        if watch_doc is not None:
            by_group, by_tag = cw.rbc_runs(det.model, det.lim, faulty, names)
            row_["attribution"], right, right_30 = attribution_row(
                f, {k: v / w_group for k, v in by_group.items()},
                {k: v / w_tag for k, v in by_tag.items()}, dets, det.lim["n"], names,
                list(det.model.tags), n_boot)
            if right is not None:
                hit_right.update(right)
                hit_right_30.update(right_30)
        rows[f"fault_{f:02d}"] = row_
        hit.update({(f, k): d.detected for k, d in dets.items()})

    results = {"faults": rows,
               "summary": mean_rate(hit, summary_faults, n_boot),
               "excluded": mean_rate(hit, EXCLUDED, n_boot),
               "normal": normal_row(normal_tracks, warmup, n_boot, onset)}
    if watch_doc is not None:
        results["right_place"] = {"summary": mean_rate(hit_right, right_place_faults, n_boot),
                                  "summary_30min": mean_rate(hit_right_30, right_place_faults, n_boot)}
    config = {"detector": det.name, "pool": sp.name, "warmup": warmup, **det.config,
              "onset": onset, "window": metrics.WINDOW_SAMPLES,
              "notification_window": [first, last], "faults": list(faults),
              "summary_faults": list(summary_faults),
              "calibration_record": cal_record.relative_to(repo_root).as_posix(),
              "limits_sha256": limits_sha,
              "bootstrap": {"resamples": n_boot, "level": 0.95, "method": "percentile"}}
    if sp.name == "test":
        config["split"] = "test"
        config["right_place_faults"] = list(right_place_faults)
        config["twin_check"] = {"record": twin_rel, "verdict": "shared" if twins_shared else "not shared"}
    if masked_rel is not None:
        config["masked_record"] = masked_rel
    if watch_doc is not None:
        config["attribution"] = {"watch_record": watch_record.relative_to(repo_root).as_posix(),
                                 "watch_sha256": run_record.sha256(watch),
                                 "p": watch_doc["p"], "window": det.lim["n"],
                                 "secondary_offset": metrics.SECONDARY_OFFSET,
                                 "family_groups": {fam: list(g) for fam, g in FAMILY_GROUPS.items()}}
    if base is not None:
        config["lead_vs"] = {"detector": base.name,
                             "calibration_record": base_record.relative_to(repo_root).as_posix(),
                             "limits_sha256": base_sha}
    seeds = {"bootstrap": BOOTSTRAP_SEED}

    # The table is rendered from the values exactly as the record stores them, then the
    # record is written with the table's checksum. Both share one timestamp.
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
    print(f"{sp.name}: {len(normal.runs)} run numbers x {len(faults)} faults; detector {det.name}")
    print(f"mean detection, faults {min(faults)}-{max(faults)} except 3, 9, 15: {s['rate']:.3f} "
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
    parser.add_argument("--masked", type=Path, default=None,
                        help="a masked_faults run record (eval/masked.py) for the Masked column")
    parser.add_argument("--watch", type=Path, default=None,
                        help="a watch file (eval/calibrate_watch.py) for right place and top tags")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true (a test load refuses anyway)")
    parser.add_argument("--split", choices=split_mod.NAMES, default="dev",
                        help="test: the sealed testing files, only with EVAL_MODE=1 (Raj runs it)")
    parser.add_argument("--twin-check", type=Path, default=None,
                        help="a twin_check run record (eval/twin_check.py); required with --split test")
    args = parser.parse_args(argv)
    is_alarm = args.row is not None
    lead_vs = None if (args.no_lead or is_alarm) else (args.lead_vs or DEFAULT_LEAD)
    try:
        run(args.limits, args.model, row=args.row, lead_vs=lead_vs, masked=args.masked,
            watch=args.watch, allow_dirty=args.allow_dirty, split=args.split, twin_check=args.twin_check)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError,
            run_record.RunRecordError, drv.CalibrationError, DevTableError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
