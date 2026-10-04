"""The faithfulness check (decision 75; PROTOCOL, Faithfulness and governance checks).
Runtime code: no imports from dataset/, eval/ or ingest/.

Deterministic, after the LLM: everything a schema-valid output (app/agent/schema.Output)
claims about the evidence and the library must trace back to them. check() returns every
failure it finds, not just the first; an empty list is a pass.

The five checks, one Failure code each (decision 75):
1. CITATION   every cited item exists in the evidence with the stated state. The evidence
              is the evidence tool's "features" dict as of the diagnosis time: an item of
              a reading that isn't there (the revised reading at +30 min) doesn't exist.
              Item names and state text follow app/agent/schema.py's docstring:
              - location.top_group: state is the top group's name
              - location.top_tags: state is one of the top tags
              - <reading>.tags|loops|analyzers.<id>: state is that id's observed state
              - <reading>.masked: state is "true" or "false"
2. ENTRY      for propose, entry_ref is one of the candidates shown to the LLM, and is the
              revision in force at as_of (library.get(entry_id, as_of).ref == entry_ref),
              so it's never a draft, a withdrawn entry or a superseded revision.
3. ACTION     every action_id belongs to that entry's revision in force.
4. FAMILY     for propose, family is the entry's family; for not_in_library, it's the
              family of one of the candidates.
5. RATIONALE  the rationale passes the leak scan (shared/leak_scan.py) and holds no number
              the LLM wasn't shown. Digits are allowed only inside tag, loop and analyzer
              IDs in the evidence, the candidates' entry IDs, refs and action IDs, and
              names with numbers in the shown entry text ("reactant 1", "reactants 1
              and 2"), never a number on its own after a function word ("and 2").
              Every other number fails (decision 75).

A failed output isn't shown as a diagnosis: the deterministic evidence is shown with "the
explanation failed a check", it scores as no diagnosis, it's counted separately, and it's
never retried (decision 75). That handling is the graph's (S5); this module only judges.

Raj implements check(). The rest is wiring.
"""

import re
from dataclasses import dataclass

from shared import leak_scan

READINGS = ("provisional", "revised")
SECTIONS = ("tags", "loops", "analyzers")
# A name with a number, with any numbers listed after it: "reactant 1", "Reactant-2",
# "reactants 1 and 2", "products 1, 2 and 3". The whole phrase and its head ("reactants 1")
# are allowed, never a number on its own after a function word ("and 2").
_NAME_WITH_NUMBER = re.compile(r"([A-Za-z]+)[- ]\d+(?:(?:\s*,\s*|\s+(?:and|or)\s+)\d+)*")
_HEAD = re.compile(r"[A-Za-z]+[- ]\d+")
_FUNCTION_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is", "of", "on",
                   "or", "per", "than", "the", "to", "was", "were", "with"}
_DIGITS = re.compile(r"\d")


def _observed(features, item):
    """The states the evidence shows for a citation item, or None if it isn't there."""
    parts = item.split(".", 2)
    if parts[0] == "location" and len(parts) == 2 and parts[1] in ("top_group", "top_tags"):
        loc = features.get("location")
        if loc is None:
            return None
        return {str(loc["top_group"])} if parts[1] == "top_group" else {str(t) for t in loc["top_tags"]}
    if parts[0] in READINGS:
        rd = features.get(parts[0])
        if rd is None:
            return None                          # that reading doesn't exist yet at as_of
        if len(parts) == 2 and parts[1] == "masked":
            return {"true" if rd["masked"] else "false"}
        if len(parts) == 3 and parts[1] in SECTIONS and parts[2] in rd.get(parts[1], {}):
            return {str(rd[parts[1]][parts[2]])}
    return None                                  # not an item name the evidence has


def _shown(library, candidates):
    """The stored revisions the LLM was shown, by exact ref (whatever is in force now)."""
    out = []
    for ref in candidates:
        for s in library.entries.get(ref.split("@", 1)[0], ()):
            if s.ref == ref:
                out.append(s)
    return out


