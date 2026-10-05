"""The diagnosis graph's nodes (decisions 74, 75), implemented by Raj.
The wiring, the state and the harness are in app/agent/graph.py.

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

import hashlib
from datetime import datetime, timedelta
from fractions import Fraction

from langgraph.types import interrupt

from app.agent import emergency as emergency_screen
from app.agent import faithfulness, records
from app.agent import shipped  # noqa: F401 (ship uses it)
from app.agent import llm      # BudgetExceeded and CacheMiss propagate; any other LLMError is an outcome
from app.agent import schema as sc
from app.diagnosis import matcher

OFFSETS_MIN = {"provisional": 30, "revised": 60}
VERDICTS = ("approve", "reject")
OUTCOMES = ("matcher_declined", "declined", "not_in_library", "failed_check", "error", "proposed",
            "emergency", "vetoed")       # the shipped flow (decision 79) gives "vetoed", not "declined" or "not_in_library"
SCHEMA_FAILURE = getattr(sc, "SCHEMA_FAILURE", "schema")    # the code for an answer that breaks the schema


def _library_time(state):
    """The library clock (decision 77), fixed per episode in the state."""
    return datetime.fromisoformat(state["library_as_of"])


def _fraction_text(f) -> str:
    f = Fraction(f)
    return f"{f.numerator}/{f.denominator}"


def _score_json(s) -> dict:
    return {"ref": s.ref, "entry_id": s.entry_id, "required_contradictions": s.required_contradictions,
            "fit": _fraction_text(s.fit), "verdicts": [list(v) for v in s.verdicts]}


def select_candidates(ranking, k) -> list:
    """The Scores shown to the LLM: every entry in the ranking's top k ranks, extended to the
    whole tied block when rank k falls inside one (decision 75), ordered by ref. ranking is
    matcher.rank's list of tied blocks. An empty ranking gives []."""
    chosen, covered = [], 0
    for block in ranking:
        if covered >= k:
            break                                   # the top k ranks are covered
        chosen.extend(block)                        # a whole tied block, even past rank k
        covered += len(block)
    return sorted(chosen, key=lambda s: s.ref)      # ref order, never rank order (decision 75)


def screen(state, deps) -> dict:
    """{"screen": {"emergency": bool, "classes": [...]}} from
    emergency_screen.screen(state["operator_note"]) (decision 78). No clock, no tools, no LLM:
    it reads only the note. A pass without a note is never an emergency."""
    classes = emergency_screen.screen(state.get("operator_note"))      # [] without a note
    return {"screen": {"emergency": bool(classes), "classes": classes}}


def route_after_screen(state) -> str:
    """"emergency" when state["screen"]["emergency"], else "evidence"."""
    return "emergency" if state["screen"]["emergency"] else "evidence"


def emergency(state, deps) -> dict:
    """{"outcome": "emergency", "note": emergency_screen.EMERGENCY_TEXT, "as_of": ISO}: the pass
    ends with the site emergency procedure. No evidence, no matcher, no LLM, no diagnosis, no
    proposal. as_of = notified_at + OFFSETS_MIN[stage] min (the record needs it; no clock)."""
    notified = datetime.fromisoformat(state["notified_at"])
    as_of = notified + timedelta(minutes=OFFSETS_MIN[state["stage"]])       # plant clock, from the state
    return {"outcome": "emergency", "note": emergency_screen.EMERGENCY_TEXT, "as_of": as_of.isoformat()}


def evidence(state, deps) -> dict:
    """{"as_of": ISO, "evidence": features}.
    as_of = notified_at + OFFSETS_MIN[stage] min, as an ISO string with its UTC offset.
    features = deps.tools.evidence(history_id, notified_at, as_of)["features"], called with
    timezone-aware datetimes."""
    notified = datetime.fromisoformat(state["notified_at"])
    as_of = notified + timedelta(minutes=OFFSETS_MIN[state["stage"]])       # plant clock, from the state
    got = deps.tools.evidence(state["history_id"], notified, as_of)
    return {"as_of": as_of.isoformat(), "evidence": got["features"]}


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
    stage = state["stage"]
    ranking = matcher.match(deps.library, state["evidence"], stage, _library_time(state))
    threshold = Fraction(deps.thresholds[stage])
    declined = matcher.decline(ranking, threshold)
    reason = None
    if declined:
        top = ranking[0][0] if ranking else None
        reason = ("no_entry" if top is None else
                  "required_contradictions" if top.required_contradictions > 0 else "below_threshold")
    chosen = select_candidates(ranking, deps.k)
    return {"ranking": [[_score_json(s) for s in block] for block in ranking],
            "candidates": [{"ref": s.ref, "entry_id": s.entry_id, "verdicts": [list(v) for v in s.verdicts]}
                           for s in chosen],
            "matcher": {"decision": "decline" if declined else "propose", "reason": reason,
                        "threshold": _fraction_text(threshold)}}


