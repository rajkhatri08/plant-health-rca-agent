"""A command line for the spike, so each step can run in its own Python process
(decision 73, criterion 3). Prints JSON only.

    python -m spikes.langgraph.cli <dir> start <episode> <notified_at ISO>
    python -m spikes.langgraph.cli <dir> decide <episode> approve|reject
    python -m spikes.langgraph.cli <dir> reenter <episode>
    python -m spikes.langgraph.cli <dir> retry <episode>
    python -m spikes.langgraph.cli <dir> state <episode>
    python -m spikes.langgraph.cli <dir> records

<dir> holds checkpoints.db (LangGraph's state) and records.db (the action's records).
"""

import json
import sys
from pathlib import Path

from spikes.langgraph import graph as hg
from spikes.langgraph.records import RecordStore


def open_graph(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    records = RecordStore(folder / "records.db")
    return hg.build(hg.open_checkpointer(folder / "checkpoints.db"), records), records


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    folder, cmd, *rest = argv
    g, records = open_graph(folder)
    if cmd == "start":
        out = hg.start(g, *rest)
    elif cmd == "decide":
        out = hg.decide(g, *rest)
    elif cmd == "reenter":
        out = hg.re_enter(g, *rest)
    elif cmd == "retry":
        out = hg.retry(g, *rest)
    elif cmd == "state":
        out = hg.snapshot(g, *rest)
    elif cmd == "records":
        out = records.all()
    else:
        print(f"unknown command {cmd}", file=sys.stderr)
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())