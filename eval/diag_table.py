"""The dev diagnosis table: matcher vs forest vs random (week 5's "Done when"; decisions
69-72; PROTOCOL, Diagnosis). Builder side: it uses labels and run numbers.

    python -m eval.diag_table [--model …] [--limits …] [--watch …] [--normals …]
                              [--tables data/tables] [--allow-dirty]

Cases, through eval/cases.py's shared scoring path, built in memory in one run:
- dev known-fault cases: the detected dev runs of the 12 known faults, at the first
  notification after onset (cases.score_pool)
- dev false-alert cases: every notification on a normal dev run (cases.score_normal);
  the right answer is a decline
- training cases: the detected authoring runs (forest-5) and forest_ceiling runs (the
  ceiling forest) of the 12 known faults
A case exists at a diagnosis time only if its reading does (decision 70: a reading past
the run end is left out). Provisional (+30 min) is the headline; revised is reported too.

Methods, per diagnosis time:
- the matcher (app/diagnosis/matcher.py) on every entry in force at the run's time
- forest-5 and the ceiling forest (eval/baselines/forest.py, decision 72), one per time
- the analytic random floor over the N entries in force (no decline)

Rules set on the dev known-fault cases of the full library, per diagnosis time:
- decline thresholds (decisions 69, 72), one for the matcher and one per forest, by
  threshold_95: the highest observed top score that still accepts at least 95% of the
  known-fault cases. A matcher case with a required contradiction everywhere is declined
  whatever the threshold, and counts as not accepted.
- top-k (PROTOCOL): the smallest k with at least 95% matcher candidate recall (choose_k).

Metrics (eval/diag_metrics.py, Raj's): top-1, top-3, family accuracy, wrongly declined,
candidate recall at k, the decline share on false-alert cases, and per-entry results.
Leave-one-out (decisions 70, 72): the entries of LOO_FAULTS are removed from the library,
both forests are retrained without their classes, and those faults' cases are scored with
the main thresholds: correct when declined, with family accuracy alongside. The paired
bootstrap of the top-1 difference (decision 72) compares the matcher with each forest by
run number, B = 2000, seed BOOTSTRAP_SEED.

Writes one diag_table run record and a Markdown table under data/tables/ (gitignored). It
refuses a dirty tree before loading anything, and never overwrites. Prints only counts,
rates and paths.

Week 7 (S1c):
- --library-as-of <ISO> pins the library clock (default: now, as before).
- --fingerprint (dev; needs --library-as-of): also writes a diag_fingerprint record (S1 Q2):
  per diagnosis time, the SHA-256 of the matcher's rankings of every dev case and of each
  forest's full predicted probabilities, with the thresholds and k as exact strings. Raj runs
  it before the freeze; TEST_PLAN names the record.
- --split test --fingerprint-record <record> --library-as-of <ISO> (Raj runs it with
  EVAL_MODE=1, never Claude): re-derives every rule on dev (open data) by the code above and
  stops unless the fingerprint matches exactly (S0 answer 13), and checks the leave-one-out
  refs (S0 answer 16), all before the first test load. Then it scores the testing files at
  onset 160 with those rules, never deriving anything on test: known faults, unknown faults
  16-20 (correct only when declined), leave-one-out on 1, 4, 5 and 13 one at a time (the entry
  removed, both forests refit without its class), and false alerts, over every detected test
  run and over the seed-20261006 subsample of 10 run numbers (S0 answers 12, 14, 15); the
  paired bootstrap on the subsample only. Per-case rows go to the sealed folder (S0 answer
  21); the test_diag_table record and its table hold aggregates only. The LLM-only diagnostic
  isn't run on test (S0 answer 18).
"""

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import numpy as np
import yaml

from app.diagnosis import matcher
from app.library import store
from dataset import loader
from eval import approve_entry as ap
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import cases as cases_mod
from eval import dev_table, evidence_normals, metrics, run_record
from eval import diag_metrics as dm
from eval import split as split_mod
from eval.baselines import forest

TIMES = tuple(matcher.SCOPES)              # ("provisional", "revised")
HEADLINE = "provisional"
ACCEPT = Fraction(95, 100)                 # decline thresholds accept 95% of known-fault dev cases
RECALL = Fraction(95, 100)                 # top-k: at least 95% candidate recall
TOP3 = 3
LOO_FAULTS = (2, 11)                       # PROTOCOL: dev leave-one-out
BOOTSTRAP_SEED = dev_table.BOOTSTRAP_SEED
DEFAULT_TABLES = dev_table.DEFAULT_TABLES
METHODS = ("matcher", "forest5", "ceiling", "random")


class DiagTableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Moment:
    """One diagnosable moment: a detected fault run, or one notification on a normal run."""
    run: int
    fault: int                             # 0 on a normal run
    features: dict


# ---------- the pre-registered rules ----------

def threshold_95(values, eligible, accept=ACCEPT):
    """(threshold, accepted share, short) over the known-fault cases. values are each
    case's top score; eligible says the case can be accepted at all (for the matcher: no
    required contradiction in the top block). The threshold is the highest eligible value
    that accepts at least ceil(accept x N) of the N cases (ties at the threshold are all
    accepted). If even accepting every eligible case falls short, the threshold is the
    lowest eligible value and short is True. Decline is strictly below the threshold."""
    n = len(values)
    if n == 0 or len(eligible) != n:
        raise DiagTableError("threshold_95 needs one value and one eligibility per case")
    ok = sorted((v for v, e in zip(values, eligible) if e), reverse=True)
    if not ok:
        raise DiagTableError("no case can be accepted at any threshold")
    need = math.ceil(accept * n)
    short = len(ok) < need
    t = ok[-1] if short else ok[need - 1]
    accepted = sum(1 for v, e in zip(values, eligible) if e and v >= t)
    return t, Fraction(accepted, n), short


