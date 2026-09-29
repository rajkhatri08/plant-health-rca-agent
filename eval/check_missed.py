"""Why does App 3 miss a dev run the alarms catch? A diagnostic, not a metric.

    python -m eval.check_missed [--limits data/models/pca_static_limits.json]
                                [--model data/models/pca_static.npz]
                                [--lead-vs data/models/alarms_realistic_limits.json]
                                [--allow-dirty]

Scores the dev runs of open faults 1-15 and the normal dev runs with one App 3 detector
and the realistic list's grouped alarm row, through dev_table's detectors (the same alert
path). Per fault it lists App 3's missed run numbers and the ones the alarms detected
("only alarms" in the dev table). For each missed run of the 12 summary faults it records
how App 3's track looked around onset:
- on_at_onset: the alert was already on at the onset sample. PROTOCOL counts only a new
  notification after onset, so an alert that bridges from before onset into the fault
  (grouping holds it for G samples) is a miss, not a late detection.
- the last notification before onset, and whether the track stayed on through the window
- the normal dev run with the same number (its twin, decision 49): its notifications up
  to onset, and whether its track equals the faulty run's up to onset (samples 1-20 are
  copies and scoring is causal, so it should)
A missed run's cause is "on at onset" or "no alert in window".

Summary: the run numbers behind every "only alarms" run of the summary faults, whether one
run number accounts for all of them, and whether every one of them was on at onset.
Loads only dev. Writes a check_missed_<detector> run record and prints its findings.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from dataset import loader
from eval import calibrate_driver as drv
from eval import dev_table as dt
from eval import metrics, run_record

ON_AT_ONSET, NO_ALERT = "on at onset", "no alert in window"


def missed_detail(track, twin, warmup, onset=dt.ONSET, window=metrics.WINDOW_SAMPLES):
    """How a missed run's alert track looked around onset. track and twin are whole-run
    0/1 tracks, index 0 = sample 1."""
    a, tw = np.asarray(track).astype(bool), np.asarray(twin).astype(bool)
    notes = metrics.notifications(a, warmup)
    before = [s for s in notes if s <= onset]
    after = [s for s in notes if s > onset]
    return {
        "cause": ON_AT_ONSET if a[onset - 1] else NO_ALERT,
        "on_at_onset": bool(a[onset - 1]),
        "last_notification_before_onset": before[-1] if before else None,
        "on_through_window": bool(a[onset:onset + window].all()),
        "first_notification_after_onset": after[0] if after else None,
        "twin_notifications_pre_onset": [s for s in metrics.notifications(tw, warmup) if s <= onset],
        "twin_track_equal_to_onset": bool(np.array_equal(a[:onset], tw[:onset])),
    }


def summarise(faults):
    """The findings over the summary faults' "only alarms" runs."""
    only = {f: row["only_alarms"] for f, row in faults.items()
            if int(f.split("_")[1]) in dt.SUMMARY_FAULTS}
    numbers = sorted({k for ks in only.values() for k in ks})
    details = [faults[f]["missed_runs"][f"run_{k}"] for f, ks in only.items() for k in ks]
    same = len(numbers) == 1
    return {
        "only_alarms_runs": sum(len(ks) for ks in only.values()),
        "only_alarms_faults": [int(f.split("_")[1]) for f, ks in only.items() if ks],
        "only_alarms_run_numbers": numbers,
        "same_run_everywhere": same,
        "all_on_at_onset": bool(details) and all(d["on_at_onset"] for d in details),
        "hypothesis_holds": same and bool(details) and all(d["on_at_onset"] for d in details),
    }


def run(limits_path=drv.DEFAULT_OUT, model_path=drv.DEFAULT_MODEL, *, lead_vs=dt.DEFAULT_LEAD,
        allow_dirty=False, repo_root=None):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    det, cal_record, limits_sha = dt.load_detector(limits_path, model_path, None, repo_root)
    base, base_record, base_sha = dt.load_detector(lead_vs, None, dt.LEAD_ROW, repo_root)
    if not isinstance(det, dt.PCADetector):
        raise dt.DevTableError("check_missed is for App 3's detector, not an alarm row")
    if base.list != dt.LEAD_LIST:
        raise dt.DevTableError(f"compare against the {dt.LEAD_LIST} list, not {base.list}")
    if base.warmup != det.warmup:
        raise dt.DevTableError(f"warm-ups differ: {det.warmup} and {base.warmup}")
    warmup = det.warmup

    normal = loader.load_normal("dev")
    twins = {k: t for k, (t, _) in det.score(normal).items()}
    faults = {}
    for f in dt.FAULTS:
        faulty = loader.load_faulty(f, "dev")
        if sorted(faulty.runs) != sorted(normal.runs):
            raise dt.DevTableError(f"fault {f}'s dev run numbers aren't the normal dev numbers")
        tracks = {k: t for k, (t, _) in det.score(faulty).items()}
        base_hit = {k: metrics.detection(t, dt.ONSET, warmup=warmup).detected
                    for k, (t, _) in base.score(faulty).items()}
        missed = [k for k in sorted(tracks)
                  if not metrics.detection(tracks[k], dt.ONSET, warmup=warmup).detected]
        row = {"runs": len(tracks), "missed": missed,
               "only_alarms": [k for k in missed if base_hit[k]]}
        if f in dt.SUMMARY_FAULTS:
            row["missed_runs"] = {f"run_{k}": missed_detail(tracks[k], twins[k], warmup)
                                  for k in missed}
        faults[f"fault_{f:02d}"] = row
    summary = summarise(faults)

    config = {"detector": det.name, "pool": "dev", "warmup": warmup, **det.config,
              "onset": dt.ONSET, "window": metrics.WINDOW_SAMPLES, "faults": list(dt.FAULTS),
              "summary_faults": list(dt.SUMMARY_FAULTS),
              "calibration_record": cal_record.relative_to(repo_root).as_posix(),
              "limits_sha256": limits_sha,
              "alarms": {"detector": base.name,
                         "calibration_record": base_record.relative_to(repo_root).as_posix(),
                         "limits_sha256": base_sha}}
    record = run_record.write(f"check_missed_{det.name}", config=config, seeds={},
                              metrics={"faults": faults, "summary": summary}, outputs={},
                              commit=commit, dirty=dirty, repo_root=repo_root)
    print(f"dev: {len(normal.runs)} run numbers x {len(dt.FAULTS)} faults; detector {det.name}")
    for key, row in faults.items():
        if row["only_alarms"] or (row["missed"] and "missed_runs" in row):
            causes = {k: d["cause"] for k, d in row.get("missed_runs", {}).items()}
            print(f"{key}: missed {row['missed'] if len(row['missed']) <= 5 else len(row['missed'])}, "
                  f"only alarms {row['only_alarms']}" + (f"; {causes}" if causes else ""))
    print(f"only-alarms run numbers (summary faults): {summary['only_alarms_run_numbers']}; "
          f"one run everywhere: {summary['same_run_everywhere']}; "
          f"all on at onset: {summary['all_on_at_onset']}")
    print(f"run record: {record}")
    return faults, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--lead-vs", type=Path, default=dt.DEFAULT_LEAD,
                        help=f"the realistic alarm limits (default {dt.DEFAULT_LEAD.name})")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.limits, args.model, lead_vs=args.lead_vs, allow_dirty=args.allow_dirty)
    except (ValueError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, dt.DevTableError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
