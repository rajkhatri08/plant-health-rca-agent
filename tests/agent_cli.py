"""A command line for the graph tests, so each step can run in its own Python process
(decision 73, criterion 3). Prints JSON only. The LLM is tests/agent_helpers' FakeClient,
behind the cache in <dir>/cache, so a step re-run in another process is a cache hit.

    python -m tests.agent_cli <dir> start <episode> <history_id>
    python -m tests.agent_cli <dir> decide <episode> approve|reject
    python -m tests.agent_cli <dir> reenter <episode>
    python -m tests.agent_cli <dir> retry <episode>
    python -m tests.agent_cli <dir> state <episode>
    python -m tests.agent_cli <dir> records

start uses tests/agent_helpers' NOTIFIED and LIBRARY_AS_OF, and the "propose" answer.
"""

import json
import sys

from app.agent import graph as ag
from tests import agent_helpers as ah


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    folder, cmd, *rest = argv
    g, deps, _ = ah.open_graph(folder)
    if cmd == "start":
        out = ag.start(g, rest[0], rest[1], ah.NOTIFIED, ah.LIBRARY_AS_OF)
    elif cmd == "decide":
        out = ag.decide(g, *rest)
    elif cmd == "reenter":
        out = ag.re_enter(g, *rest)
    elif cmd == "retry":
        out = ag.retry(g, *rest)
    elif cmd == "state":
        out = ag.snapshot(g, *rest)
    elif cmd == "records":
        out = deps.records.all()
    else:
        print(f"unknown command {cmd}", file=sys.stderr)
        return 2
    print(json.dumps(out, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())