"""The agent's dev metrics (decisions 75, 77; PROTOCOL, Diagnosis: Metrics, the keep rule).
Builder side: rows carry labels. Implemented by Raj.

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

Conventions (confirmed by Raj, 4 October 2026; decision 77):
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

import math
from collections import Counter
from decimal import Decimal
from fractions import Fraction

from eval import diag_metrics as dm          # the Case form and the shared metrics

CORRECT_DECLINES = ("matcher_declined", "declined", "failed_check", "error")
KEEP_RULE = {"better_by": 0.05, "worse_by": 0.02, "metrics": ("top1", "family", "unknowns_declined")}
VALID_OUTPUTS = ("declined", "not_in_library", "proposed")       # the LLM gave a valid answer
LEVELS = ("high", "medium", "low")
EPS = 1e-9                                  # "exactly 2 points" must not fail on float rounding


def _declined(row, keep_rule=False) -> bool:
    if row["kind"] == "known":
        return row["outcome"] != "proposed"          # no diagnosis on a known case: wrong
    if keep_rule and row["kind"] == "loo" and row["outcome"] in ("failed_check", "error"):
        return False                                 # B2: a broken answer can't win on unknowns
    return row["outcome"] in CORRECT_DECLINES


def _ranking(row) -> tuple:
    """The agent's pick first, then the matcher's blocks without it; () unless proposed."""
    if row["outcome"] != "proposed":
        return ()
    pick = row["entry"]
    rest = (tuple(e for e in block if e != pick) for block in row["matcher_ranking"])
    return ((pick,),) + tuple(b for b in rest if b)


def _correct(row) -> bool:
    if row["kind"] == "known":
        return row["outcome"] == "proposed" and row["entry"] == row["right"]
    return _declined(row)


def _share(cases):
    return Fraction(sum(c.declined for c in cases), len(cases)) if cases else None


def _quantile(sorted_values, q):
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (pos - lo) * (sorted_values[hi] - sorted_values[lo])


def to_case(row, *, keep_rule=False):
    """One row as a diag_metrics.Case, scored as the module docstring says. keep_rule=True
    applies B2: a failed_check or error on a "loo" case is not a decline."""
    return dm.Case(run=row["run"], fault=row["fault"], family=row["family"], right=row["right"],
                   ranking=_ranking(row), declined=_declined(row, keep_rule))


def summary(rows, family_of) -> dict:
    """Over one stage and one repeat's rows, with family_of {entry_id: family} for the
    family credit (diag_metrics.family_credit): {"known", "top1", "top3", "family",
    "wrongly_declined", "false_alerts", "false_alert_declined", "loo", "loo_declined",
    "failed_check", "schema", "errors"} as Fractions or counts (None when a denominator is 0).
    failed_check, schema and errors are counts over all rows."""
    pairs = [(r["kind"], to_case(r)) for r in rows]
    known = [c for k, c in pairs if k == "known"]
    false = [c for k, c in pairs if k == "false"]
    loo = [c for k, c in pairs if k == "loo"]
    n = len(known)
    return {
        "known": n,
        "top1": dm.topk_credit(known, 1) / n if n else None,
        "top3": dm.topk_credit(known, 3) / n if n else None,
        "family": dm.family_credit(known, family_of) / n if n else None,
        "wrongly_declined": dm.wrongly_declined(known) if n else None,
        "false_alerts": len(false), "false_alert_declined": _share(false),
        "loo": len(loo), "loo_declined": _share(loo),
        "failed_check": sum(r["outcome"] == "failed_check" for r in rows),
        "schema": sum("schema" in (r["failures"] or ()) for r in rows),
        "errors": sum(r["outcome"] == "error" for r in rows),
    }


def keep_rule(agent_by_repeat, matcher) -> dict:
    """PROTOCOL's keep rule on one stage. agent_by_repeat: per repeat, {"top1", "family",
    "unknowns_declined"} (unknowns_declined from to_case(..., keep_rule=True) on loo rows);
    matcher: the same three for the matcher on the same cases.
    Returns {"metrics": {name: {"matcher", "agent_mean", "diff_mean", "diffs"}},
    "better_on": [names >= 5 points better on average and in every repeat],
    "worse_on": [names more than 2 points worse on average], "keep": bool}."""
    metrics, better, worse = {}, [], []
    for name in KEEP_RULE["metrics"]:
        values = [rep[name] for rep in agent_by_repeat]
        if matcher[name] is None or not values or any(v is None for v in values):
            metrics[name] = {"matcher": matcher[name], "agent_mean": None, "diff_mean": None, "diffs": None}
            continue                                 # nothing to compare on this metric
        diffs = [float(v) - float(matcher[name]) for v in values]
        mean = sum(diffs) / len(diffs)
        metrics[name] = {"matcher": float(matcher[name]), "agent_mean": sum(float(v) for v in values) / len(values),
                         "diff_mean": mean, "diffs": diffs}
        if mean >= KEEP_RULE["better_by"] - EPS and all(d >= KEEP_RULE["better_by"] - EPS for d in diffs):
            better.append(name)                      # at least 5 points better, on average and every repeat
        if mean < -KEEP_RULE["worse_by"] - EPS:
            worse.append(name)                       # more than 2 points worse on average
    return {"metrics": metrics, "better_on": better, "worse_on": worse, "keep": bool(better) and not worse}


def confidence_table(rows) -> dict:
    """{level: {"n", "correct"}} for high, medium and low (module docstring)."""
    table = {level: {"n": 0, "correct": 0} for level in LEVELS}
    for r in rows:
        if r["outcome"] in VALID_OUTPUTS and r.get("confidence") in table:
            table[r["confidence"]]["n"] += 1
            table[r["confidence"]]["correct"] += int(_correct(r))
    return table


def agreement(rows) -> dict:
    """{"cases", "stable", "mean_agreement", "unstable": [(case, stage), ...] sorted}."""
    answers = {}
    for r in rows:
        answers.setdefault((r["case"], r["stage"]), []).append((r["outcome"], r.get("entry")))
    shares, unstable = [], []
    for key, given in answers.items():
        shares.append(Counter(given).most_common(1)[0][1] / len(given))
        if len(set(given)) > 1:
            unstable.append(key)
    return {"cases": len(answers), "stable": len(answers) - len(unstable),
            "mean_agreement": sum(shares) / len(shares) if shares else None, "unstable": sorted(unstable)}


def miss_labels(rows) -> dict:
    """{"gate", "retrieval", "reasoning"} counts over known rows that aren't correct."""
    out = {"gate": 0, "retrieval": 0, "reasoning": 0}
    for r in rows:
        if r["kind"] != "known" or _correct(r):
            continue
        if r["matcher_declined"]:
            out["gate"] += 1                         # the LLM was never asked
        elif r["right"] not in (r["candidates"] or ()):
            out["retrieval"] += 1                    # the right entry wasn't shown
        else:
            out["reasoning"] += 1                    # it was shown, and the agent missed it
    return out


