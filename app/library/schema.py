"""Library entry schema (decisions 23, 67, 68).

Runtime code: no imports from dataset/, eval/ or ingest/. Pydantic models for the files
under library/entries/<entry_id>/:
- r<k>.yaml                    one revision, never edited (Revision)
- r<k>.approval.yaml           its approval, written only by the gated approval command
                               (Approval); a revision without one is a draft
- r<k>.review-<account>.yaml   a reviewer's note (Review); Claude may only review

These models check each file on its own. Everything that needs other files (the tag
register, the loop map, the accounts, other entries, the 24-hour gap against the
revision's created_at) is checked in app/library/store.py.

Signatures use decision 68's vocabulary. Each listed item is required or supporting;
anything unlisted is "don't care".
"""

import re
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

EVENT_TYPES = ("data_quality", "instrument", "planned_activity", "process")   # decision 7's order
FAMILIES = ("feed composition", "feed supply", "feed temperature", "reactor cooling",
            "condenser cooling", "reaction kinetics")                         # PROTOCOL, Cases
TAG_STATES = ("high", "low", "both", "normal")
LOOP_STATES = ("held", "compensating", "lost", "saturated")
ANALYZER_STATES = ("high", "low", "normal", "not_yet_available")
ACTION_KINDS = ("check", "confirm", "request_setpoint_change", "escalate")
REQUIRED_CHECKS = ("schema", "leak_scan", "provenance", "preconditions", "entry_tests", "gap_24h")

# ISO 14224 (decision 67): until Raj verifies the standard's category names against a
# source he can access, every field holds "unverified". The verified lists are empty, so
# no guessed code can pass. Filling a list is a decision.
UNVERIFIED, NOT_APPLICABLE = "unverified", "not_applicable"
ISO_VERIFIED = {"equipment_class": (), "failure_mode": (), "failure_mechanism": (),
                "cause_category": (), "detection_method": ()}

SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SOURCE_ID = re.compile(r"^src-\d{3}$")     # opaque: the register (eval/sources.yaml) holds the titles
LABEL_IN_ID = re.compile(r"(?:^|-)(?:fault|idv)(?:-?\d|$|-)")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _slug(value, what):
    if not SLUG.match(value):
        raise ValueError(f"{what} {value!r} must be a lowercase slug (letters, digits, hyphens)")
    if LABEL_IN_ID.search(value):
        raise ValueError(f"{what} {value!r} looks like a fault label; IDs describe mechanisms")
    return value


# ---------- signature (decision 68) ----------

Weight = Literal["required", "supporting"]


def _one_state(self):
    """Exactly one of state or one_of; one_of lists at least 2 different states."""
    if (self.state is None) == (self.one_of is None):
        raise ValueError("give either state or one_of, not both or neither")
    if self.one_of is not None and len(set(self.one_of)) != len(self.one_of):
        raise ValueError("one_of repeats a state")
    return self


class TagExpect(_Strict):
    """One expected state, or several acceptable ones (one_of: any of them agrees;
    decision 68, amended 2 October 2026)."""
    state: Literal[TAG_STATES] | None = None
    one_of: tuple[Literal[TAG_STATES], ...] | None = Field(default=None, min_length=2)
    weight: Weight

    _check = model_validator(mode="after")(_one_state)

    def accepted(self) -> tuple:
        return (self.state,) if self.state is not None else self.one_of


class LoopExpect(_Strict):
    state: Literal[LOOP_STATES]
    weight: Weight

    def accepted(self) -> tuple:
        return (self.state,)


class AnalyzerExpect(_Strict):
    """As TagExpect: one state, or one_of several acceptable ones."""
    state: Literal[ANALYZER_STATES] | None = None
    one_of: tuple[Literal[ANALYZER_STATES], ...] | None = Field(default=None, min_length=2)
    weight: Weight

    _check = model_validator(mode="after")(_one_state)

    def accepted(self) -> tuple:
        return (self.state,) if self.state is not None else self.one_of


class MaskedExpect(_Strict):
    state: bool
    weight: Weight


class GroupExpect(_Strict):
    one_of: tuple[str, ...] = Field(min_length=1)       # the top group is one of these
    weight: Weight


class TopTagsExpect(_Strict):
    any_of: tuple[str, ...] = Field(min_length=1)       # at least one of these is in the top 3
    weight: Weight


class Location(_Strict):
    """At the notification only (decision 68, F3-A)."""
    top_group: GroupExpect | None = None
    top_tags: TopTagsExpect | None = None


class Reading(_Strict):
    """Provisional (+30 min) or revised (+60 min)."""
    tags: dict[str, TagExpect] = {}
    loops: dict[str, LoopExpect] = {}
    analyzers: dict[str, AnalyzerExpect] = {}
    masked: MaskedExpect | None = None

    def items(self):
        yield from self.tags.values()
        yield from self.loops.values()
        yield from self.analyzers.values()
        if self.masked:
            yield self.masked


