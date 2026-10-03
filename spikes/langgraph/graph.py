"""The spike's harness (decision 73): state, the fixed graph, the checkpointer, and the
calls an operator's approval and the +60 min re-entry would make. Claude's scaffolding;
the nodes are Raj's (nodes.py).

The graph, fixed in code (criterion 1):

    START -> evidence -> match --route--> decline -> END
                                    \\-> propose -> approval --after_approval--> act -> END
                                                                      \\-> END (reject)

route and after_approval are the only branch points, and each is a tested function of
the state.

Episodes are LangGraph threads (thread_id = episode). Checkpoints go to a SQLite file
(SqliteSaver), so a new Python process resumes from the same state (criterion 3).
approval pauses the graph with interrupt() (criterion 2); decide() resumes it with
Command(resume=verdict). re_enter() runs the same episode again with stage "revised":
notified_at stays in the saved state, so as_of is notified_at + 60 min, never the clock
(criterion 4). act writes through RecordStore.insert_once with an idempotency key
(criterion 5).

No LLM call, no network: build() refuses to run with LangSmith tracing switched on.
"""

import os
import sqlite3
from functools import partial
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from spikes.langgraph import nodes
from spikes.langgraph.records import RecordStore

NODES = ("evidence", "match", "decline", "propose", "approval", "act")
TRACING_VARS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")


class State(TypedDict, total=False):
    episode: str
    notified_at: str            # ISO time of the notification, set once at start
    stage: str                  # "provisional" (+30 min) or "revised" (+60 min)
    as_of: str
    reading: dict
    ranking: list
    decision: str               # "propose" or "decline"
    proposal: dict              # {"entry", "action_id", "key"}
    approval: str               # "approve" or "reject"
    outcome: str                # "declined" or "acted"; a reject ends with approval "reject"
    done: str                   # the idempotency key of the action taken


class SpikeError(RuntimeError):
    pass


def open_checkpointer(path) -> SqliteSaver:
    return SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))


def build(checkpointer, records: RecordStore):
    """The compiled graph. The wiring is fixed here; nothing else adds a route."""
    on = [v for v in TRACING_VARS if os.environ.get(v, "").lower() in ("1", "true", "yes")]
    if on:
        raise SpikeError(f"tracing is switched on ({on}); the spike sends nothing off this machine")
    g = StateGraph(State)
    g.add_node("evidence", nodes.evidence)
    g.add_node("match", nodes.match)
    g.add_node("decline", nodes.decline)
    g.add_node("propose", nodes.propose)
    g.add_node("approval", nodes.approval)
    g.add_node("act", partial(nodes.act, records=records))
    g.add_edge(START, "evidence")
    g.add_edge("evidence", "match")
    g.add_conditional_edges("match", nodes.route, {"propose": "propose", "decline": "decline"})
    g.add_edge("decline", END)
    g.add_edge("propose", "approval")
    g.add_conditional_edges("approval", nodes.after_approval, {"act": "act", "end": END})
    g.add_edge("act", END)
    return g.compile(checkpointer=checkpointer)


def config(episode) -> dict:
    return {"configurable": {"thread_id": episode}}


def start(graph, episode, notified_at) -> dict:
    """The provisional pass for a new episode. It runs until it declines, or pauses at
    approval."""
    if graph.get_state(config(episode)).values:
        raise SpikeError(f"episode {episode} already started")
    graph.invoke({"episode": episode, "notified_at": notified_at, "stage": "provisional"}, config(episode))
    return snapshot(graph, episode)


def decide(graph, episode, verdict) -> dict:
    """Resume a paused episode with "approve" or "reject"."""
    if verdict not in ("approve", "reject"):
        raise SpikeError(f"a verdict is approve or reject, not {verdict!r}")
    graph.invoke(Command(resume=verdict), config(episode))
    return snapshot(graph, episode)


def re_enter(graph, episode) -> dict:
    """The revised pass (+60 min) for an episode whose provisional pass has finished. It
    sets only the stage; notified_at, and so as_of, come from the saved state."""
    if waiting(graph, episode):
        raise SpikeError(f"episode {episode} is still waiting for approval")
    if not graph.get_state(config(episode)).values:
        raise SpikeError(f"episode {episode} hasn't started")
    graph.invoke({"stage": "revised", "proposal": None, "approval": None, "outcome": None, "done": None},
                 config(episode))
    return snapshot(graph, episode)


def retry(graph, episode) -> dict:
    """Run again whatever step didn't finish, from the last checkpoint: after a process
    stopped mid-step (for example after act's write and before its checkpoint)."""
    graph.invoke(None, config(episode))
    return snapshot(graph, episode)


def snapshot(graph, episode) -> dict:
    """{"values": the saved state, "next": the nodes waiting to run}."""
    s = graph.get_state(config(episode))
    return {"values": dict(s.values), "next": list(s.next)}


def waiting(graph, episode) -> bool:
    return "approval" in graph.get_state(config(episode)).next