def choose_k(known_cases, n_entries, target=RECALL):
    """The smallest k in 1..n_entries with candidate recall at least target."""
    for k in range(1, n_entries + 1):
        if dm.candidate_recall(known_cases, k) >= target:
            return k
    raise DiagTableError(f"candidate recall never reaches {target} by k = {n_entries}")


# ---------- building cases ----------

def entry_faults(repo_root) -> dict:
    """{entry_id: fault} from the entry key and each provenance file's fault."""
    key = ap.load_entry_key(Path(repo_root) / ap.KEY)
    return {e: int(yaml.safe_load((Path(repo_root) / rel).read_text())["fault"]) for e, rel in key.items()}


def gather(inp) -> dict:
    """{"dev", "false", "authoring", "ceiling"}: the moments for every case and training set."""
    out = {"dev": [], "false": [], "authoring": [], "ceiling": []}
    for pool, name in (("dev", "dev"), ("authoring", "authoring"), ("forest_ceiling", "ceiling")):
        for f in cases_mod.KNOWN_FAULTS:
            runs = loader.load_faulty(f, pool)
            if runs.pool != pool:
                raise DiagTableError(f"asked for {pool}, the loader gave {runs.pool}")
            out[name] += [Moment(r["run"], f, r["features"]) for r in cases_mod.score_pool(inp, runs)
                          if r["detected"]]
    normal = loader.load_normal("dev")
    for r in cases_mod.score_normal(inp, normal):
        out["false"] += [Moment(r["run"], 0, n["features"]) for n in r["notifications"]]
    return out


def at_time(moments, at):
    return [m for m in moments if at in m.features]


def ids(ranking) -> tuple:
    """Matcher blocks of Scores as blocks of entry_ids."""
    return tuple(tuple(s.entry_id for s in block) for block in ranking)


def make_case(m, ranking, declined, right_of, family_of_fault) -> dm.Case:
    right = right_of.get(m.fault)                  # None for a false alert or a left-out entry
    return dm.Case(run=m.run, fault=m.fault, family=family_of_fault.get(m.fault), right=right,
                   ranking=ranking, declined=bool(declined))


# ---------- methods ----------

def run_matcher(revs, moments, at):
    """[matcher ranking (Score blocks)] per moment."""
    return [matcher.rank([matcher.score(r, m.features, at) for r in revs.values()]) for m in moments]


def matcher_threshold(rankings):
    tops = [r[0][0] for r in rankings]
    return threshold_95([s.fit for s in tops], [s.required_contradictions == 0 for s in tops])


def fit_forest(vocab, train, at, label_of, exclude=()):
    cols = forest.columns(vocab, at)
    tr = at_time(train, at)
    X = forest.encode([m.features for m in tr], cols)
    y = np.array([label_of[m.fault] for m in tr])
    if exclude:
        X, y = forest.drop_classes(X, y, exclude)
    return forest.fit(X, y), cols


def forest_output(model, cols, moments):
    X = forest.encode([m.features for m in moments], cols)
    return forest.rankings(model, X), forest.top_probability(model, X)


# ---------- metrics ----------

def per_entry(known_cases, entries) -> dict:
    """{entry: {cases, picked_right, picked_wrong}} over known-fault cases, ties fractional:
    picked_right is the top-1 credit on its own cases; picked_wrong the share of the top
    block it holds on other entries' cases. Declined cases pick nothing."""
    out = {e: {"cases": 0, "picked_right": Fraction(0), "picked_wrong": Fraction(0)} for e in entries}
    for c in known_cases:
        out[c.right]["cases"] += 1
        if c.declined or not c.ranking:
            continue
        top = c.ranking[0]
        for e in top:
            if e in out:
                key = "picked_right" if e == c.right else "picked_wrong"
                out[e][key] += Fraction(1, len(top))
    return out


def evaluate(known, false_alerts, family_of, k, entries) -> dict:
    n = len(known)
    return {"cases": n,
            "top1": dm.topk_credit(known, 1) / n,
            "top3": dm.topk_credit(known, TOP3) / n,
            "family": dm.family_credit(known, family_of) / n,
            "wrongly_declined": dm.wrongly_declined(known),
            "recall_at_k": dm.candidate_recall(known, k),
            "false_alert_cases": len(false_alerts),
            "false_alert_declined": dm.decline_share(false_alerts) if false_alerts else None,
            "per_entry": per_entry(known, entries)}


def evaluate_loo(loo_cases, family_of) -> dict:
    n = len(loo_cases)
    if n == 0:
        return {"cases": 0, "declined": None, "family": None}
    return {"cases": n, "declined": dm.decline_share(loo_cases), "family": dm.family_credit(loo_cases, family_of) / n}


def random_floor(known, false_alerts, revs, family_of_fault, loo_cases=None) -> dict:
    sizes = {}
    for r in revs.values():
        sizes[r.family] = sizes.get(r.family, 0) + 1
    floor = forest.random_floor(len(revs), [sizes.get(c.family, 0) for c in (loo_cases or known)])
    if loo_cases is not None:
        return {"cases": len(loo_cases), "declined": Fraction(0), "family": floor["family"]}
    return {"cases": len(known), "top1": floor["top1"], "top3": floor["top3"], "family": floor["family"],
            "wrongly_declined": Fraction(0), "recall_at_k": None,
            "false_alert_cases": len(false_alerts), "false_alert_declined": Fraction(0) if false_alerts else None}


