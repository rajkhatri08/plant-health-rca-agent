"""The diagnosis graph's nodes (decisions 74, 75). Stubs for Raj; each raises
NotImplementedError. The wiring, the state and the harness are in app/agent/graph.py.

Runtime code: no imports from dataset/, eval/ or ingest/.

A node is a plain function from the state (graph.State) and deps (graph.Deps) to a dict of
the fields it changes; LangGraph saves a checkpoint after each step. A routing function
(route_after_match, route_after_check, route_after_record, after_approval) takes the state
only, returns a branch name and changes nothing. Everything a node puts in the state is
plain JSON (strings, numbers, booleans, lists, dicts, None): fit is written "a/b".

Rules (decisions 11, 16, 17, 74, 75, 77; CLAUDE.md):
- No node reads the clock. as_of = notified_at + OFFSETS_MIN[stage] minutes (plant clock);
  the library is read at state["library_as_of"] (library clock).
- The LLM is called only in adjudicate, and only when the matcher would propose.
- approval pauses with langgraph.types.interrupt(proposal). On resume LangGraph runs it again
  from its first line, so nothing before interrupt() may have a side effect.
- Side effects only through deps.records.insert_once with records' keys, so a re-run step
  writes nothing twice. The LLM call is made through deps.client, which writes its own
  ledger row (records.LedgerClient) and is cached, so a re-run call is free.
- Action texts and safety preconditions come from the library entry, never the model.
"""

from langgraph.types import interrupt  # noqa: F401 (approval uses it)

from app.agent import faithfulness, records  # noqa: F401
from app.agent import llm  # noqa: F401 (BudgetExceeded and CacheMiss propagate; other LLMError is an outcome)
from app.agent import schema as sc  # noqa: F401
from app.diagnosis import matcher  # noqa: F401

OFFSETS_MIN = {"provisional": 30, "revised": 60}
VERDICTS = ("approve", "reject")
OUTCOMES = ("matcher_declined", "declined", "not_in_library", "failed_check", "error", "proposed")


def select_candidates(ranking, k) -> list:
    """The Scores shown to the LLM: every entry in the ranking's top k ranks, extended to the
    whole tied block when rank k falls inside one (decision 75), ordered by ref. ranking is
    matcher.rank's list of tied blocks. An empty ranking gives []."""
    raise NotImplementedError("Raj implements select_candidates (decision 75)")


def evidence(state, deps) -> dict:
    """{"as_of": ISO, "evidence": features}.
    as_of = notified_at + OFFSETS_MIN[stage] min, as an ISO string with its UTC offset.
    features = deps.tools.evidence(history_id, notified_at, as_of)["features"], called with
    timezone-aware datetimes."""
    raise NotImplementedError("Raj implements the evidence node")


def match(state, deps) -> dict:
    """{"ranking", "candidates", "matcher"}.
    ranking = matcher.match(deps.library, evidence, stage, library_as_of) as JSON: a list of
      blocks, each a list of {"ref", "entry_id", "required_contradictions", "fit": "a/b",
      "verdicts": [[item, verdict], ...]}.
    candidates = select_candidates(ranking, deps.k) as {"ref", "entry_id", "verdicts"} in ref
      order (no fit, no rank: decision 75).
    matcher = {"decision": "propose" or "decline",
               "reason": None, "no_entry", "required_contradictions" or "below_threshold",
               "threshold": "a/b"} from matcher.decline(ranking, deps.thresholds[stage])."""
    raise NotImplementedError("Raj implements the match node")


def route_after_match(state) -> str:
    """"decline" when state["matcher"]["decision"] is decline, else "adjudicate"."""
    raise NotImplementedError("Raj implements route_after_match")


def adjudicate(state, deps) -> dict:
    """The one LLM call: {"prompt_sha256", "llm", "output", "failures"}.
    - views = deps.tools.retrieve([c["entry_id"] for c in candidates], library_as_of)["entries"]
    - shown = [{"ref", "view", "verdicts"}] for the candidates, in ref order
    - prompt = deps.prompt(evidence, shown, operator_note)  (leak-checked by the harness)
    - result = deps.client.complete(prompt, deps.schema, repeat=state["repeat"])
    llm = result.as_dict(), or {"error": text} on an llm.LLMError other than BudgetExceeded and
    CacheMiss, which propagate (the run stops; the demo's cache is wrong).
    output = schema.parse_output(result.parsed).model_dump(mode="json"), or None.
    failures = [] or, on schema.OutputError, [{"code": schema.SCHEMA_FAILURE, "detail": text}]."""
    raise NotImplementedError("Raj implements the adjudicate node")


def check(state, deps) -> dict:
    """{"failures"}: when there's an output and no schema failure, faithfulness.check(output,
    evidence, [candidate refs], deps.library, library_as_of) as [{"code", "detail"}];
    otherwise the failures as they are."""
    raise NotImplementedError("Raj implements the check node")


def route_after_check(state) -> str:
    """"show_evidence" when the LLM gave an error or there's any failure; otherwise the
    output's decision: "decline", "not_in_library" or "propose"."""
    raise NotImplementedError("Raj implements route_after_check")


def decline(state, deps) -> dict:
    """{"outcome": "matcher_declined"} when the matcher declined (no LLM call), else
    {"outcome": "declined"} (the LLM declined)."""
    raise NotImplementedError("Raj implements the decline node")


def not_in_library(state, deps) -> dict:
    """{"outcome": "not_in_library"}: the family-level answer, shown flagged "mechanism not in
    library", with no proposal and no approval."""
    raise NotImplementedError("Raj implements the not_in_library node")


def show_evidence(state, deps) -> dict:
    """{"outcome": "error" (the LLM gave an error) or "failed_check" (schema or faithfulness),
    "note": faithfulness.FAILED_NOTE}. No proposal; the deterministic evidence is shown."""
    raise NotImplementedError("Raj implements the show_evidence node")


def propose(state, deps) -> dict:
    """{"outcome": "proposed", "proposal": {"entry_ref", "family", "actions", "key"}}.
    actions: for each of the output's action_ids in order, {"action_id", "kind", "text",
    "safety_preconditions"} copied from the entry's revision in force at library_as_of.
    key = records.act_key(episode, stage)."""
    raise NotImplementedError("Raj implements the propose node")


def record(state, deps) -> dict:
    """{"recorded": key}: deps.records.insert_once("diagnosis", records.diagnosis_key(episode,
    stage), payload). The payload holds at least: episode, stage, as_of, library_as_of,
    outcome, candidates (their refs), matcher, output, failures, proposal, prompt_sha256, and
    from the LLM call (None without one) llm_key, model_id, model_version, schema_version."""
    raise NotImplementedError("Raj implements the record node")


def route_after_record(state) -> str:
    """"approval" when the outcome is proposed, else "end"."""
    raise NotImplementedError("Raj implements route_after_record")


def approval(state, deps) -> dict:
    """{"approval": verdict}. verdict = interrupt(state["proposal"]); anything but approve or
    reject raises ValueError. Then deps.records.insert_once("approval",
    records.approval_key(episode, stage), {"episode", "stage", "verdict", "proposal_key"})."""
    raise NotImplementedError("Raj implements the approval node")


def after_approval(state) -> str:
    """"act" on approve, "end" on reject."""
    raise NotImplementedError("Raj implements after_approval")


def act(state, deps) -> dict:
    """{"done": key}: deps.records.insert_once("act", proposal["key"], {"episode", "stage",
    "as_of", "entry_ref", "actions"}). A record only: nothing is written to plant controls."""
    raise NotImplementedError("Raj implements the act node")