def _allowed_strings(features, shown, entry_ids):
    """Everything with digits the LLM was shown: tag, loop and analyzer IDs in the evidence;
    the candidates' entry IDs, refs and action IDs; and names with a number in their text
    (for example "reactant 1"). Longest first, so a longer ID is removed before its parts."""
    allowed = set(entry_ids)
    loc = features.get("location") or {}
    allowed.update(str(t) for t in loc.get("top_tags", ()))
    for r in READINGS:
        for sec in SECTIONS:
            allowed.update((features.get(r) or {}).get(sec, {}).keys())
    for s in shown:
        rev = s.revision
        allowed.update({s.ref, rev.entry_id, *(a.action_id for a in rev.actions)})
        text = " ".join([rev.title, rev.description, *(a.text for a in rev.actions)])
        for m in _NAME_WITH_NUMBER.finditer(text):
            if m.group(1).lower() not in _FUNCTION_WORDS:
                allowed.update({m.group(0), _HEAD.match(m.group(0)).group(0)})
    return sorted((a for a in allowed if _DIGITS.search(a)), key=len, reverse=True)


def _stray_numbers(text, features, shown, entry_ids):
    """The digit runs left in text once everything the LLM was shown is taken out."""
    rest = text
    for a in _allowed_strings(features, shown, entry_ids):
        rest = re.sub(re.escape(a), " ", rest, flags=re.IGNORECASE)
    return re.findall(r"\d+(?:[.,]\d+)?", rest)

CITATION, ENTRY, ACTION, FAMILY, RATIONALE = "citation", "entry", "action", "family", "rationale"
CODES = (CITATION, ENTRY, ACTION, FAMILY, RATIONALE)
FAILED_NOTE = "the explanation failed a check"


@dataclass(frozen=True)
class Failure:
    code: str              # one of CODES
    detail: str            # what failed, in plant terms (it may be shown to a reviewer)

    def __post_init__(self):
        if self.code not in CODES:
            raise ValueError(f"a failure code is one of {CODES}, not {self.code!r}")


def check(output, features, candidates, library, as_of) -> list:
    """Every Failure in a schema-valid output.

    output      app/agent/schema.Output
    features    the evidence tool's "features" dict at as_of (location, and each reading
                whose time is at or before as_of)
    candidates  the entry refs (entry_id@r<k>) shown to the LLM
    library     app/library/store.Library
    as_of       the diagnosis time (timezone-aware)
    """
    failures = []
    entry_ids = {ref.split("@", 1)[0] for ref in candidates}

    # 1. citations: each cited item exists in the evidence, with the stated state
    for c in output.cited_evidence:
        seen = _observed(features, c.item)
        if seen is None:
            failures.append(Failure(CITATION, f"{c.item} isn't in the evidence at this diagnosis time"))
        elif c.state not in seen:
            failures.append(Failure(CITATION, f"{c.item} is {sorted(seen)}, not {c.state!r}"))

    # 2. the entry: one of the candidates shown, and the revision in force at as_of
    entry = None
    if output.decision == "propose":
        ref = output.entry_ref
        if ref not in candidates:
            failures.append(Failure(ENTRY, f"{ref} wasn't one of the candidates shown"))
        live = library.get(ref.split("@", 1)[0], as_of)
        if live is None or live.ref != ref:
            failures.append(Failure(ENTRY, f"{ref} isn't the revision in force at the diagnosis time"))
        else:
            entry = live.stored.revision        # in force: actions and family are checked against it

    # 3. actions: each belongs to the proposed entry's revision in force
    allowed = {a.action_id for a in entry.actions} if entry is not None else set()
    for action_id in output.action_ids:
        if action_id not in allowed:
            failures.append(Failure(ACTION, f"{action_id} isn't an action of the proposed entry"))

    # 4. family: the entry's own; for not_in_library, one of the candidates' families
    if output.decision == "propose" and entry is not None and output.family != entry.family:
        failures.append(Failure(FAMILY, f"{output.family!r} isn't {entry.entry_id}'s family"))
    if output.decision == "not_in_library":
        shown = {s.revision.family for s in _shown(library, candidates)}
        if output.family not in shown:
            failures.append(Failure(FAMILY, f"{output.family!r} isn't the family of any candidate shown"))

    # 5. the rationale: no leak, and no number the LLM wasn't shown
    leaks = leak_scan.find_leaks(output.rationale)
    if leaks:
        failures.append(Failure(RATIONALE, f"the rationale names {sorted(set(leaks))}"))
    stray = _stray_numbers(output.rationale, features, _shown(library, candidates), entry_ids)
    if stray:
        failures.append(Failure(RATIONALE, f"the rationale holds numbers not in the evidence: {stray}"))
    return failures


def passed(failures) -> bool:
    return not failures
