"""Export the thin slice's replay stream: one open dev fault run as historian rows.

    python -m ingest.export_replay

Builder side. The run is fixed mechanically (Raj's choice, session 6): fault
REPLAY_FAULT on the lowest run number in the dev pool of dataset/splits.yaml. Nothing
is picked by looking at results.

Writes:
- app/replay/run.csv: `ts, tag, value, quality` rows for the 33 fast tags, with plant
  tag names only, on a synthetic plant clock (START, 3-minute steps). No run, fault or
  sample columns: the CSV, the API and the UI never reveal which run this is.
- eval/replay_source.yaml: the fault, run number and pool (builder side only), with
  the CSV's SHA-256 and the commit it was exported from.

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
from ingest import tags as tagmap

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "app" / "replay" / "run.csv"
DEFAULT_SOURCE = REPO_ROOT / "eval" / "replay_source.yaml"
REPLAY_FAULT = 13
POOL = "dev"
START = datetime(2026, 1, 5, 6, 0, tzinfo=timezone.utc)
STEP = timedelta(minutes=3)
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

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "x", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ts", "tag", "value", "quality"])
        n_rows = 0
        for row in historian_rows(values, runs.columns, tag_names):
            w.writerow(row)
            n_rows += 1
    sha = hashlib.sha256(out_csv.read_bytes()).hexdigest()
    source.parent.mkdir(parents=True, exist_ok=True)
    rel = out_csv.resolve().relative_to(repo_root.resolve()).as_posix() \
        if out_csv.resolve().is_relative_to(repo_root.resolve()) else str(out_csv)
    doc = {"fault": REPLAY_FAULT, "run": number, "pool": POOL,
           "rule": "fault 13 on the lowest dev run number (mechanical, session 6)",
           "csv": rel, "csv_sha256": sha, "rows": n_rows, "samples": len(values),
           "tags": len(tag_names), "start": START.strftime(TS_FORMAT), "step_min": 3,
           "commit": commit, "dirty": dirty}
    with open(source, "x") as f:
        f.write("# Builder side only: which run app/replay/run.csv holds. Never copy into app/.\n")
        yaml.safe_dump(doc, f, sort_keys=False)
    print(f"wrote {out_csv}: {len(values)} samples x {len(tag_names)} tags = {n_rows} rows, "
          f"sha256 {sha[:12]}…")
    print(f"wrote {source}")
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)
    try:
        run()
    except (FileExistsError, loader.LoaderError, splits.SplitsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())