def numbers(x):
    """Fractions and numpy scalars as floats, for the run record."""
    if isinstance(x, dict):
        return {k: numbers(v) for k, v in x.items()}
    if isinstance(x, (Fraction, np.floating)):
        return float(x)
    return x


# ---------- the rules, set on dev (one diagnosis time) ----------

FORESTS = ("forest5", "ceiling")
TRAINING = {"forest5": "authoring", "ceiling": "ceiling"}


def labels(revs, entry_fault):
    """(right_of {fault: entry}, family_of {entry: family}, family_of_fault {fault: family})."""
    right_of = {f: e for e, f in entry_fault.items() if e in revs}
    family_of = {e: r.family for e, r in revs.items()}
    return right_of, family_of, {f: family_of[e] for f, e in right_of.items()}


def derive_rules(at, moments, revs, entry_fault, vocab) -> dict:
    """The pre-registered rules at one diagnosis time, set on the dev known-fault cases of
    the full library (decisions 69, 72; PROTOCOL top-k): the matcher's threshold and k, and
    each forest (fitted on its training runs) with its threshold. Also returns what they were
    set on (the dev and dev false-alert moments, the matcher's rankings, the forests' outputs),
    so the dev table, the fingerprint and the test run all use one derivation."""
    right_of, _, family_of_fault = labels(revs, entry_fault)
    dev, fa = at_time(moments["dev"], at), at_time(moments["false"], at)
    if not dev:
        raise DiagTableError(f"no dev known-fault case at {at}")
    m_dev, m_fa = run_matcher(revs, dev, at), run_matcher(revs, fa, at)
    m_t, m_acc, m_short = matcher_threshold(m_dev)
    m_known = [make_case(m, ids(r), matcher.decline(r, m_t), right_of, family_of_fault) for m, r in zip(dev, m_dev)]
    k = choose_k(m_known, len(revs))
    rules = {"at": at, "dev": dev, "false": fa, "k": k,
             "matcher": {"value": m_t, "accepted": m_acc, "short": m_short, "dev": m_dev, "false": m_fa},
             "forests": {}}
    for name in FORESTS:
        train = moments[TRAINING[name]]
        model, cols = fit_forest(vocab, train, at, right_of)
        r_dev, p_dev = forest_output(model, cols, dev)
        t, acc, short = threshold_95(list(map(float, p_dev)), [True] * len(dev))
        rules["forests"][name] = {"model": model, "cols": cols, "value": t, "accepted": acc, "short": short,
                                  "training_cases": len(at_time(train, at)), "train": train,
                                  "dev": (r_dev, p_dev)}
    return rules


# ---------- one diagnosis time on dev ----------

def diagnose(at, moments, revs, entry_fault, vocab, rng_seed=BOOTSTRAP_SEED, n_boot=metrics.BOOTSTRAP_N,
             rules=None):
    right_of, family_of, family_of_fault = labels(revs, entry_fault)
    rules = rules or derive_rules(at, moments, revs, entry_fault, vocab)
    dev, fa = rules["dev"], rules["false"]
    entries = sorted(revs)

    # the matcher: thresholds and k on the full library's known-fault cases
    m_dev, m_fa = rules["matcher"]["dev"], rules["matcher"]["false"]
    m_t, m_acc, m_short = (rules["matcher"][x] for x in ("value", "accepted", "short"))
    m_known = [make_case(m, ids(r), matcher.decline(r, m_t), right_of, family_of_fault) for m, r in zip(dev, m_dev)]
    m_false = [make_case(m, ids(r), matcher.decline(r, m_t), right_of, family_of_fault) for m, r in zip(fa, m_fa)]
    k = rules["k"]

    out = {"counts": {"known": len(dev), "false_alerts": len(fa)},
           "k": k, "thresholds": {"matcher": {"value": m_t, "accepted": m_acc, "short": m_short}},
           "methods": {"matcher": evaluate(m_known, m_false, family_of, k, entries)},
           "loo": {}, "paired": {}}
    known_by = {"matcher": m_known}

    # forests: trained per time, thresholds on the same known-fault cases
    label_of = {f: e for f, e in right_of.items()}
    models = {}
    for name in FORESTS:
        fr = rules["forests"][name]
        model, cols, t, train = fr["model"], fr["cols"], fr["value"], fr["train"]
        models[name] = (train, cols)
        r_dev, p_dev = fr["dev"]
        r_fa, p_fa = forest_output(model, cols, fa) if fa else ([], [])
        known_cases = [make_case(m, r, p < t, right_of, family_of_fault) for m, r, p in zip(dev, r_dev, p_dev)]
        false_cases = [make_case(m, r, p < t, right_of, family_of_fault) for m, r, p in zip(fa, r_fa, p_fa)]
        out["thresholds"][name] = {"value": t, "accepted": fr["accepted"], "short": fr["short"],
                                   "training_cases": fr["training_cases"],
                                   "classes": len(model.classes_)}
        out["methods"][name] = evaluate(known_cases, false_cases, family_of, k, entries)
        known_by[name] = known_cases
    out["methods"]["random"] = random_floor(m_known, m_false, revs, family_of_fault)

    # leave-one-out: entries removed, forests retrained, the main thresholds kept
    left_out = [right_of[f] for f in LOO_FAULTS]
    loo_revs = {e: r for e, r in revs.items() if e not in left_out}
    loo_moments = [m for m in dev if m.fault in LOO_FAULTS]
    loo_right = {f: e for f, e in right_of.items() if e not in left_out}
    r_loo = run_matcher(loo_revs, loo_moments, at)
    out["loo"]["matcher"] = evaluate_loo(
        [make_case(m, ids(r), matcher.decline(r, m_t), loo_right, family_of_fault) for m, r in zip(loo_moments, r_loo)],
        family_of)
    for name in ("forest5", "ceiling"):
        train, _ = models[name]
        model, cols = fit_forest(vocab, train, at, label_of, exclude=left_out)
        if loo_moments:
            r, p = forest_output(model, cols, loo_moments)
            loo_cases = [make_case(m, rr, pp < out["thresholds"][name]["value"], loo_right, family_of_fault)
                         for m, rr, pp in zip(loo_moments, r, p)]
        else:
            loo_cases = []
        out["loo"][name] = {**evaluate_loo(loo_cases, family_of), "classes": len(model.classes_)}
    loo_cases_known = [make_case(m, (), False, loo_right, family_of_fault) for m in loo_moments]
    out["loo"]["random"] = random_floor(None, None, loo_revs, family_of_fault, loo_cases=loo_cases_known) \
        if loo_moments else {"cases": 0, "declined": None, "family": None}
    out["loo"]["left_out"] = {str(f): right_of[f] for f in LOO_FAULTS}

    # paired bootstrap of the top-1 difference, by run number
    runs_with_known = {c.run for c in m_known}
    for name in ("forest5", "ceiling"):
        if {c.run for c in known_by[name]} != runs_with_known:
            raise DiagTableError("the methods must be scored on the same cases")
        diff, lo, hi = dm.paired_top1_bootstrap(m_known, known_by[name], np.random.default_rng(rng_seed), n=n_boot)
        out["paired"][f"matcher_vs_{name}"] = {"difference": diff, "lo": lo, "hi": hi}
    return out


