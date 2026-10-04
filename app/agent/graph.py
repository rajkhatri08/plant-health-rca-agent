"""The diagnosis graph's harness (decisions 74, 75; ported from spikes/langgraph): state,
the fixed wiring, the checkpointer, and the calls the operator and the evaluation make.
Claude's scaffolding; the nodes are Raj's (app/agent/nodes.py).

Runtime code: no imports from dataset/, eval/ or ingest/.

The graph, fixed in code (decision 73, criterion 1):

    START -> evidence -> match --route_after_match--> decline ---------------------\\
                                      \\-> adjudicate -> check --route_after_check--+--> record
                                            (the one LLM call)  \\-> decline        |
                                                                 \\-> not_in_library|
                                                                 \\-> show_evidence |
                                                                 \\-> propose ------/
    record --route_after_record--> approval --after_approval--> act -> END
                         \\-> END                      \\-> END (reject)

The four routing functions are the only branch points, and each is a tested function of
the state. The LLM is called only when the matcher would propose (decision 75).

Episodes are LangGraph threads (thread_id = episode). Checkpoints go to a SQLite file
(SqliteSaver), so a new process resumes from the same state. approval pauses with
interrupt(); decide() resumes it with Command(resume=verdict). re_enter() runs the revised
pass: notified_at and library_as_of stay in the saved state, so as_of is notified_at + 60
min, never the clock (decision 11). Side effects go only through app/agent/records.py with
idempotency keys, and every LLM call writes its ledger row (records.LedgerClient).

IDs are opaque (eval/LEAKAGE.md): episode and history_id are hashes (opaque_id), so no run
or fault number reaches a thread, a prompt or a record. start() refuses anything else.

Two clocks (decision 77): as_of is plant time (notified_at + 30 or 60 min) and reads the
evidence; library_as_of is fixed per episode and decides which library revisions are in
force (candidates, retrieval, the faithfulness check).

No tracing: build() refuses to run with LangSmith tracing switched on.
"""

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import partial
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agent import nodes, records
from app.agent import schema as sc
from shared import leak_scan

NODES = ("evidence", "match", "adjudicate", "check", "decline", "not_in_library", "show_evidence",
         "propose", "record", "approval", "act")
STAGES = ("provisional", "revised")
TRACING_VARS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")
OPAQUE = {"episode": re.compile(r"^ep-[0-9a-f]{16}$"), "history_id": re.compile(r"^h-[0-9a-f]{16}$")}
# Fields a pass sets; re_enter clears them so the revised pass starts clean.
PASS_FIELDS = ("as_of", "evidence", "ranking", "candidates", "matcher", "prompt_sha256", "llm", "output",
               "failures", "outcome", "note", "proposal", "recorded", "approval", "done")


class State(TypedDict, total=False):
    # set once at start
    episode: str                # opaque, ep-<16 hex>
    history_id: str             # opaque, h-<16 hex>: the episode's history (eval/LEAKAGE.md)
    notified_at: str            # ISO time of the notification (plant clock)
    library_as_of: str          # ISO time the library is read at (decision 77)
    repeat: int                 # the repeat index, part of the LLM cache key (decision 76)
    operator_note: Any          # the bounded operator note, or None (decision 78; screened in S8)
    stage: str                  # "provisional" (+30 min) or "revised" (+60 min)
    # set by each pass (see nodes.py for each field's form)
    as_of: str
    evidence: dict
    ranking: list
    candidates: list
    matcher: dict
    prompt_sha256: str
    llm: dict
    output: Any
    failures: list
    outcome: str
    note: Any
    proposal: Any
    recorded: str
    approval: str
    done: str


class GraphError(RuntimeError):
    pass


@dataclass
class Deps:
    """What the nodes use, given at build time; never from the LLM.

    tools        app/agent/tools.Tools (or a stand-in with evidence() and retrieve())
    library      app/library/store.Library
    client       an app/agent/llm client; build() wraps it in records.LedgerClient
    records      records.RecordStore
    render       render(features, candidates, operator_note) -> prompt text, Raj's template.
                 candidates: [{"ref", "view", "verdicts"}] in ref order (decision 75)
    thresholds   {"provisional": Fraction, "revised": Fraction}: the matcher's decline
                 thresholds (decisions 69, 72)
    k            top-k candidates (PROTOCOL: k = 2)
    """
    tools: Any
    library: Any
    client: Any
    records: records.RecordStore
    render: Callable
    thresholds: dict
    k: int = 2
    schema: Any = field(default_factory=sc.output_schema)

    def prompt(self, features, candidates, operator_note):
        """The rendered prompt, leak-checked before it can be sent (decision 75; LEAKAGE wall 2)."""
        text = self.render(features, candidates, operator_note)
        if not isinstance(text, str) or not text.strip():
            raise GraphError("the prompt template rendered nothing")
        return leak_scan.check(text, "the rendered prompt")


def opaque_id(prefix, *parts) -> str:
    """An opaque ID: prefix-<first 16 hex of SHA-256 of the parts as JSON>. prefix is "ep"
    (episode) or "h" (history). The parts (which may name a run on the builder side) can't
    be read back from it."""
    if prefix not in ("ep", "h"):
        raise ValueError(f"prefix is 'ep' or 'h', not {prefix!r}")
    digest = hashlib.sha256(json.dumps([str(p) for p in parts]).encode()).hexdigest()
    return f"{prefix}-{digest[:16]}"


