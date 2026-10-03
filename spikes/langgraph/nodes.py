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

from datetime import datetime, timedelta

from langgraph.types import interrupt

from spikes.langgraph import toy

VERDICTS = ("approve", "reject")
DECISIONS = ("propose", "decline")


def evidence(state) -> dict:
    """{"as_of": ISO time, "reading": toy reading}. as_of = state["notified_at"] +
    toy.OFFSETS_MIN[state["stage"]] minutes, as an ISO string with its UTC offset."""
    notified = datetime.fromisoformat(state["notified_at"])
    as_of = (notified + timedelta(minutes=toy.OFFSETS_MIN[state["stage"]])).isoformat()
    # as_of comes only from the saved state, never from the clock (criterion 4)
    return {"as_of": as_of, "reading": toy.reading(state["episode"], state["notified_at"], as_of)}


def match(state) -> dict:
    """{"ranking": [entry_id, ...], "decision": "propose" or "decline"}. Toy rule: an
    entry agrees when every tag it lists that's in the reading has the listed state;
    propose the best agreeing entry, decline when none agrees."""
    reading = state["reading"]
    agreeing = []
    for entry, expected in toy.ENTRIES.items():
        listed = {tag: st for tag, st in expected.items() if tag in reading}
        if listed and all(reading[tag] == st for tag, st in listed.items()):
            agreeing.append((len(listed), entry))          # more agreeing tags ranks higher
    ranking = [entry for _, entry in sorted(agreeing, key=lambda x: (-x[0], x[1]))]
    return {"ranking": ranking, "decision": "propose" if ranking else "decline"}


def route(state) -> str:
    """After match: "propose" or "decline", from state["decision"] only."""
    if state["decision"] not in DECISIONS:
        raise ValueError(f"a decision is propose or decline, not {state['decision']!r}")
    return state["decision"]


def decline(state) -> dict:
    """{"outcome": "declined"}. No proposal, no approval, no action."""
    return {"outcome": "declined"}


def propose(state) -> dict:
    """{"proposal": {"entry", "action_id", "key"}} for the top entry, with action_id from
    toy.ACTIONS and the idempotency key f"{episode}:{stage}:{action_id}"."""
    entry = state["ranking"][0]
    action_id = toy.ACTIONS[entry]
    key = f"{state['episode']}:{state['stage']}:{action_id}"     # one key per episode, stage and action
    return {"proposal": {"entry": entry, "action_id": action_id, "key": key}}


def approval(state) -> dict:
    """{"approval": "approve" or "reject"}: interrupt(state["proposal"]) pauses the graph;
    the value it's resumed with is the verdict. Anything else raises ValueError."""
    verdict = interrupt(state["proposal"])     # pauses here; on resume returns the human's answer
    if verdict not in VERDICTS:
        raise ValueError(f"a verdict is approve or reject, not {verdict!r}")
    return {"approval": verdict}


def after_approval(state) -> str:
    """"act" on approve, "end" on reject."""
    if state["approval"] not in VERDICTS:
        raise ValueError(f"a verdict is approve or reject, not {state['approval']!r}")
    return "act" if state["approval"] == "approve" else "end"


def act(state, records) -> dict:
    """The side effect: records.insert_once(proposal key, {"episode", "stage", "entry",
    "action_id", "as_of"}). Returns {"outcome": "acted", "done": key}, whether or not the
    record was new."""
    p = state["proposal"]
    records.insert_once(p["key"], {"episode": state["episode"], "stage": state["stage"],
                                   "entry": p["entry"], "action_id": p["action_id"],
                                   "as_of": state["as_of"]})     # a second write is a no-op
    return {"outcome": "acted", "done": p["key"]}