# ---------- the fingerprint (S1 Q2; S0 answer 13) ----------

def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, separators=(",", ":")).encode()).hexdigest()


def _ranking_rows(rankings):
    return [[[[s.entry_id, str(s.fit), int(s.required_contradictions)] for s in block] for block in r]
            for r in rankings]


def fingerprint(rules) -> dict:
    """Exactly what the rules were set from, at one diagnosis time: the matcher's rankings of
    every dev known-fault and false-alert case (entries, exact fits, contradictions), each
    forest's full predicted probabilities on the same cases (float64 bytes, with its class
    order), and the thresholds and k as exact strings. Two runs agree only if every case does."""
    out = {"k": rules["k"],
           "matcher": {"threshold": str(rules["matcher"]["value"]), "accepted": str(rules["matcher"]["accepted"]),
                       "short": bool(rules["matcher"]["short"]),
                       "rankings_sha256": _sha(_ranking_rows(rules["matcher"]["dev"] + rules["matcher"]["false"]))},
           "cases": {"known": len(rules["dev"]), "false_alerts": len(rules["false"])}}
    for name in FORESTS:
        fr = rules["forests"][name]
        h = hashlib.sha256(json.dumps([str(c) for c in fr["model"].classes_]).encode())
        for moments in (rules["dev"], rules["false"]):
            if moments:
                p = fr["model"].predict_proba(forest.encode([m.features for m in moments], fr["cols"]))
                h.update(np.ascontiguousarray(p, dtype="<f8").tobytes())
        out[name] = {"threshold": repr(float(fr["value"])), "accepted": str(fr["accepted"]),
                     "short": bool(fr["short"]), "training_cases": fr["training_cases"],
                     "classes": len(fr["model"].classes_), "proba_sha256": h.hexdigest()}
    return out


def load_fingerprint(path, repo_root, config) -> tuple:
    """(relative path, metrics) of a clean diag_fingerprint record whose library as-of, library
    and inputs equal config's. Raises DiagTableError otherwise."""
    path = Path(path)
    if not path.name.endswith("_diag_fingerprint.json"):
        raise DiagTableError(f"{path} isn't a diag_fingerprint run record")
    rec = json.loads(path.read_text())
    if rec.get("dirty") is not False:
        raise DiagTableError(f"{path} was made on a dirty tree; the fingerprint must be clean")
    for key in ("as_of", "library", "calibration_record", "watch_record", "normals_record", "limits_sha256"):
        if rec["config"].get(key) != config[key]:
            raise DiagTableError(f"the fingerprint's {key} isn't this run's: {rec['config'].get(key)!r}")
    return path.resolve().relative_to(Path(repo_root).resolve()).as_posix(), rec["metrics"]


# ---------- the test split (week 7 S1c; Raj runs it with EVAL_MODE=1) ----------

UNKNOWN_FAULTS = tuple(loader.QUARANTINED_FAULTS)        # 16-20: no entry, a decline is right
LOO_TEST = {1: "mixed-feed-reactant-ratio-shift", 4: "reactor-cooling-water-warm-supply",   # S0 answer 16
            5: "condenser-cooling-water-warm-supply", 13: "reaction-rate-drift"}
LOO_TEST_REVISION = 1


def check_loo_refs(revs, right_of):
    """S0 answer 16: each test leave-one-out fault's entry is the named one, at r1."""
    for f, e in LOO_TEST.items():
        if right_of.get(f) != e or e not in revs or revs[e].revision != LOO_TEST_REVISION:
            raise DiagTableError(f"leave-one-out fault {f} should remove {e}@r{LOO_TEST_REVISION}; "
                                 f"the library has {right_of.get(f)}")