def open_checkpointer(path) -> SqliteSaver:
    return SqliteSaver(sqlite3.connect(str(path), check_same_thread=False))


def _refuse_tracing():
    on = [v for v in TRACING_VARS if os.environ.get(v, "").lower() in ("1", "true", "yes")]
    if on:
        raise GraphError(f"tracing is switched on ({on}); nothing about an episode leaves this machine")


def build(checkpointer, deps: Deps):
    """The compiled graph. The wiring is fixed here; nothing else adds a route."""
    _refuse_tracing()
    if set(deps.thresholds) != set(STAGES):
        raise GraphError(f"thresholds must cover {STAGES}")
    if not isinstance(deps.client, records.LedgerClient):
        deps = replace(deps, client=records.LedgerClient(deps.client, deps.records))
    g = StateGraph(State)
    for name in NODES:
        g.add_node(name, partial(getattr(nodes, name), deps=deps))
    g.add_edge(START, "evidence")
    g.add_edge("evidence", "match")
    g.add_conditional_edges("match", nodes.route_after_match, {"decline": "decline", "adjudicate": "adjudicate"})
    g.add_edge("adjudicate", "check")
    g.add_conditional_edges("check", nodes.route_after_check,
                            {"decline": "decline", "not_in_library": "not_in_library",
                             "show_evidence": "show_evidence", "propose": "propose"})
    for terminal in ("decline", "not_in_library", "show_evidence", "propose"):
        g.add_edge(terminal, "record")
    g.add_conditional_edges("record", nodes.route_after_record, {"approval": "approval", "end": END})
    g.add_conditional_edges("approval", nodes.after_approval, {"act": "act", "end": END})
    g.add_edge("act", END)
    return g.compile(checkpointer=checkpointer)


def config(episode) -> dict:
    return {"configurable": {"thread_id": episode}}


def _iso_aware(value, what):
    try:
        t = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise GraphError(f"{what} must be an ISO time, got {value!r}") from None
    if t.tzinfo is None:
        raise GraphError(f"{what} must carry its UTC offset")
    return value


def start(graph, episode, history_id, notified_at, library_as_of, *, repeat=0, operator_note=None) -> dict:
    """The provisional pass for a new episode. It runs until it ends (a decline, a
    family-level answer, a failed check) or pauses at approval."""
    for name, value in (("episode", episode), ("history_id", history_id)):
        if not (isinstance(value, str) and OPAQUE[name].match(value)):
            raise GraphError(f"{name} must be an opaque ID from opaque_id(), got {value!r}")
    _iso_aware(notified_at, "notified_at")
    _iso_aware(library_as_of, "library_as_of")
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 0:
        raise GraphError(f"repeat must be a non-negative integer, got {repeat!r}")
    if graph.get_state(config(episode)).values:
        raise GraphError(f"episode {episode} already started")
    graph.invoke({"episode": episode, "history_id": history_id, "notified_at": notified_at,
                  "library_as_of": library_as_of, "repeat": repeat, "operator_note": operator_note,
                  "stage": "provisional"}, config(episode))
    return snapshot(graph, episode)


def decide(graph, episode, verdict) -> dict:
    """Resume a paused episode with "approve" or "reject" (the approval step; decision 75)."""
    if verdict not in ("approve", "reject"):
        raise GraphError(f"a verdict is approve or reject, not {verdict!r}")
    if not waiting(graph, episode):
        raise GraphError(f"episode {episode} isn't waiting for approval")
    graph.invoke(Command(resume=verdict), config(episode))
    return snapshot(graph, episode)


def re_enter(graph, episode) -> dict:
    """The revised pass (+60 min) for an episode whose provisional pass has finished. It
    sets only the stage and clears the pass's fields; notified_at and library_as_of, and so
    both clocks, come from the saved state."""
    s = graph.get_state(config(episode))
    if not s.values:
        raise GraphError(f"episode {episode} hasn't started")
    if waiting(graph, episode):
        raise GraphError(f"episode {episode} is still waiting for approval")
    if s.next:
        raise GraphError(f"episode {episode} has an unfinished step {list(s.next)}; retry it first")
    if s.values.get("stage") != "provisional":
        raise GraphError(f"episode {episode} has had its revised pass")
    graph.invoke({"stage": "revised", **{f: None for f in PASS_FIELDS}}, config(episode))
    return snapshot(graph, episode)


def retry(graph, episode) -> dict:
    """Run again whatever step didn't finish, from the last checkpoint (after a process
    stopped mid-step)."""
    graph.invoke(None, config(episode))
    return snapshot(graph, episode)


def snapshot(graph, episode) -> dict:
    """{"values": the saved state, "next": the nodes waiting to run}."""
    s = graph.get_state(config(episode))
    return {"values": dict(s.values), "next": list(s.next)}


def waiting(graph, episode) -> bool:
    return "approval" in graph.get_state(config(episode)).next