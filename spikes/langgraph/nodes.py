"""The spike's nodes (decision 73). Stubs for Raj; each raises NotImplementedError.

A node is a plain function: it gets the current state (a dict, see graph.State) and
returns a dict of the fields it changes. LangGraph merges that into the state and saves a
checkpoint after the step. Routing functions (route, after_approval) return the name of
the next branch and change nothing.

Rules from decision 73 and CLAUDE.md:
- No node reads the clock. as_of comes from the saved state: notified_at plus
  toy.OFFSETS_MIN[stage] minutes. That's what makes re-entry at +60 min reproducible.
- approval pauses with langgraph.types.interrupt(proposal) and returns the value it's
  resumed with. On resume, LangGraph runs the node again from its first line, so nothing
  may come before interrupt() that mustn't run twice.
- act is the only node with a side effect. It writes through records.insert_once with
  the proposal's idempotency key, so running it twice (a second resume, or a crash after
  the write and before the checkpoint) still leaves one record.
- Toy only: toy.reading and toy.ENTRIES, no LLM call, no plant data.
"""

from langgraph.types import interrupt  # noqa: F401  (approval uses it)

from spikes.langgraph import toy  # noqa: F401


def evidence(state) -> dict:
    """{"as_of": ISO time, "reading": toy reading}. as_of = state["notified_at"] +
    toy.OFFSETS_MIN[state["stage"]] minutes, as an ISO string with its UTC offset."""
    raise NotImplementedError


def match(state) -> dict:
    """{"ranking": [entry_id, ...], "decision": "propose" or "decline"}. Toy rule: an
    entry agrees when every tag it lists that's in the reading has the listed state;
    propose the best agreeing entry, decline when none agrees."""
    raise NotImplementedError


def route(state) -> str:
    """After match: "propose" or "decline", from state["decision"] only."""
    raise NotImplementedError


def decline(state) -> dict:
    """{"outcome": "declined"}. No proposal, no approval, no action."""
    raise NotImplementedError


def propose(state) -> dict:
    """{"proposal": {"entry", "action_id", "key"}} for the top entry, with action_id from
    toy.ACTIONS and the idempotency key f"{episode}:{stage}:{action_id}"."""
    raise NotImplementedError


def approval(state) -> dict:
    """{"approval": "approve" or "reject"}: interrupt(state["proposal"]) pauses the graph;
    the value it's resumed with is the verdict. Anything else raises ValueError."""
    raise NotImplementedError


def after_approval(state) -> str:
    """"act" on approve, "end" on reject."""
    raise NotImplementedError


def act(state, records) -> dict:
    """The side effect: records.insert_once(proposal key, {"episode", "stage", "entry",
    "action_id", "as_of"}). Returns {"outcome": "acted", "done": key}, whether or not the
    record was new."""
    raise NotImplementedError