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
              that isn't in the evidence. The evidence is states only, so the only digits
              allowed are those inside tag and loop IDs (for example RX-FV-206,
              CP-FIC-501).

A failed output isn't shown as a diagnosis: the deterministic evidence is shown with "the
explanation failed a check", it scores as no diagnosis, it's counted separately, and it's
never retried (decision 75). That handling is the graph's (S5); this module only judges.

Raj implements check(). The rest is wiring.
"""

from dataclasses import dataclass

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
    raise NotImplementedError("Raj implements the faithfulness check (decision 75)")


def passed(failures) -> bool:
    return not failures