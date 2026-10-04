"""The agent's dev metrics (decisions 75, 77; PROTOCOL, Diagnosis: Metrics, the keep rule).
Builder side: rows carry labels. Stubs for Raj; every function raises NotImplementedError.

A row is one graph pass, as eval/agent_table.py writes it to calls.jsonl:
  case        the case's builder-side ID ("known", "false" and "loo" cases)
  kind        "known" (a detected dev run of a known fault, full library), "false" (a
              notification on a normal dev run), "loo" (a detected dev run of a left-out
              fault, with its entry removed)
  run, fault  the run number (for the bootstrap) and the fault (0 for "false")
  family      the case's family (None for "false")
  right       the right entry_id; None when the right answer is a decline ("false", "loo")
  stage       "provisional" or "revised";  repeat  0..R-1
  outcome     matcher_declined, declined, not_in_library, failed_check, error, proposed
  entry       the proposed entry_id (None unless proposed)
  answer_family, confidence   from the LLM's output (None without a valid output)
  failures    the failure codes (citation, entry, action, family, rationale, schema)
  candidates  the entry_ids shown to the LLM;  matcher_ranking  the matcher's blocks of
              entry_ids;  matcher_declined  bool
  llm_key, cached, latency_ms, tokens_in, tokens_out, tokens_thinking, error

Scoring, from decisions 75 and 77 (B1, B2):
- A known case is correct when the outcome is proposed and entry == right. Every other
  outcome is no diagnosis: wrong (and counted in wrongly declined).
- A "false" or "loo" case is correct when it's declined. matcher_declined, declined,
  failed_check and error are declines (no diagnosis is a decline on unknowns). not_in_library
  is not a decline (strict leave-one-out); it's the secondary figure.
- For the keep rule only, "unknowns declined" is the loo cases alone, and failed_check and
  error there count as not declined.

Conventions (Claude's, to confirm before any paid run):
- The agent's ranking for top-3: the proposed entry first, then the matcher's blocks with
  that entry removed. A case that isn't proposed has no ranking and is declined.
- Confidence check: over rows with a valid LLM output (outcome declined, not_in_library or
  proposed), accuracy per stated confidence, with correctness as above.
- Miss labels, over known rows that aren't correct: "gate" when the matcher declined (no
  LLM call), "retrieval" when right isn't among the candidates, else "reasoning".
- Agreement: a row's answer is (outcome, entry); a case (case, stage) is stable when all its
  repeats give one answer. Mean agreement is the mean, over cases, of the share of repeats
  giving the case's most common answer.
"""

from eval import diag_metrics as dm  # noqa: F401 (the Case form and the shared metrics)

CORRECT_DECLINES = ("matcher_declined", "declined", "failed_check", "error")
KEEP_RULE = {"better_by": 0.05, "worse_by": 0.02, "metrics": ("top1", "family", "unknowns_declined")}


def to_case(row, *, keep_rule=False):
    """One row as a diag_metrics.Case, scored as the module docstring says. keep_rule=True
    applies B2: a failed_check or error on a "loo" case is not a decline."""
    raise NotImplementedError("Raj implements to_case (decision 77)")


def summary(rows, family_of) -> dict:
    """Over one stage and one repeat's rows, with family_of {entry_id: family} for the
    family credit (diag_metrics.family_credit): {"known", "top1", "top3", "family",
    "wrongly_declined", "false_alerts", "false_alert_declined", "loo", "loo_declined",
    "failed_check", "schema", "errors"} as Fractions or counts (None when a denominator is 0).
    failed_check, schema and errors are counts over all rows."""
    raise NotImplementedError("Raj implements summary")


def keep_rule(agent_by_repeat, matcher) -> dict:
    """PROTOCOL's keep rule on one stage. agent_by_repeat: per repeat, {"top1", "family",
    "unknowns_declined"} (unknowns_declined from to_case(..., keep_rule=True) on loo rows);
    matcher: the same three for the matcher on the same cases.
    Returns {"metrics": {name: {"matcher", "agent_mean", "diff_mean", "diffs"}},
    "better_on": [names >= 5 points better on average and in every repeat],
    "worse_on": [names more than 2 points worse on average], "keep": bool}."""
    raise NotImplementedError("Raj implements keep_rule (PROTOCOL, decision 41)")


def confidence_table(rows) -> dict:
    """{level: {"n", "correct"}} for high, medium and low (module docstring)."""
    raise NotImplementedError("Raj implements confidence_table")


def agreement(rows) -> dict:
    """{"cases", "stable", "mean_agreement", "unstable": [(case, stage), ...] sorted}."""
    raise NotImplementedError("Raj implements agreement")


def miss_labels(rows) -> dict:
    """{"gate", "retrieval", "reasoning"} counts over known rows that aren't correct."""
    raise NotImplementedError("Raj implements miss_labels")


def not_in_library_secondary(rows) -> dict:
    """Over "loo" rows: {"cases", "answers" (outcome not_in_library), "family_correct"
    (answer_family == family among those answers)}."""
    raise NotImplementedError("Raj implements not_in_library_secondary")


def latency_cost(rows, ledger) -> dict:
    """{"calls" (rows with an llm_key), "latency_ms": {"median", "p95", "max"} over those rows
    (linear interpolation), "cost_inr" (sum of the ledger rows' cost_inr for those keys, each
    key once), "cost_per_diagnosis" (cost_inr over all rows)}. ledger is {key: row}."""
    raise NotImplementedError("Raj implements latency_cost")