def gather_test(inp, sp) -> dict:
    """{"known", "unknown", "false": [Moment], "runs": {fault: runs scored}}: the detected
    testing runs of the 12 known faults and of 16-20 at the split's onset, and every
    notification on every normal testing run. Every file load goes through the split."""
    out = {"known": [], "unknown": [], "false": [], "runs": {}}
    for f in cases_mod.KNOWN_FAULTS + UNKNOWN_FAULTS:
        runs = sp.load_faulty(f)
        if runs.pool != "test":
            raise DiagTableError(f"asked for the test split, the loader gave {runs.pool}")
        per_run = cases_mod.score_pool(inp, runs, onset=sp.onset)
        out["runs"][f] = len(per_run)
        kind = "known" if f in cases_mod.KNOWN_FAULTS else "unknown"
        out[kind] += [Moment(r["run"], f, r["features"]) for r in per_run if r["detected"]]
    for r in cases_mod.score_normal(inp, sp.load_normal()):
        out["false"] += [Moment(r["run"], 0, n["features"]) for n in r["notifications"]]
    return out


def _unknown_summary(cases) -> dict:
    by = {}
    for c in cases:
        by.setdefault(c.fault, []).append(c)
    return {"cases": len(cases), "declined": dm.decline_share(cases) if cases else None,
            "by_fault": {str(f): {"cases": len(by.get(f, [])),
                                  "declined": dm.decline_share(by[f]) if by.get(f) else None}
                         for f in UNKNOWN_FAULTS}}


def diagnose_test(rules, test, revs, entry_fault, vocab, draw, n_boot=metrics.BOOTSTRAP_N):
    """(results, per-case rows) at one diagnosis time, with the rules set on dev and never
    on test. Two scopes: "full" (every detected testing run, every normal-run notification)
    and "subsample" (the runs in draw, for every fault and the normal runs; S0 answer 14).
    Known faults: the usual metrics. Faults 16-20: correct only when declined, no family.
    Leave-one-out on 1, 4, 5 and 13, one at a time (S0 answer 16): that entry removed, both
    forests refit without its class, the full library's thresholds; correct only when
    declined, family accuracy alongside. The paired bootstrap is on the subsample only."""
    at, k = rules["at"], rules["k"]
    right_of, family_of, family_of_fault = labels(revs, entry_fault)
    entries = sorted(revs)
    kn, un, fa = (at_time(test[x], at) for x in ("known", "unknown", "false"))
    m_t = rules["matcher"]["value"]

    def matcher_cases(revs_, moments, right):
        return [make_case(m, ids(r), matcher.decline(r, m_t), right, family_of_fault)
                for m, r in zip(moments, run_matcher(revs_, moments, at))]

    def forest_cases(model, cols, t, moments, right):
        if not moments:
            return []
        r, p = forest_output(model, cols, moments)
        return [make_case(m, rr, pp < t, right, family_of_fault) for m, rr, pp in zip(moments, r, p)]

    # every method on every case, once; each scope is a filter by run number
    cases = {"matcher": [matcher_cases(revs, ms, right_of) for ms in (kn, un, fa)]}
    for name in FORESTS:
        fr = rules["forests"][name]
        cases[name] = [forest_cases(fr["model"], fr["cols"], fr["value"], ms, right_of) for ms in (kn, un, fa)]
    loo = {}
    for f, e in LOO_TEST.items():
        ms = [m for m in kn if m.fault == f]
        loo_right = {g: x for g, x in right_of.items() if x != e}
        loo[f] = {"matcher": matcher_cases({x: r for x, r in revs.items() if x != e}, ms, loo_right),
                  "random": [make_case(m, (), False, loo_right, family_of_fault) for m in ms],
                  "revs": {x: r for x, r in revs.items() if x != e}}
        for name in FORESTS:
            fr = rules["forests"][name]
            model, cols = fit_forest(vocab, fr["train"], at, right_of, exclude=[e])
            loo[f][name] = forest_cases(model, cols, fr["value"], ms, loo_right)
            loo[f][f"{name}_classes"] = len(model.classes_)

    keep_all = lambda cs: cs                                               # noqa: E731
    keep_draw = lambda cs: [c for c in cs if c.run in set(draw)]           # noqa: E731
    n_runs = {"full": sum(test["runs"][f] for f in cases_mod.KNOWN_FAULTS),
              "subsample": len(draw) * len(cases_mod.KNOWN_FAULTS)}
    results = {"rules": {"k": k, "matcher": str(m_t),
                         **{name: repr(float(rules["forests"][name]["value"])) for name in FORESTS}}}
    for scope, keep in (("full", keep_all), ("subsample", keep_draw)):
        r = {"counts": {"known": len(keep(cases["matcher"][0])), "unknown": len(keep(cases["matcher"][1])),
                        "false_alerts": len(keep(cases["matcher"][2])), "known_fault_runs": n_runs[scope]},
             "methods": {}, "unknown": {}, "loo": {}}
        for name in ("matcher", *FORESTS):
            known, unknown, false = (keep(cs) for cs in cases[name])
            if not known:
                raise DiagTableError(f"no known-fault test case in the {scope} scope at {at}")
            r["methods"][name] = {**evaluate(known, false, family_of, k, entries),
                                  "end_to_end_top1": dm.topk_credit(known, 1) / n_runs[scope]}
            r["unknown"][name] = _unknown_summary(unknown)
        mk, mf = keep(cases["matcher"][0]), keep(cases["matcher"][2])
        r["methods"]["random"] = {**random_floor(mk, mf, revs, family_of_fault),
                                  "end_to_end_top1": Fraction(len(mk), n_runs[scope]) / len(revs)}
        r["unknown"]["random"] = {"cases": len(keep(cases["matcher"][1])), "declined": Fraction(0)}
        for f in LOO_TEST:
            lo = loo[f]
            row = {name: {**evaluate_loo(keep(lo[name]), family_of)} for name in ("matcher", *FORESTS)}
            for name in FORESTS:
                row[name]["classes"] = lo[f"{name}_classes"]
            rand = keep(lo["random"])
            row["random"] = (random_floor(None, None, lo["revs"], family_of_fault, loo_cases=rand) if rand
                             else {"cases": 0, "declined": None, "family": None})
            r["loo"][str(f)] = {"left_out": LOO_TEST[f], **row}
        if scope == "subsample":
            r["paired"] = {}
            for name in FORESTS:
                diff, lo_, hi_ = dm.paired_top1_bootstrap(mk, keep(cases[name][0]),
                                                          np.random.default_rng(BOOTSTRAP_SEED), n=n_boot)
                r["paired"][f"matcher_vs_{name}"] = {"difference": diff, "lo": lo_, "hi": hi_}
        results[scope] = r

    rows = []
    for name in ("matcher", *FORESTS):
        for kind, cs in zip(("known", "unknown", "false"), cases[name]):
            rows += [_case_row(at, name, kind, c, draw) for c in cs]
        for f in LOO_TEST:
            rows += [_case_row(at, name, f"loo_{f}", c, draw) for c in loo[f][name]]
    return results, rows