def route_after_match(state) -> str:
    """"decline" when state["matcher"]["decision"] is decline, else "adjudicate"."""
    return "decline" if state["matcher"]["decision"] == "decline" else "adjudicate"


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
    candidates = sorted(state["candidates"], key=lambda c: c["ref"])
    views = deps.tools.retrieve([c["entry_id"] for c in candidates], _library_time(state))["entries"]
    by_ref = {v["ref"]: v for v in views}
    missing = [c["ref"] for c in candidates if c["ref"] not in by_ref]
    if missing:
        raise RuntimeError(f"candidates not in force at the library clock: {missing}")
    shown = [{"ref": c["ref"], "view": by_ref[c["ref"]], "verdicts": c["verdicts"]} for c in candidates]
    prompt = deps.prompt(state["evidence"], shown, state.get("operator_note"))     # leak-checked
    sha = hashlib.sha256(prompt.encode()).hexdigest()
    try:
        result = deps.client.complete(prompt, deps.schema, repeat=state["repeat"])
    except (llm.BudgetExceeded, llm.CacheMiss):
        raise                                       # the run stops (decision 76)
    except llm.LLMError as e:
        return {"prompt_sha256": sha, "llm": {"error": str(e)}, "output": None, "failures": []}
    try:
        output, failures = sc.parse_output(result.parsed).model_dump(mode="json"), []
    except sc.OutputError as e:
        output, failures = None, [{"code": SCHEMA_FAILURE, "detail": str(e)}]
    return {"prompt_sha256": sha, "llm": result.as_dict(), "output": output, "failures": failures}


def check(state, deps) -> dict:
    """{"failures"}: when there's an output and no schema failure, faithfulness.check(output,
    evidence, [candidate refs], deps.library, library_as_of) as [{"code", "detail"}];
    otherwise the failures as they are."""
    output, failures = state.get("output"), state.get("failures") or []
    if output is None or failures:
        return {"failures": failures}               # an error or a schema failure: nothing to check
    found = faithfulness.check(sc.parse_output(output), state["evidence"],
                               [c["ref"] for c in state["candidates"]], deps.library, _library_time(state))
    return {"failures": [{"code": f.code, "detail": f.detail} for f in found]}


def route_after_check(state) -> str:
    """"show_evidence" when the LLM gave an error or there's any failure; otherwise the
    output's decision: "decline", "not_in_library" or "propose"."""
    if "error" in (state.get("llm") or {}) or state.get("failures"):
        return "show_evidence"
    return state["output"]["decision"]              # decline, not_in_library or propose


def ship(state, deps) -> dict:
    """{"ship": shipped.ship(state["output"], state["failures"], state["llm"], state["ranking"])}
    (decision 79): what the operator is shown. Reads only the state."""
    raise NotImplementedError("Raj implements the ship node (decision 79)")


def route_after_ship(state) -> str:
    """"show_evidence" when state["ship"]["decision"] is evidence, "veto" when it's veto,
    "propose" when it's propose."""
    raise NotImplementedError("Raj implements route_after_ship (decision 79)")


def veto(state, deps) -> dict:
    """{"outcome": "vetoed", "dissent": state["ship"]["dissent"]}: no proposal. The LLM's
    dissent is shown beside the matcher's top entry (state["ship"]["matcher_top"]); it never
    becomes a proposal and never reaches approval."""
    raise NotImplementedError("Raj implements the veto node (decision 79)")


def decline(state, deps) -> dict:
    """{"outcome": "matcher_declined"} when the matcher declined (no LLM call), else
    {"outcome": "declined"} (the LLM declined)."""
    return {"outcome": "matcher_declined" if state["matcher"]["decision"] == "decline" else "declined"}