class Signature(_Strict):
    location: Location = Location()
    provisional: Reading = Reading()
    revised: Reading = Reading()

    @model_validator(mode="after")
    def _one_required(self):
        loc = [x for x in (self.location.top_group, self.location.top_tags) if x]
        weights = [x.weight for x in loc + list(self.provisional.items()) + list(self.revised.items())]
        if "required" not in weights:
            raise ValueError("a signature needs at least one required item")
        if not loc and not list(self.provisional.items()):
            # the +30 min diagnosis scores only these, and fit needs a non-zero total (decision 69)
            raise ValueError("a signature needs at least one location or provisional item")
        return self


# ---------- the rest of a revision ----------

class Equipment(_Strict):
    group: str
    equipment_class: str
    tags: tuple[str, ...] = ()
    loops: tuple[str, ...] = ()

    @field_validator("equipment_class")
    @classmethod
    def _iso_class(cls, v):
        return _iso("equipment_class", v)


def _iso(field, value, allow_na=False):
    if value == UNVERIFIED or (allow_na and value == NOT_APPLICABLE) or value in ISO_VERIFIED[field]:
        return value
    raise ValueError(f"ISO 14224 {field} {value!r} isn't verified; use {UNVERIFIED!r} until it is")


class ISO14224(_Strict):
    failure_mode: str
    failure_mechanism: str
    cause_category: str
    detection_method: str

    @model_validator(mode="after")
    def _verified(self):
        _iso("failure_mode", self.failure_mode, allow_na=True)
        for f in ("failure_mechanism", "cause_category", "detection_method"):
            _iso(f, getattr(self, f))
        return self


class Action(_Strict):
    action_id: str
    text: str = Field(min_length=1)
    kind: Literal[ACTION_KINDS]
    safety_preconditions: tuple[str, ...] = Field(min_length=1)
    approval_required: Literal[True]

    @field_validator("action_id")
    @classmethod
    def _id(cls, v):
        return _slug(v, "action_id")

    @field_validator("safety_preconditions")
    @classmethod
    def _non_empty(cls, v):
        if any(not p.strip() for p in v):
            raise ValueError("a safety precondition is empty")
        return v


class Links(_Strict):
    related_entries: tuple[str, ...] = ()
    loops: tuple[str, ...] = ()


class Governance(_Strict):
    author: str
    created_at: AwareDatetime
    effective_from: AwareDatetime
    review_due: AwareDatetime
    change_note: str = Field(min_length=1)
    supersedes: int | None

    @model_validator(mode="after")
    def _dates(self):
        if self.effective_from < self.created_at:
            raise ValueError("effective_from is before created_at")
        if self.review_due <= self.effective_from:
            raise ValueError("review_due must be after effective_from")
        return self


class Revision(_Strict):
    entry_id: str
    revision: int = Field(ge=1)
    event_type: Literal[EVENT_TYPES]
    family: Literal[FAMILIES]
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1200)
    withdrawn: bool = False
    equipment: Equipment
    iso14224: ISO14224
    signature: Signature
    actions: tuple[Action, ...] = ()
    links: Links = Links()
    sources: tuple[str, ...] = ()
    governance: Governance

    @field_validator("entry_id")
    @classmethod
    def _id(cls, v):
        return _slug(v, "entry_id")

    @field_validator("sources")
    @classmethod
    def _opaque_sources(cls, v):
        bad = [s for s in v if not SOURCE_ID.match(s)]
        if bad:
            raise ValueError(f"sources {bad} aren't opaque register IDs (src-NNN); titles stay in "
                             "eval/sources.yaml, never in library/")
        return v

    @model_validator(mode="after")
    def _consistent(self):
        g = self.governance
        if (self.revision == 1) != (g.supersedes is None) or (
                self.revision > 1 and g.supersedes != self.revision - 1):
            raise ValueError("supersedes must be None for revision 1 and revision - 1 after it")
        ids = [a.action_id for a in self.actions]
        if len(set(ids)) != len(ids):
            raise ValueError("an action_id repeats within the entry")
        if self.entry_id in self.links.related_entries:
            raise ValueError("an entry can't link to itself")
        return self


class Approval(_Strict):
    entry_id: str
    revision: int = Field(ge=1)
    approver: str
    approved_at: AwareDatetime
    checks: tuple[str, ...]
    independent: bool

    @field_validator("checks")
    @classmethod
    def _all_checks(cls, v):
        missing = [c for c in REQUIRED_CHECKS if c not in v]
        if missing:
            raise ValueError(f"approval lacks the checks {missing}")
        return v


class Review(_Strict):
    entry_id: str
    revision: int = Field(ge=1)
    reviewer: str
    reviewed_at: AwareDatetime
    note: str = Field(min_length=1)