def _case_row(at, method, kind, c, draw) -> dict:
    """One per-case row for the sealed folder (S0 answer 21): never in a committed record."""
    return {"time": at, "method": method, "kind": kind, "fault": c.fault, "run": c.run,
            "in_draw": c.run in draw, "right": c.right, "declined": c.declined,
            "top": list(c.ranking[0]) if c.ranking else None}


# ---------- the Markdown table ----------

def _pct(x):
    return "—" if x is None else f"{100 * float(x):.1f}"


def markdown(results, config) -> str:
    lines = ["# Dev diagnosis table", "",
             f"Library as of {config['as_of']}: {len(config['library'])} entries in force. "
             f"Provisional (+30 min) is the headline. Rates in %.", ""]
    for at in TIMES:
        r = results[at]
        lines += [f"## {at.capitalize()}{' (headline)' if at == HEADLINE else ''}", "",
                  f"{r['counts']['known']} known-fault cases, {r['counts']['false_alerts']} false-alert cases; "
                  f"top-k = {r['k']}.", "",
                  "| Method | Top-1 | Top-3 | Family | Wrongly declined | Recall at k | False alerts declined | Threshold |",
                  "|---|---|---|---|---|---|---|---|"]
        for name in METHODS:
            m = r["methods"][name]
            th = r["thresholds"].get(name)
            th_s = "none" if th is None else f"{float(th['value']):.3f}{' (short)' if th['short'] else ''}"
            lines.append(f"| {name} | {_pct(m['top1'])} | {_pct(m['top3'])} | {_pct(m['family'])} | "
                         f"{_pct(m['wrongly_declined'])} | {_pct(m['recall_at_k'])} | "
                         f"{_pct(m['false_alert_declined'])} | {th_s} |")
        lines += ["", "Leave-one-out (" + ", ".join(r["loo"]["left_out"].values()) + " removed):", "",
                  "| Method | Cases | Declined (correct) | Family |", "|---|---|---|---|"]
        for name in METHODS:
            m = r["loo"][name]
            lines.append(f"| {name} | {m['cases']} | {_pct(m['declined'])} | {_pct(m['family'])} |")
        lines += ["", "Paired bootstrap of the top-1 difference (points, 95% interval):", ""]
        for key, p in r["paired"].items():
            lines.append(f"- {key.replace('_', ' ')}: {100 * float(p['difference']):+.1f} "
                         f"({100 * p['lo']:+.1f} to {100 * p['hi']:+.1f})")
        lines += ["", "Per entry (matcher): cases, picked when right, picked when wrong:", "",
                  "| Entry | Cases | Right | Wrong |", "|---|---|---|---|"]
        for e, v in r["methods"]["matcher"]["per_entry"].items():
            lines.append(f"| {e} | {v['cases']} | {float(v['picked_right']):.1f} | {float(v['picked_wrong']):.1f} |")
        lines.append("")
    return "\n".join(lines)


