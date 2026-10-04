"""Export the replay stream: one open dev fault run as historian rows.

    python -m ingest.export_replay

Builder side. The run is fixed mechanically (Raj's choice, session 6): fault
REPLAY_FAULT on the lowest run number in the dev pool of dataset/splits.yaml. Nothing
is picked by looking at results.

Writes (week 6 S2: the second export, with the analyzers):
- app/replay/run_v2.csv: `ts, tag, value, quality` rows with plant tag names only, on a
  synthetic plant clock (START, 3-minute steps). Each sample has a row for each of the 33
  fast tags, then a row for each analyzer that published a value at that sample. An
  analyzer's value appears only at its publication time, never in between: the reader
  holds the last value and never interpolates (CLAUDE.md, Time). Publications are
  recovered from the stored held series by eval/cases.publications_from_held, the same
  function the evaluation's features use, so the replay's analyzers are evaluation's.
  No run, fault or sample columns: the CSV, the API and the UI never reveal which run
  this is.
- eval/replay_source_v2.yaml: the fault, run number and pool (builder side only), with
  the CSV's SHA-256, the row counts and the commit it was exported from.

The first export (app/replay/run.csv, 33 fast tags, and eval/replay_source.yaml, from
commit 70947bc) stays as committed: the live API serves it until the demo wiring (week 6
S9) switches REPLAY_CSV. app/detector/replay.read_csv skips tags it isn't asked for, so
the API reads the new file the same way.

Values are written with repr(), so each float32 round-trips exactly and the replay
scores exactly what evaluation scores. Refuses to overwrite either file. Prints only
counts and the checksum, never values.
"""

import argparse
import csv
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from dataset import loader, splits
from eval import run_record
from eval.cases import publications_from_held
from ingest import tags as tagmap

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "app" / "replay" / "run_v2.csv"
DEFAULT_SOURCE = REPO_ROOT / "eval" / "replay_source_v2.yaml"
REPLAY_FAULT = 13
POOL = "dev"
START = datetime(2026, 1, 5, 6, 0, tzinfo=timezone.utc)
STEP = timedelta(minutes=3)
STEP_MIN = 3
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def replay_run_number(assignment):
    """The lowest run number in the dev pool."""
    return min(assignment["pools"][POOL])


def historian_rows(values, columns, tag_names):
    """(ts, tag, value, quality) for every sample and tag, in time then register order."""
    cols = tagmap.column_indices(columns, tag_names)
    for i, sample in enumerate(values):
        ts = (START + i * STEP).strftime(TS_FORMAT)
        for tag, c in zip(tag_names, cols):
            yield ts, tag, repr(float(sample[c])), "good"


def analyzer_intervals(repo_root=None):
    """{analyzer tag: update interval in samples}, in register order (library/tags.yaml)."""
    return {r["tag"]: r["update_interval_min"] // STEP_MIN for r in tagmap.register(repo_root)
            if r["kind"] == "analyzer"}


def publications(values, columns, intervals):
    """{analyzer tag: [(1-based sample, value), ...]} from the run's stored held series."""
    cols = tagmap.column_indices(columns, list(intervals))
    return {tag: publications_from_held(values[:, c], intervals[tag]) for tag, c in zip(intervals, cols)}


def stream_rows(values, columns, fast_tags, pubs):
    """(ts, tag, value, quality) in time order: at each sample, the fast tags in register
    order, then each analyzer that published at that sample, in register order."""
    at = {}
    for tag, items in pubs.items():                       # pubs is in register order
        for s, v in items:
            at.setdefault(s, []).append((tag, v))
    fast = historian_rows(values, columns, fast_tags)
    for i in range(len(values)):
        for _ in fast_tags:
            yield next(fast)
        ts = (START + i * STEP).strftime(TS_FORMAT)
        for tag, v in at.get(i + 1, ()):
            yield ts, tag, repr(float(v)), "good"


def run(out_csv=DEFAULT_CSV, source=DEFAULT_SOURCE, *, repo_root=None):
    out_csv, source = Path(out_csv), Path(source)
    for p in (out_csv, source):
        if p.exists():
            raise FileExistsError(f"{p} already exists; the replay stream is exported once")
    repo_root = Path(repo_root or REPO_ROOT)
    commit, dirty = run_record.git_state(repo_root)
    number = replay_run_number(splits.load())
    runs = loader.load_faulty(REPLAY_FAULT, POOL)
    tag_names = tagmap.fast_tags()
    values = runs.runs[number]
    intervals = analyzer_intervals()
    pubs = publications(values, runs.columns, intervals)    # refuses an off-schedule series first

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    n_fast = len(values) * len(tag_names)
    with open(out_csv, "x", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ts", "tag", "value", "quality"])
        n_rows = 0
        for row in stream_rows(values, runs.columns, tag_names, pubs):
            w.writerow(row)
            n_rows += 1
    sha = hashlib.sha256(out_csv.read_bytes()).hexdigest()
    source.parent.mkdir(parents=True, exist_ok=True)
    rel = out_csv.resolve().relative_to(repo_root.resolve()).as_posix() \
        if out_csv.resolve().is_relative_to(repo_root.resolve()) else str(out_csv)
    doc = {"fault": REPLAY_FAULT, "run": number, "pool": POOL,
           "rule": "fault 13 on the lowest dev run number (mechanical, session 6)",
           "csv": rel, "csv_sha256": sha, "rows": n_rows, "samples": len(values),
           "tags": len(tag_names), "analyzers": len(intervals),
           "fast_rows": n_fast, "analyzer_rows": n_rows - n_fast,
           "start": START.strftime(TS_FORMAT), "step_min": STEP_MIN,
           "commit": commit, "dirty": dirty}
    with open(source, "x") as f:
        f.write(f"# Builder side only: which run {rel} holds. Never copy into app/.\n")
        yaml.safe_dump(doc, f, sort_keys=False)
    print(f"wrote {out_csv}: {len(values)} samples x {len(tag_names)} fast tags + "
          f"{n_rows - n_fast} analyzer publications ({len(intervals)} analyzers) = {n_rows} rows, "
          f"sha256 {sha[:12]}…")
    print(f"wrote {source}")
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)
    try:
        run()
    except (FileExistsError, loader.LoaderError, splits.SplitsError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())