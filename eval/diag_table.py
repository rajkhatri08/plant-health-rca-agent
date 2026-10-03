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
"""

import argparse
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


# ---------- one diagnosis time ----------

def diagnose(at, moments, revs, entry_fault, vocab, rng_seed=BOOTSTRAP_SEED, n_boot=metrics.BOOTSTRAP_N):
    right_of = {f: e for e, f in entry_fault.items() if e in revs}
    family_of = {e: r.family for e, r in revs.items()}
    family_of_fault = {f: family_of[e] for f, e in right_of.items()}
    dev, fa = at_time(moments["dev"], at), at_time(moments["false"], at)
    if not dev:
        raise DiagTableError(f"no dev known-fault case at {at}")
    entries = sorted(revs)

    # the matcher: thresholds and k on the full library's known-fault cases
    m_dev, m_fa = run_matcher(revs, dev, at), run_matcher(revs, fa, at)
    m_t, m_acc, m_short = matcher_threshold(m_dev)
    m_known = [make_case(m, ids(r), matcher.decline(r, m_t), right_of, family_of_fault) for m, r in zip(dev, m_dev)]
    m_false = [make_case(m, ids(r), matcher.decline(r, m_t), right_of, family_of_fault) for m, r in zip(fa, m_fa)]
    k = choose_k(m_known, len(revs))

    out = {"counts": {"known": len(dev), "false_alerts": len(fa)},
           "k": k, "thresholds": {"matcher": {"value": m_t, "accepted": m_acc, "short": m_short}},
           "methods": {"matcher": evaluate(m_known, m_false, family_of, k, entries)},
           "loo": {}, "paired": {}}
    known_by = {"matcher": m_known}

    # forests: trained per time, thresholds on the same known-fault cases
    label_of = {f: e for f, e in right_of.items()}
    models = {}
    for name in ("forest5", "ceiling"):
        train = moments["authoring" if name == "forest5" else "ceiling"]
        model, cols = fit_forest(vocab, train, at, label_of)
        models[name] = (train, cols)
        r_dev, p_dev = forest_output(model, cols, dev)
        t, acc, short = threshold_95(list(map(float, p_dev)), [True] * len(dev))
        r_fa, p_fa = forest_output(model, cols, fa) if fa else ([], [])
        known_cases = [make_case(m, r, p < t, right_of, family_of_fault) for m, r, p in zip(dev, r_dev, p_dev)]
        false_cases = [make_case(m, r, p < t, right_of, family_of_fault) for m, r, p in zip(fa, r_fa, p_fa)]
        out["thresholds"][name] = {"value": t, "accepted": acc, "short": short,
                                   "training_cases": len(at_time(train, at)),
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


# ---------- the run ----------

def run(model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT, watch_path=cw.DEFAULT_OUT,
        normals_path=evidence_normals.DEFAULT_OUT, *, tables_dir=None, allow_dirty=False, repo_root=None,
        now=None, n_boot=metrics.BOOTSTRAP_N):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before any loading
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    tables_dir = Path(tables_dir or DEFAULT_TABLES)
    table_path = tables_dir / f"{stamp}_diag_table.md"
    if table_path.exists():
        raise FileExistsError(f"{table_path} already exists")

    lib = store.load(**ap.library_paths(repo_root))
    revs = {e: inf.stored.revision for e, inf in sorted(lib.in_force(now).items())}
    entry_fault = entry_faults(repo_root)
    missing = [f for f in cases_mod.KNOWN_FAULTS if f not in {entry_fault[e] for e in revs if e in entry_fault}]
    if missing:
        raise DiagTableError(f"known faults without an entry in force: {missing}")
    vocab = forest.plant_vocabulary(repo_root / "library" / "tags.yaml", repo_root / "library" / "loops.yaml")
    inp = cases_mod.load_inputs(model_path, limits_path, watch_path, normals_path, repo_root)

    moments = gather(inp)
    results = {at: diagnose(at, moments, revs, entry_fault, vocab, n_boot=n_boot) for at in TIMES}

    config = {"as_of": now.strftime(ap.TS), "library": {e: f"{e}@r{r.revision}" for e, r in revs.items()},
              **inp.records, "limits_sha256": inp.limits_sha256, "readings": dict(cases_mod.features.READINGS),
              "headline": HEADLINE, "accept": float(ACCEPT), "recall_target": float(RECALL),
              "loo_faults": list(LOO_FAULTS), "bootstrap_n": n_boot,
              "moments": {k: len(v) for k, v in moments.items()}}
    tables_dir.mkdir(parents=True, exist_ok=True)
    table_path.write_text(markdown(results, config))
    record = run_record.write("diag_table", config=config,
                              seeds={"bootstrap": BOOTSTRAP_SEED, "forest": forest.SEED},
                              metrics=numbers(results), outputs={"table": table_path},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    h = results[HEADLINE]["methods"]
    print(f"{HEADLINE}: {results[HEADLINE]['counts']['known']} known-fault cases; top-1 matcher "
          f"{_pct(h['matcher']['top1'])}%, forest-5 {_pct(h['forest5']['top1'])}%, ceiling "
          f"{_pct(h['ceiling']['top1'])}%, random {_pct(h['random']['top1'])}%")
    print(f"table: {table_path}\nrun record: {record}")
    return results, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", type=Path, default=drv.DEFAULT_MODEL)
    parser.add_argument("--limits", type=Path, default=drv.DEFAULT_OUT)
    parser.add_argument("--watch", type=Path, default=cw.DEFAULT_OUT)
    parser.add_argument("--normals", type=Path, default=evidence_normals.DEFAULT_OUT)
    parser.add_argument("--tables", type=Path, default=DEFAULT_TABLES)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true")
    args = parser.parse_args(argv)
    try:
        run(args.model, args.limits, args.watch, args.normals, tables_dir=args.tables,
            allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, evidence_normals.NormalsError, cases_mod.CasesError, DiagTableError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())