def markdown_test(results, config) -> str:
    """The test diagnosis table: aggregates only, like the record it's rendered from."""
    lines = ["# Test diagnosis table", "",
             f"Library as of {config['as_of']}: {len(config['library'])} entries in force. Rules (thresholds, k, "
             f"forests) set on dev and checked against `{config['fingerprint_record']}` before any test load. "
             f"Subsample: {config['subsample']['runs']} run numbers, seed {config['subsample']['seed']}. "
             "Provisional (+30 min) is the headline. Rates in %.", ""]
    for at in TIMES:
        res = results[at]
        lines += [f"## {at.capitalize()}{' (headline)' if at == HEADLINE else ''}", "",
                  f"Rules: matcher threshold {res['rules']['matcher']}, forest-5 {float(res['rules']['forest5']):.3f}, "
                  f"ceiling {float(res['rules']['ceiling']):.3f}, top-k = {res['rules']['k']}.", ""]
        for scope in ("full", "subsample"):
            r = res[scope]
            c = r["counts"]
            lines += [f"### {'All detected test runs' if scope == 'full' else 'The subsample'}", "",
                      f"{c['known']} known-fault cases from {c['known_fault_runs']} known-fault runs, "
                      f"{c['unknown']} unknown-fault cases (16–20), {c['false_alerts']} false-alert cases.", "",
                      "| Method | Top-1 | Top-3 | Family | Wrongly declined | Recall at k | End-to-end top-1 | "
                      "False alerts declined | Unknowns declined (16–20) |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for name in METHODS:
                m, u = r["methods"][name], r["unknown"][name]
                lines.append(f"| {name} | {_pct(m['top1'])} | {_pct(m['top3'])} | {_pct(m['family'])} | "
                             f"{_pct(m['wrongly_declined'])} | {_pct(m['recall_at_k'])} | {_pct(m['end_to_end_top1'])} | "
                             f"{_pct(m['false_alert_declined'])} | {_pct(u['declined'])} |")
            lines += ["", "Unknown faults declined, by fault (correct only when declined):", "",
                      "| Method | " + " | ".join(str(f) for f in UNKNOWN_FAULTS) + " |",
                      "|---|" + "---|" * len(UNKNOWN_FAULTS)]
            for name in ("matcher", *FORESTS):
                by = r["unknown"][name]["by_fault"]
                lines.append(f"| {name} | " + " | ".join(
                    f"{_pct(by[str(f)]['declined'])} ({by[str(f)]['cases']})" for f in UNKNOWN_FAULTS) + " |")
            lines += ["", "Leave-one-out, one entry removed at a time (correct only when declined; family alongside):",
                      "", "| Fault | Entry removed | Method | Cases | Declined | Family |", "|---|---|---|---|---|---|"]
            for f, row in r["loo"].items():
                for name in METHODS:
                    m = row[name]
                    lines.append(f"| {f} | {row['left_out']} | {name} | {m['cases']} | {_pct(m['declined'])} | "
                                 f"{_pct(m['family'])} |")
            if "paired" in r:
                lines += ["", "Paired bootstrap of the top-1 difference (points, 95% interval; subsample only):", ""]
                for key, p in r["paired"].items():
                    lines.append(f"- {key.replace('_', ' ')}: {100 * float(p['difference']):+.1f} "
                                 f"({100 * p['lo']:+.1f} to {100 * p['hi']:+.1f})")
            lines.append("")
    return "\n".join(lines)


# ---------- the run ----------

def run(model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT, watch_path=cw.DEFAULT_OUT,
        normals_path=evidence_normals.DEFAULT_OUT, *, tables_dir=None, allow_dirty=False, repo_root=None,
        now=None, n_boot=metrics.BOOTSTRAP_N, split="dev", library_as_of=None, fingerprint_out=False,
        fingerprint_record=None):
    """The dev table (the default), optionally also writing the diag_fingerprint record
    (fingerprint_out, which needs library_as_of); or, with split="test", the test table:
    the rules re-derived on dev and checked against fingerprint_record before any test load."""
    if split not in ("dev", "test"):
        raise DiagTableError(f"unknown split {split!r}")
    if split == "test" and (fingerprint_record is None or library_as_of is None or fingerprint_out):
        raise DiagTableError("--split test needs --fingerprint-record and --library-as-of, and no --fingerprint")
    if split == "dev" and fingerprint_record is not None:
        raise DiagTableError("--fingerprint-record is only for --split test")
    if fingerprint_out and library_as_of is None:
        raise DiagTableError("--fingerprint needs --library-as-of, so the library is pinned")
    if library_as_of is not None and library_as_of.tzinfo is None:
        raise DiagTableError("--library-as-of needs a time zone, e.g. 2026-10-05T00:00:00+00:00")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    lib_t = library_as_of or now
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    tables_dir = Path(tables_dir or DEFAULT_TABLES)
    name = "test_diag_table" if split == "test" else "diag_table"
    table_path = tables_dir / f"{stamp}_{name}.md"
    if table_path.exists():
        raise FileExistsError(f"{table_path} already exists")

    lib = store.load(**ap.library_paths(repo_root))
    revs = {e: inf.stored.revision for e, inf in sorted(lib.in_force(lib_t).items())}
    entry_fault = entry_faults(repo_root)
    missing = [f for f in cases_mod.KNOWN_FAULTS if f not in {entry_fault[e] for e in revs if e in entry_fault}]
    if missing:
        raise DiagTableError(f"known faults without an entry in force: {missing}")
    vocab = forest.plant_vocabulary(repo_root / "library" / "tags.yaml", repo_root / "library" / "loops.yaml")
    inp = cases_mod.load_inputs(model_path, limits_path, watch_path, normals_path, repo_root)
    base_config = {"as_of": lib_t.strftime(ap.TS), "library": {e: f"{e}@r{r.revision}" for e, r in revs.items()},
                   **inp.records, "limits_sha256": inp.limits_sha256}
    if split == "test":
        return _run_test(inp, revs, entry_fault, vocab, base_config, fingerprint_record, repo_root, tables_dir,
                         table_path, commit, dirty, now, n_boot)

    moments = gather(inp)
    rules = {at: derive_rules(at, moments, revs, entry_fault, vocab) for at in TIMES}
    results = {at: diagnose(at, moments, revs, entry_fault, vocab, n_boot=n_boot, rules=rules[at]) for at in TIMES}

    config = {**base_config, "readings": dict(cases_mod.features.READINGS),
              "headline": HEADLINE, "accept": float(ACCEPT), "recall_target": float(RECALL),
              "loo_faults": list(LOO_FAULTS), "bootstrap_n": n_boot,
              "moments": {k: len(v) for k, v in moments.items()}}
    tables_dir.mkdir(parents=True, exist_ok=True)
    table_path.write_text(markdown(results, config))
    seeds = {"bootstrap": BOOTSTRAP_SEED, "forest": forest.SEED}
    record = run_record.write("diag_table", config=config, seeds=seeds,
                              metrics=numbers(results), outputs={"table": table_path},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    if fingerprint_out:
        fp = run_record.write("diag_fingerprint", config={**base_config, "moments": config["moments"]},
                              seeds=seeds, metrics={at: fingerprint(rules[at]) for at in TIMES}, outputs={},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
        print(f"fingerprint record: {fp}")
    h = results[HEADLINE]["methods"]
    print(f"{HEADLINE}: {results[HEADLINE]['counts']['known']} known-fault cases; top-1 matcher "
          f"{_pct(h['matcher']['top1'])}%, forest-5 {_pct(h['forest5']['top1'])}%, ceiling "
          f"{_pct(h['ceiling']['top1'])}%, random {_pct(h['random']['top1'])}%")
    print(f"table: {table_path}\nrun record: {record}")
    return results, record


def _run_test(inp, revs, entry_fault, vocab, base_config, fingerprint_record, repo_root, tables_dir,
              table_path, commit, dirty, now, n_boot):
    """The test table. Order: the rules re-derived on dev and checked against the fingerprint
    (stop on any mismatch), the leave-one-out refs checked, and only then the test loads."""
    right_of, _, _ = labels(revs, entry_fault)
    check_loo_refs(revs, right_of)
    fp_rel, fp_metrics = load_fingerprint(fingerprint_record, repo_root, base_config)
    moments = gather(inp)                                         # dev and training runs: open data
    rules = {at: derive_rules(at, moments, revs, entry_fault, vocab) for at in TIMES}
    now_fp = run_record.clean_metrics({at: fingerprint(rules[at]) for at in TIMES})
    if now_fp != fp_metrics:
        differ = sorted(f"{at}.{key}" for at in TIMES for key in now_fp[at]
                        if now_fp[at][key] != fp_metrics.get(at, {}).get(key))
        raise DiagTableError(f"the rules re-derived on dev don't match {fp_rel} ({', '.join(differ)}); "
                             "nothing from the test split was loaded")

    sp = split_mod.get("test", "test_diag_table")                 # first test load is below
    draw = split_mod.test_draw()
    test = gather_test(inp, sp)
    results, rows = {}, []
    for at in TIMES:
        results[at], at_rows = diagnose_test(rules[at], test, revs, entry_fault, vocab, draw, n_boot=n_boot)
        rows += at_rows

    out_dir = sp.out_dir(None, f"{now.strftime('%Y%m%dT%H%M%SZ')}_test_diag_table")
    out_dir.mkdir(parents=True, exist_ok=False)
    cases_path = out_dir / "cases.jsonl"
    with open(cases_path, "x") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    config = {**base_config, "split": "test", "fingerprint_record": fp_rel,
              "readings": dict(cases_mod.features.READINGS), "headline": HEADLINE,
              "subsample": {"seed": split_mod.TEST_SEED, "runs": split_mod.TEST_DRAW},
              "unknown_faults": list(UNKNOWN_FAULTS),
              "loo_test": {str(f): f"{e}@r{LOO_TEST_REVISION}" for f, e in LOO_TEST.items()},
              "bootstrap_n": n_boot, "llm_only": "not run (S0 answer 18)",
              "moments": {"dev": len(moments["dev"]), "false": len(moments["false"]),
                          "authoring": len(moments["authoring"]), "ceiling": len(moments["ceiling"]),
                          "test_known": len(test["known"]), "test_unknown": len(test["unknown"]),
                          "test_false": len(test["false"])}}
    tables_dir.mkdir(parents=True, exist_ok=True)
    table_path.write_text(markdown_test(numbers(results), config))
    record = run_record.write("test_diag_table", config=config,
                              seeds={"bootstrap": BOOTSTRAP_SEED, "forest": forest.SEED,
                                     "subsample": split_mod.TEST_SEED},
                              metrics=numbers(results), outputs={"table": table_path, "cases": cases_path},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    h = results[HEADLINE]["subsample"]["methods"]
    print(f"test, {HEADLINE}, subsample: top-1 matcher {_pct(h['matcher']['top1'])}%, forest-5 "
          f"{_pct(h['forest5']['top1'])}%, ceiling {_pct(h['ceiling']['top1'])}%")
    print(f"table: {table_path}\nrun record: {record}")
    return results, record


def _as_of(text):
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO time: {text!r}") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--watch", type=Path, default=cw.DEFAULT_OUT)
    parser.add_argument("--normals", type=Path, default=evidence_normals.DEFAULT_OUT)
    parser.add_argument("--tables", type=Path, default=DEFAULT_TABLES)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true (a test load refuses anyway)")
    parser.add_argument("--split", choices=split_mod.NAMES, default="dev",
                        help="test: the sealed testing files, only with EVAL_MODE=1 (Raj runs it)")
    parser.add_argument("--library-as-of", type=_as_of, default=None,
                        help="pin the library clock (ISO with a time zone); default now on dev")
    parser.add_argument("--fingerprint", action="store_true",
                        help="dev: also write the diag_fingerprint record (needs --library-as-of)")
    parser.add_argument("--fingerprint-record", type=Path, default=None,
                        help="test: the diag_fingerprint record the dev rules must reproduce")
    args = parser.parse_args(argv)
    try:
        run(args.model, args.limits, args.watch, args.normals, tables_dir=args.tables,
            allow_dirty=args.allow_dirty, split=args.split, library_as_of=args.library_as_of,
            fingerprint_out=args.fingerprint, fingerprint_record=args.fingerprint_record)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, evidence_normals.NormalsError, cases_mod.CasesError, DiagTableError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())