def not_in_library_secondary(rows) -> dict:
    """Over "loo" rows: {"cases", "answers" (outcome not_in_library), "family_correct"
    (answer_family == family among those answers)}."""
    loo = [r for r in rows if r["kind"] == "loo"]
    answers = [r for r in loo if r["outcome"] == "not_in_library"]
    return {"cases": len(loo), "answers": len(answers),
            "family_correct": sum(r["answer_family"] == r["family"] for r in answers)}


def latency_cost(rows, ledger) -> dict:
    """{"calls" (rows with an llm_key), "latency_ms": {"median", "p95", "max"} over those rows
    (linear interpolation), "cost_inr" (sum of the ledger rows' cost_inr for those keys, each
    key once), "cost_per_diagnosis" (cost_inr over all rows)}. ledger is {key: row}."""
    called = [r for r in rows if r.get("llm_key")]
    times = sorted(float(r["latency_ms"]) for r in called if r.get("latency_ms") is not None)
    latency = ({"median": _quantile(times, 0.5), "p95": _quantile(times, 0.95), "max": times[-1]}
               if times else {"median": None, "p95": None, "max": None})
    cost = float(sum((Decimal(ledger[k]["cost_inr"]) for k in {r["llm_key"] for r in called} if k in ledger),
                     Decimal(0)))                     # each call's cost once, cache hits included
    return {"calls": len(called), "latency_ms": latency, "cost_inr": cost,
            "cost_per_diagnosis": cost / len(rows) if rows else None}
