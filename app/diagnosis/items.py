"""Signature items against observed features: agree, contradict or unknown (decisions 67-69).

One definition for the matcher (app/diagnosis/matcher.py) and the approval gate's
provenance check (eval/approve_entry.py), so the two can't disagree about what an item
says (one engine, decision 19).

features is features.extract()'s dict: "location", and the "provisional" and "revised"
readings when the run reached them. Each listed item gets one verdict:
- agree       the observed state is one the item accepts (state, or any of one_of)
- contradict  an observed state the item doesn't accept
- unknown     nothing observed: the item's reading is missing (past the end of the run),
              or an analyzer is not_yet_available and the item doesn't accept that

Items come out in a fixed order: location (top group, top tags), then provisional and
revised, each with tags, loops, analyzers and the masked flag. Names are
"location.top_group", "location.top_tags", "<reading>.<kind>.<id>" and "<reading>.masked".

Runtime code: no imports from dataset/, eval/ or ingest/.
"""

from dataclasses import dataclass, field
from typing import Callable

AGREE, CONTRADICT, UNKNOWN = "agree", "contradict", "unknown"
VERDICTS = (AGREE, CONTRADICT, UNKNOWN)
NOT_YET = "not_yet_available"
SCOPES = ("location", "provisional", "revised")


@dataclass(frozen=True)
class Item:
    name: str
    scope: str                  # one of SCOPES
    weight: str                 # "required" or "supporting"
    judge: Callable = field(repr=False, compare=False)

    def verdict(self, features) -> str:
        return self.judge(features)


def _top_group(e):
    def judge(f):
        if "location" not in f:
            return UNKNOWN
        return AGREE if f["location"]["top_group"] in e.one_of else CONTRADICT
    return judge


def _top_tags(e):
    def judge(f):
        if "location" not in f:
            return UNKNOWN
        return AGREE if set(e.any_of) & set(f["location"]["top_tags"]) else CONTRADICT
    return judge


def _state(scope, kind, key, e):
    def judge(f):
        if scope not in f:
            return UNKNOWN
        seen = f[scope][kind][key]
        if seen in e.accepted():
            return AGREE
        if kind == "analyzers" and seen == NOT_YET:
            return UNKNOWN
        return CONTRADICT
    return judge


def _masked(scope, e):
    def judge(f):
        if scope not in f:
            return UNKNOWN
        return AGREE if f[scope]["masked"] == e.state else CONTRADICT
    return judge


def items(signature):
    """Every listed item of a schema.Signature, in the fixed order."""
    loc = signature.location
    if loc.top_group:
        yield Item("location.top_group", "location", loc.top_group.weight, _top_group(loc.top_group))
    if loc.top_tags:
        yield Item("location.top_tags", "location", loc.top_tags.weight, _top_tags(loc.top_tags))
    for scope in ("provisional", "revised"):
        reading = getattr(signature, scope)
        for kind in ("tags", "loops", "analyzers"):
            for key, e in getattr(reading, kind).items():
                yield Item(f"{scope}.{kind}.{key}", scope, e.weight, _state(scope, kind, key, e))
        if reading.masked:
            yield Item(f"{scope}.masked", scope, reading.masked.weight, _masked(scope, reading.masked))
