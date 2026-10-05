"""The shipped flow's rule (decision 79): the matcher's order, with the LLM as tie-break,
explainer and veto. One function, used by the graph (nodes.ship) and by evaluation, so the two
can't disagree (decision 19). Runtime code: no imports from dataset/, eval/ or ingest/.

Raj implements ship(). The contract:

    ship(output, failures, llm, ranking) -> {
        "decision":    "propose" | "veto" | "evidence",
        "entry_ref":   the proposed entry_id@r<k> (propose only; None otherwise),
        "tie_break":   True when the proposal came from a top block of more than one entry,
        "matcher_top": [refs of the matcher's top block, in ref order],
        "dissent":     None, or (veto only) {"llm_decision", "llm_entry_ref", "rationale",
                       "family_note"},
    }

  output    the LLM's schema-valid output as a JSON dict (state["output"]), or None
  failures  [{"code", "detail"}] (schema or faithfulness), possibly empty
  llm       state["llm"]: the call's result, or {"error": text}
  ranking   the matcher's ranking as JSON blocks (state["ranking"]): [[{"ref", ...}, ...], ...]

The rules (decision 79):
1. evidence:  the LLM gave an error, or there's any failure. No proposal, no dissent: the
              deterministic evidence is shown (decision 75).
2. propose:   the output proposes an entry_ref in the matcher's top block. That entry is the
              proposal. With a one-entry top block it's the matcher's top entry. With a tied top
              block it's the LLM's pick within it (a tie-break, not a re-rank).
3. veto:      anything else. The output proposes an entry outside the top block, declines, or
              answers not_in_library. There's no proposal; dissent holds the LLM's decision, its
              entry_ref (when it proposed one), its rationale, and its family when the answer was
              not_in_library (family_note; None otherwise).
A veto's entry_ref is always None: dissent never becomes a proposal.
"""

DECISIONS = ("propose", "veto", "evidence")


def ship(output, failures, llm, ranking) -> dict:
    raise NotImplementedError("Raj implements the shipped flow's rule (decision 79)")