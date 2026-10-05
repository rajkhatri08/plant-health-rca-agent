"""Export the replay stream: one open dev fault run as historian rows.

    python -m ingest.export_replay [--episode 1|2]

Builder side. The run is fixed mechanically (Raj's choice, session 6): fault
REPLAY_FAULT on the lowest run number in the dev pool of dataset/splits.yaml. Nothing
is picked by looking at results.

Episodes (week 6 S9; app/agent/demo.EPISODES): episode 1 is the stream below; episode 2 is the
masked fault's (decision 62, read from its committed record), its lowest dev run number, written
the same way to app/replay/episode2.csv with its source in eval/replay_source_episode2.yaml.
The file names never say which fault; only the source records do.

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
import json
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
# The demo's episodes (week 6 S9), each chosen by rule before looking at any result. The fault
# lives only here and in the builder-side source record; the app sees an opaque file name.
MASKED_RECORD = Path("eval") / "runs" / "20260928T155738Z_masked_faults.json"     # decision 62's list (PROTOCOL)
EPISODES = {
    1: {"csv": DEFAULT_CSV, "source": DEFAULT_SOURCE,
        "rule": "fault 13 on the lowest dev run number (mechanical, session 6)"},
    2: {"csv": REPO_ROOT / "app" / "replay" / "episode2.csv", "source": REPO_ROOT / "eval" / "replay_source_episode2.yaml",
        "rule": "the masked fault (decision 62; eval/runs/20260928T155738Z_masked_faults.json) on the lowest dev "
                "run number (Raj, week 6 S9)"},
}
START = datetime(2026, 1, 5, 6, 0, tzinfo=timezone.utc)
STEP = timedelta(minutes=3)
STEP_MIN = 3
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ExportError(RuntimeError):
    pass


def masked_fault(repo_root=None):
    """The one fault decision 62 labels masked, read from its committed record."""
    rec = json.loads((Path(repo_root or REPO_ROOT) / MASKED_RECORD).read_text())
    faults = rec["metrics"]["masked_faults"]
    if len(faults) != 1:
        raise ExportError(f"the masked-fault record lists {len(faults)} masked faults; episode 2 needs exactly one")
    return int(faults[0])


def episode_fault(episode, repo_root=None):
    if episode == 1:
        return REPLAY_FAULT
    if episode == 2:
        return masked_fault(repo_root)
    raise ExportError(f"episode is 1 or 2, not {episode!r}")


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


def run(out_csv=None, source=None, *, episode=1, repo_root=None):
    if episode not in EPISODES:
        raise ExportError(f"episode is one of {sorted(EPISODES)}, not {episode!r}")
    out_csv = Path(out_csv or EPISODES[episode]["csv"])
    source = Path(source or EPISODES[episode]["source"])
    for p in (out_csv, source):
        if p.exists():
            raise FileExistsError(f"{p} already exists; the replay stream is exported once")
    repo_root = Path(repo_root or REPO_ROOT)
    fault = episode_fault(episode, repo_root)                      # before loading anything
    commit, dirty = run_record.git_state(repo_root)
    number = replay_run_number(splits.load())
    runs = loader.load_faulty(fault, POOL)
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
    doc = {"episode": episode, "fault": fault, "run": number, "pool": POOL, "rule": EPISODES[episode]["rule"],
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
    parser.add_argument("--episode", type=int, choices=sorted(EPISODES), default=1,
                        help="1: the first replay (already exported); 2: the masked fault's (week 6 S9)")
    args = parser.parse_args(argv)
    try:
        run(episode=args.episode)
    except (FileExistsError, loader.LoaderError, splits.SplitsError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())