def not_in_library(state, deps) -> dict:
    """{"outcome": "not_in_library"}: the family-level answer, shown flagged "mechanism not in
    library", with no proposal and no approval."""
    return {"outcome": "not_in_library"}


def show_evidence(state, deps) -> dict:
    """{"outcome": "error" (the LLM gave an error) or "failed_check" (schema or faithfulness),
    "note": faithfulness.FAILED_NOTE}. No proposal; the deterministic evidence is shown."""
    errored = "error" in (state.get("llm") or {})
    return {"outcome": "error" if errored else "failed_check", "note": faithfulness.FAILED_NOTE}


def propose(state, deps) -> dict:
    """{"outcome": "proposed", "proposal": {"entry_ref", "family", "actions", "key"}}.
    actions: for each of the output's action_ids in order, {"action_id", "kind", "text",
    "safety_preconditions"} copied from the entry's revision in force at library_as_of.
    key = records.act_key(episode, stage)."""
    output = state["output"]
    live = deps.library.get(output["entry_ref"].split("@", 1)[0], _library_time(state))
    by_id = {a.action_id: a for a in live.stored.revision.actions}
    actions = [{"action_id": a, "kind": by_id[a].kind, "text": by_id[a].text,
                "safety_preconditions": list(by_id[a].safety_preconditions)}
               for a in output["action_ids"]]          # from the entry, never from the model
    return {"outcome": "proposed",
            "proposal": {"entry_ref": output["entry_ref"], "family": output["family"], "actions": actions,
                         "key": records.act_key(state["episode"], state["stage"])}}


def record(state, deps) -> dict:
    """{"recorded": key}: deps.records.insert_once("diagnosis", records.diagnosis_key(episode,
    stage), payload). The payload holds at least: episode, stage, as_of, library_as_of,
    outcome, candidates (their refs), matcher, output, failures, proposal, prompt_sha256, and
    from the LLM call (None without one) llm_key, model_id, model_version, schema_version."""
    called = state.get("llm") or {}                 # empty when the matcher declined
    key = records.diagnosis_key(state["episode"], state["stage"])
    deps.records.insert_once("diagnosis", key, {
        "episode": state["episode"], "stage": state["stage"], "as_of": state["as_of"],
        "library_as_of": state["library_as_of"], "outcome": state["outcome"],
        "candidates": [c["ref"] for c in state.get("candidates") or []],
        "matcher": state.get("matcher"), "output": state.get("output"),
        "failures": state.get("failures") or [], "proposal": state.get("proposal"),
        "note": state.get("note"), "prompt_sha256": state.get("prompt_sha256"),
        "llm_key": called.get("key"), "llm_error": called.get("error"),
        "model_id": deps.client.settings.model_id if called else None,
        "model_version": called.get("model_version"),
        "schema_version": deps.schema.version if called else None})
    return {"recorded": key}


def route_after_record(state) -> str:
    """"approval" when the outcome is proposed, else "end"."""
    return "approval" if state["outcome"] == "proposed" else "end"


def approval(state, deps) -> dict:
    """{"approval": verdict}. verdict = interrupt(state["proposal"]); anything but approve or
    reject raises ValueError. Then deps.records.insert_once("approval",
    records.approval_key(episode, stage), {"episode", "stage", "verdict", "proposal_key"})."""
    verdict = interrupt(state["proposal"])          # pauses here; nothing above has a side effect
    if verdict not in VERDICTS:
        raise ValueError(f"a verdict is approve or reject, not {verdict!r}")
    deps.records.insert_once("approval", records.approval_key(state["episode"], state["stage"]),
                             {"episode": state["episode"], "stage": state["stage"], "verdict": verdict,
                              "proposal_key": state["proposal"]["key"]})
    return {"approval": verdict}


def after_approval(state) -> str:
    """"act" on approve, "end" on reject."""
    return "act" if state["approval"] == "approve" else "end"


def act(state, deps) -> dict:
    """{"done": key}: deps.records.insert_once("act", proposal["key"], {"episode", "stage",
    "as_of", "entry_ref", "actions"}). A record only: nothing is written to plant controls."""
    proposal = state["proposal"]
    deps.records.insert_once("act", proposal["key"], {
        "episode": state["episode"], "stage": state["stage"], "as_of": state["as_of"],
        "entry_ref": proposal["entry_ref"], "actions": proposal["actions"]})    # a record, never a control write
    return {"done": proposal["key"]}
