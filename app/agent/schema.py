"""The LLM's output schema (decision 75). Agent-visible: JSON_SCHEMA is sent to the model with
every call, so it passes the leak scan like the prompts (tests/test_leak_scan.py).

Two forms of one schema:
- JSON_SCHEMA, a flat JSON schema (no $ref) for the provider's structured output. It fixes
  the fields, types, enums and lengths. It can't say "required for propose", so
- Output, a Pydantic model, checks everything again after the call, including the rules
  that depend on the decision. tests/test_agent_schema.py keeps the two in step.

Fields (decision 75):
- decision        propose, decline or not_in_library
- entry_ref       entry_id@r<k>: required for propose (a candidate; the faithfulness check
                  confirms it), and null otherwise
- family          one of the library's families: required for propose and not_in_library,
                  null for decline
- confidence      high, medium or low
- cited_evidence  [{item, state}]: at least two for propose
                  item names one piece of evidence, in the matcher's item names
                  (app/diagnosis/items.py): "location.top_group", "location.top_tags",
                  "<reading>.tags.<tag>", "<reading>.loops.<loop>",
                  "<reading>.analyzers.<tag>", "<reading>.masked"
                  (reading: provisional or revised)
                  state is the observed value as text: a tag, loop or analyzer state,
                  the top group's name, one of the top tags, or "true"/"false" for masked
- action_ids      a subset of the chosen entry's action IDs, possibly empty; empty unless
                  the decision is propose (only an entry has actions)
- rationale       at most 600 characters

Conventions (confirmed by Raj, 4 October 2026; decision 75): entry_ref null and action_ids
empty unless propose; family null for decline; no extra fields. What the output claims about
the evidence and the library is checked in app/agent/faithfulness.py, not here.

An answer that isn't JSON or breaks this schema (OutputError) never reaches the faithfulness
check. It scores like a faithfulness failure (no diagnosis, the evidence shown) and is
counted separately as SCHEMA_FAILURE ("schema"; decision 75).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.library.schema import FAMILIES

SCHEMA_VERSION = "diagnosis-1"          # part of the cache key: bump on any change below
DECISIONS = ("propose", "decline", "not_in_library")
CONFIDENCE = ("high", "medium", "low")
RATIONALE_MAX = 600
SCHEMA_FAILURE = "schema"               # how an invalid answer is counted (decision 75)
MIN_CITATIONS_PROPOSE = 2


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(_Strict):
    item: str = Field(min_length=1)
    state: str = Field(min_length=1)


class Output(_Strict):
    decision: Literal[DECISIONS]
    entry_ref: str | None
    family: Literal[FAMILIES] | None
    confidence: Literal[CONFIDENCE]
    cited_evidence: tuple[Citation, ...]
    action_ids: tuple[str, ...]
    rationale: str = Field(max_length=RATIONALE_MAX)

    @model_validator(mode="after")
    def _by_decision(self):
        if self.decision == "propose":
            if not self.entry_ref:
                raise ValueError("propose needs entry_ref")
            if self.family is None:
                raise ValueError("propose needs family")
            if len(self.cited_evidence) < MIN_CITATIONS_PROPOSE:
                raise ValueError(f"propose needs at least {MIN_CITATIONS_PROPOSE} cited pieces of evidence")
        else:
            if self.entry_ref is not None:
                raise ValueError(f"{self.decision} has no entry_ref")
            if self.action_ids:
                raise ValueError(f"{self.decision} has no actions: only a proposed entry has them")
        if self.decision == "not_in_library" and self.family is None:
            raise ValueError("not_in_library needs family")
        if self.decision == "decline" and self.family is not None:
            raise ValueError("decline has no family")
        if len(set(self.action_ids)) != len(self.action_ids):
            raise ValueError("an action_id repeats")
        return self


JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "entry_ref": {"type": ["string", "null"]},
        "family": {"type": ["string", "null"], "enum": list(FAMILIES) + [None]},
        "confidence": {"type": "string", "enum": list(CONFIDENCE)},
        "cited_evidence": {"type": "array", "items": {
            "type": "object",
            "properties": {"item": {"type": "string"}, "state": {"type": "string"}},
            "required": ["item", "state"], "additionalProperties": False}},
        "action_ids": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string", "maxLength": RATIONALE_MAX},
    },
    "required": ["decision", "entry_ref", "family", "confidence", "cited_evidence", "action_ids", "rationale"],
    "additionalProperties": False,
}


class OutputError(ValueError):
    """The answer isn't a valid Output (not JSON, or breaks the schema)."""


def parse_output(parsed) -> Output:
    """An Output from the provider's parsed JSON (llm.Result.parsed), or OutputError."""
    if not isinstance(parsed, dict):
        raise OutputError("the answer isn't a JSON object")
    try:
        return Output.model_validate(parsed)
    except ValidationError as e:
        first = e.errors()[0]
        raise OutputError(f"the answer breaks the schema: {first['msg']} at {first['loc']}") from None


def output_schema():
    """The llm.OutputSchema sent with every call (its version is part of the cache key)."""
    from app.agent import llm
    return llm.OutputSchema(SCHEMA_VERSION, JSON_SCHEMA)