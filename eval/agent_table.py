"""The agent's dev evaluation driver (decisions 75-77; PROTOCOL, Diagnosis and LLM
measurement). Builder side: it reads labels and run numbers.

    python -m eval.agent_table --dry-run      --library-as-of 2026-10-05T00:00:00+00:00
    python -m eval.agent_table --project-cost --library-as-of …
    python -m eval.agent_table --tuning       --library-as-of … --budget 50
    python -m eval.agent_table --evaluation   --library-as-of … --prompt-sha256 <hash> [--budget 500]
    python -m eval.agent_table --table eval/runs/<stamp>_agent_run.json

One scoring engine (decision 19): cases come from eval/cases.py unchanged, and every
diagnosis runs through the real graph (app/agent/graph.py, Raj's nodes) on the real tools
(app/agent/tools.py on bundle pca_v3), stopping at the approval pause; nothing is approved
and nothing acts. Each case's history is its run, built exactly as the replay export
builds the demo's stream (ingest/export_replay.publications), on the replay's plant clock.
The evidence the graph reads is checked against eval/cases.py's features for every case and
stage: a mismatch stops the run.

Cases (decision 77):
- known: the detected dev runs of the 12 known faults, full library
- false: every notification on a normal dev run (decision 70); the right answer is a decline
- loo: the detected dev runs of faults 2 and 11 with their entries removed (decision 70)
Subsets, by run number (decision 49; one draw shared by every fault, see "to confirm"):
- evaluation: EVAL_RUNS dev run numbers (seed 20261004): their known cases, plus every
  false and loo case; REPEATS repeats; both diagnosis times
- tuning: TUNE_RUNS other dev run numbers (seed 20261005), disjoint: their known cases; 1 repeat

The matcher's decline thresholds and k are set by the pre-registered rules (decisions 69,
72; PROTOCOL top-k) on all dev known-fault cases, with the library at library_as_of, so the
agent's gate and the matcher baseline use the library being evaluated. The matcher baseline
is the graph's own match node on the same cases (one engine).

Modes:
- --dry-run      the evaluation and tuning plans through the graph with a FakeClient that
                 declines, into a temporary folder. Writes an agent_dry_run record: planned
                 and completed passes per subset, outcomes, the evidence checks, and the cost
                 projection. Spends nothing and calls nothing.
- --project-cost the same run; prints the projection only, writes nothing.
- --tuning / --evaluation  the paid runs (Raj runs them): GeminiClient behind the budget
                 meter (decision 76) and the cache (data/llm_cache). Every pass is written to
                 data/agent_runs/<stamp>_<mode>/calls.jsonl, the ledger to ledger.json, and an
                 agent_run record holds their SHA-256s, the prompt's hash, the settings, the
                 prices and whether the run is complete. A budget stop writes the record
                 marked incomplete. --evaluation refuses a prompt whose hash isn't the one
                 given (frozen by hash, decision 77). No metric is computed here, so a metric
                 bug never costs a paid rerun.
- --table        the agent table from a complete agent_run record: eval/agent_metrics.py
                 (Raj's) per stage and repeat, the matcher on the same cases, the keep rule,
                 the paired bootstrap (seed 20261001, a fresh generator per comparison),
                 confidence, agreement, misses, the not_in_library secondary, latency and
                 cost. Writes an agent_table record and a Markdown table under data/tables/.

Conventions (Claude's, to confirm before a paid run):
- One subset draw for every fault: the same run numbers across faults, which keeps the
  run-number bootstrap paired across faults (decision 49). Undetected runs in the draw have
  no case (decision 70); the subset isn't topped up.
- Thresholds and k re-derived on the library at library_as_of (mixed-feed-temperature-wander
  at r2), by the same rules as the dev diag table; both recorded.
- The paired bootstrap is reported per repeat.
- The cost projection assumes CHARS_PER_TOKEN input characters per token and
  EXPECTED_OUTPUT_TOKENS output tokens per call; the worst case is the budget meter's bound.
Refuses a dirty tree (before loading anything) unless --allow-dirty; never overwrites.
"""

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import numpy as np

from app.agent import graph as ag
from app.agent import llm, records, tools
from app.detector import bundle as bundle_mod
from app.detector import replay
from app.diagnosis import matcher
from app.library import store
from dataset import loader, splits
from eval import approve_entry as ap
from eval import calibrate_driver as drv
from eval import calibrate_watch as cw
from eval import cases as cases_mod
from eval import dev_table, diag_table, evidence_normals, run_record
from eval import diag_metrics as dm
from ingest import export_replay as ex
from ingest import tags as tagmap

EVAL_SEED, TUNE_SEED = 20261004, 20261005
EVAL_RUNS, TUNE_RUNS = 10, 3
REPEATS = {"evaluation": 5, "tuning": 1}
STAGES = ag.STAGES
LOO_FAULTS = diag_table.LOO_FAULTS
BOOTSTRAP_SEED = dev_table.BOOTSTRAP_SEED
DEFAULT_BUNDLE = bundle_mod.DEFAULT_BUNDLE.parent / "pca_v3"
DEFAULT_OUT = run_record.REPO_ROOT / "data" / "agent_runs"
PROMPTS = run_record.REPO_ROOT / "app" / "agent" / "prompts"
CHARS_PER_TOKEN = 4
EXPECTED_OUTPUT_TOKENS = 300
DRY_ANSWER = json.dumps({"decision": "decline", "entry_ref": None, "family": None, "confidence": "low",
                         "cited_evidence": [], "action_ids": [], "rationale": "dry run"})


class AgentTableError(RuntimeError):
    pass


# ---------- subsets and cases ----------

def subsets(dev_numbers, eval_runs=None, tune_runs=None):
    """(evaluation numbers, tuning numbers), sorted, disjoint, by their seeds."""
    eval_runs, tune_runs = eval_runs or EVAL_RUNS, tune_runs or TUNE_RUNS
    pool = sorted(int(n) for n in dev_numbers)
    if len(pool) < eval_runs + tune_runs:
        raise AgentTableError(f"{len(pool)} dev run numbers can't give {eval_runs} + {tune_runs}")
    ev = sorted(int(n) for n in np.random.default_rng(EVAL_SEED).choice(pool, eval_runs, replace=False))
    rest = [n for n in pool if n not in set(ev)]
    tu = sorted(int(n) for n in np.random.default_rng(TUNE_SEED).choice(rest, tune_runs, replace=False))
    return ev, tu


@dataclass
class Case:
    id: str                    # builder side: kind, fault, run and notification sample
    kind: str                  # known, false or loo
    run: int
    fault: int
    family: str | None
    right: str | None
    t: int                     # the notification sample (1-based)
    features: dict             # eval/cases.py's features at the notification
    values: object             # the run, raw columns (for the history)
    columns: tuple

    @property
    def history_id(self):
        return ag.opaque_id("h", self.id)

    def notified_at(self):
        return ex.START + (self.t - 1) * ex.STEP


def history_from_run(x, columns, bundle) -> tools.History:
    """The run as the historian holds it, built as the replay export builds the demo's
    stream: fast tags on the plant clock, analyzers at their publications only."""
    fast = tagmap.column_indices(columns, list(bundle.model.tags))
    ts = tuple(ex.START + i * ex.STEP for i in range(len(x)))
    stream = replay.Stream(ts=ts, values=np.asarray(x[:, fast], dtype=np.float64), tags=tuple(bundle.model.tags))
    pubs = ex.publications(x, columns, ex.analyzer_intervals())
    return tools.History(stream=stream, analyzers={t: tuple((ts[s - 1], float(v)) for s, v in items)
                                                   for t, items in pubs.items()})


class Histories(dict):
    """{history_id: History}, built on first use from the case's run."""

    def __init__(self, cases, bundle):
        super().__init__()
        self._cases = {c.history_id: c for c in cases}
        self._bundle = bundle

    def __missing__(self, key):
        c = self._cases[key]
        h = history_from_run(c.values, c.columns, self._bundle)
        self[key] = h
        return h


def gather(inp, right_of, family_of_fault):
    """{"known": [...], "false": [...], "loo": [...]} over every dev run (subsets come later)."""
    out = {"known": [], "false": [], "loo": []}
    for f in cases_mod.KNOWN_FAULTS:
        runs = loader.load_faulty(f, "dev")
        if runs.pool != "dev":
            raise AgentTableError(f"asked for dev, the loader gave {runs.pool}")
        for r in cases_mod.score_pool(inp, runs):
            if not r["detected"]:
                continue
            base = dict(run=r["run"], fault=f, family=family_of_fault[f], t=r["notification_sample"],
                        features=r["features"], values=runs.runs[r["run"]], columns=tuple(runs.columns))
            out["known"].append(Case(id=f"known:{f}:{r['run']}:{base['t']}", kind="known", right=right_of[f], **base))
            if f in LOO_FAULTS:
                out["loo"].append(Case(id=f"loo:{f}:{r['run']}:{base['t']}", kind="loo", right=None, **base))
    normal = loader.load_normal("dev")
    for r in cases_mod.score_normal(inp, normal):
        for n in r["notifications"]:
            out["false"].append(Case(id=f"false:0:{r['run']}:{n['sample']}", kind="false", run=r["run"], fault=0,
                                     family=None, right=None, t=n["sample"], features=n["features"],
                                     values=normal.runs[r["run"]], columns=tuple(normal.columns)))
    return out


def plan(cases, numbers, mode):
    """[(case, stage, repeat)] for a subset: known cases on its numbers; for evaluation also
    every false and loo case. A case is planned at a stage only if its reading exists."""
    chosen = [c for c in cases["known"] if c.run in set(numbers)]
    if mode == "evaluation":
        chosen += cases["false"] + cases["loo"]
    return [(c, st, r) for c in chosen for st in STAGES if st in c.features for r in range(REPEATS[mode])]


# ---------- the matcher's rules on the evaluated library ----------

def matcher_rules(revs, known, right_of, family_of_fault):
    """{stage: {"threshold", "accepted", "short", "k"}} on all dev known-fault cases."""
    out = {}
    for st in STAGES:
        ms = [diag_table.Moment(c.run, c.fault, c.features) for c in known if st in c.features]
        rankings = diag_table.run_matcher(revs, ms, st)
        t, acc, short = diag_table.matcher_threshold(rankings)
        kc = [diag_table.make_case(m, diag_table.ids(r), matcher.decline(r, t), right_of, family_of_fault)
              for m, r in zip(ms, rankings)]
        out[st] = {"threshold": t, "accepted": acc, "short": short, "k": diag_table.choose_k(kc, len(revs))}
    return out


def without(library, entry_ids):
    """The library with these entries removed (leave-one-out)."""
    return store.Library({e: v for e, v in library.entries.items() if e not in set(entry_ids)}, library.accounts)


# ---------- running the graph ----------

class Sizer:
    """Records each prompt's size before passing the call on (for the cost projection)."""

    def __init__(self, inner):
        self.inner, self.settings, self.sizes = inner, inner.settings, []

    def complete(self, prompt, schema, *, repeat):
        self.sizes.append((len(prompt), llm.input_bound(prompt, schema)))
        return self.inner.complete(prompt, schema, repeat=repeat)


def expected_evidence(features, stage):
    keep = ("location", "provisional") if stage == "provisional" else ("location", "provisional", "revised")
    return {k: features[k] for k in keep if k in features}


def row_of(case, stage, repeat, v):
    llm_ = v.get("llm") or {}
    out = v.get("output") or {}
    return {"case": case.id, "kind": case.kind, "run": case.run, "fault": case.fault, "family": case.family,
            "right": case.right, "stage": stage, "repeat": repeat, "outcome": v.get("outcome"),
            "entry": (v.get("proposal") or {}).get("entry_ref", "").split("@")[0] or None,
            "answer_family": out.get("family"), "confidence": out.get("confidence"),
            "failures": [f["code"] for f in v.get("failures") or []],
            "candidates": [c["entry_id"] for c in v.get("candidates") or []],
            "matcher_ranking": [[s["entry_id"] for s in block] for block in v.get("ranking") or []],
            "matcher_declined": (v.get("matcher") or {}).get("decision") == "decline",
            "llm_key": llm_.get("key"), "cached": llm_.get("cached"), "latency_ms": llm_.get("latency_ms"),
            "tokens_in": llm_.get("tokens_in"), "tokens_out": llm_.get("tokens_out"),
            "tokens_thinking": llm_.get("tokens_thinking"), "model_version": llm_.get("model_version"),
            "error": llm_.get("error")}


def run_plan(planned, *, folder, label, bundle, library, loo_library, client, render, rules, library_as_of):
    """Every planned pass through the graph. Returns (rows, complete, stop reason). A
    BudgetExceeded stops the run; every other failure raises."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rec = records.RecordStore(folder / "records.db")
    thresholds = {st: rules[st]["threshold"] for st in STAGES}
    ks = sorted({rules[st]["k"] for st in STAGES})
    if len(ks) != 1:
        raise AgentTableError(f"k differs between diagnosis times ({ks}); the graph takes one k")
    histories = Histories(list({c.id: c for c, _, _ in planned}.values()), bundle)
    graphs = {}
    for name, lib in (("full", library), ("loo", loo_library)):
        deps = ag.Deps(tools=tools.Tools(bundle, lib, histories), library=lib, client=client,
                       records=rec, render=render, thresholds=thresholds, k=ks[0])
        graphs[name] = ag.build(ag.open_checkpointer(folder / f"checkpoints_{name}.db"), deps)
    rows, checked = [], set()
    for case, stage, repeat in planned:
        g = graphs["loo" if case.kind == "loo" else "full"]
        episode = ag.opaque_id("ep", label, case.id, stage, repeat)
        try:
            s = ag.start(g, episode, case.history_id, case.notified_at().isoformat(), library_as_of,
                         repeat=repeat, stage=stage)
        except llm.BudgetExceeded as e:
            return rows, False, str(e)
        v = s["values"]
        if (case.id, stage) not in checked:
            if v.get("evidence") != expected_evidence(case.features, stage):
                raise AgentTableError(f"the graph's evidence differs from eval/cases.py's for {case.id} at {stage}")
            checked.add((case.id, stage))
        if v.get("outcome") not in ("matcher_declined", "declined", "not_in_library", "failed_check", "error",
                                    "proposed"):
            raise AgentTableError(f"{case.id} at {stage} ended without an outcome")
        rows.append(row_of(case, stage, repeat, v))
    return rows, True, None


def projection(sizes, settings=llm.SETTINGS):
    """{"calls", "input_chars", "expected_inr", "worst_inr"} for prompts of these sizes
    [(characters, input bound)], at the dated prices (decision 76)."""
    chars = sum(c for c, _ in sizes)
    bound = sum(b for _, b in sizes)
    n = len(sizes)
    expected = llm.cost_inr(settings, -(-chars // CHARS_PER_TOKEN), n * EXPECTED_OUTPUT_TOKENS, 0)
    worst = llm.cost_inr(settings, bound, n * settings.max_output_tokens, 0)
    return {"calls": n, "input_chars": chars, "expected_inr": float(round(expected, 4)),
            "worst_inr": float(round(worst, 4)), "chars_per_token": CHARS_PER_TOKEN,
            "expected_output_tokens": EXPECTED_OUTPUT_TOKENS}


def prompt_sha256(folder=PROMPTS):
    """The prompt's hash: SHA-256 over every file under app/agent/prompts/ (path and bytes, in
    path order), so any change to the template changes it."""
    h = hashlib.sha256()
    files = sorted(p for p in Path(folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts
                   and p.name != ".gitkeep")
    if not files:
        raise AgentTableError("no prompt template in app/agent/prompts/ yet (Raj's, S4)")
    for p in files:
        h.update(p.relative_to(folder).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def load_render():
    """Raj's template: app/agent/prompts/diagnosis.py's render(features, candidates, note)."""
    try:
        from app.agent.prompts import diagnosis
    except ImportError as e:
        raise AgentTableError(f"the prompt template app/agent/prompts/diagnosis.py isn't there yet ({e})") from None
    return diagnosis.render


# ---------- the run ----------

def _setup(repo_root, library_as_of, model_path, limits_path, watch_path, normals_path, bundle_dir):
    lib_t = datetime.fromisoformat(library_as_of)
    if lib_t.tzinfo is None:
        raise AgentTableError("--library-as-of needs its UTC offset")
    library = store.load(**ap.library_paths(repo_root))
    revs = {e: inf.stored.revision for e, inf in sorted(library.in_force(lib_t).items())}
    entry_fault = diag_table.entry_faults(repo_root)
    right_of = {f: e for e, f in entry_fault.items() if e in revs}
    missing = [f for f in cases_mod.KNOWN_FAULTS if f not in right_of]
    if missing:
        raise AgentTableError(f"known faults without an entry in force at {library_as_of}: {missing}")
    family_of_fault = {f: revs[e].family for f, e in right_of.items()}
    inp = cases_mod.load_inputs(model_path, limits_path, watch_path, normals_path, repo_root)
    b = bundle_mod.load(bundle_dir)
    bundle_mod.self_test(b)
    same = (b.model_sha256 == run_record.sha256(model_path)
            and all(b.limits[k] == inp.lim[k] for k in ("t2_lim", "spe_lim", "n", "gap", "warmup"))
            and [b.watch["groups"][g]["w"] for g in inp.names] == list(inp.w_group)
            and [b.watch["tags"][t] for t in b.model.tags] == list(inp.w_tag)
            and b.bands() == {t: tuple(map(float, v)) for t, v in inp.bands.items()})
    if not same:
        raise AgentTableError(f"bundle {b.name} isn't built from these inputs (one engine: the model, limits, "
                              "Watch boundaries and evidence normals must be the evaluation's)")
    return library, revs, right_of, family_of_fault, inp, b


def run(mode, *, library_as_of, model_path=drv.DEFAULT_MODEL, limits_path=drv.DEFAULT_OUT,
        watch_path=cw.DEFAULT_OUT, normals_path=evidence_normals.DEFAULT_OUT, bundle_dir=DEFAULT_BUNDLE,
        out_root=DEFAULT_OUT, budget=None, prompt_hash=None, client=None, render=None, allow_dirty=False,
        repo_root=None, now=None, eval_runs=None, tune_runs=None, out=print):
    if mode not in ("dry-run", "project-cost", "tuning", "evaluation"):
        raise AgentTableError(f"unknown mode {mode!r}")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    paid = mode in ("tuning", "evaluation")
    if paid:
        budget = budget if budget is not None else (500 if mode == "evaluation" else None)
        if budget is None:
            raise AgentTableError("--tuning needs --budget (rupees)")
        render = render or load_render()
        actual = prompt_sha256(repo_root / "app" / "agent" / "prompts") if client is None else (prompt_hash or "test")
        if mode == "evaluation" and prompt_hash != actual:
            raise AgentTableError(f"the prompt's hash is {actual}, not the frozen {prompt_hash} (decision 77)")
        prompt_hash = actual
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)          # before any loading
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    library, revs, right_of, family_of_fault, inp, b = _setup(
        repo_root, library_as_of, model_path, limits_path, watch_path, normals_path, bundle_dir)
    dev_numbers = splits.load()["pools"]["dev"]
    ev, tu = subsets(dev_numbers, eval_runs, tune_runs)
    cases = gather(inp, right_of, family_of_fault)
    rules = matcher_rules(revs, cases["known"], right_of, family_of_fault)
    loo_library = without(library, [right_of[f] for f in LOO_FAULTS])
    config = {"mode": mode, "library_as_of": library_as_of,
              "library": {e: f"{e}@r{r.revision}" for e, r in revs.items()},
              "left_out": {str(f): right_of[f] for f in LOO_FAULTS}, "bundle": b.name,
              **inp.records, "limits_sha256": inp.limits_sha256,
              "subsets": {"evaluation": {"seed": EVAL_SEED, "runs": len(ev)}, "tuning": {"seed": TUNE_SEED, "runs": len(tu)}},
              "rules": {st: {"threshold": str(r["threshold"]), "accepted": float(r["accepted"]),
                             "short": r["short"], "k": r["k"]} for st, r in rules.items()},
              "settings": llm.SETTINGS.as_dict(), "schema_version": ag.sc.SCHEMA_VERSION,
              "prices": {"read_on": llm.PRICES[llm.SETTINGS.model_id].read_on,
                         "usd_per_m_input": str(llm.PRICES[llm.SETTINGS.model_id].usd_per_m_input),
                         "usd_per_m_output": str(llm.PRICES[llm.SETTINGS.model_id].usd_per_m_output),
                         "usd_inr": str(llm.USD_INR), "usd_inr_on": llm.USD_INR_ON}}
    common = dict(bundle=b, library=library, loo_library=loo_library, rules=rules, library_as_of=library_as_of)

    if not paid:
        results = {}
        with tempfile.TemporaryDirectory() as tmp:
            for subset, numbers in (("evaluation", ev), ("tuning", tu)):
                planned = plan(cases, numbers, subset)
                sizer = Sizer(llm.CachedClient(llm.FakeClient(lambda p, s, r: DRY_ANSWER), Path(tmp) / "cache"))
                rows, complete, why = run_plan(planned, folder=Path(tmp) / subset, label=f"dry:{subset}",
                                               client=sizer, render=render or load_render(), **common)
                results[subset] = {"planned": len(planned), "completed": len(rows), "complete": complete,
                                   "outcomes": {o: sum(r["outcome"] == o for r in rows)
                                                for o in sorted({r["outcome"] for r in rows})},
                                   "cases": {k: len({r["case"] for r in rows if r["kind"] == k})
                                             for k in ("known", "false", "loo")},
                                   "llm_calls": sum(r["llm_key"] is not None for r in rows),
                                   "projection": projection(sizer.sizes)}
        for subset, r in results.items():
            p = r["projection"]
            out(f"{subset}: {r['completed']} of {r['planned']} passes complete; {p['calls']} LLM calls; "
                f"projected Rs {p['expected_inr']:.2f} expected, Rs {p['worst_inr']:.2f} at most")
        if mode == "project-cost":
            return results, None
        record = run_record.write("agent_dry_run", config=config, seeds={"evaluation": EVAL_SEED, "tuning": TUNE_SEED},
                                  metrics=results, outputs={}, commit=commit, dirty=dirty, repo_root=repo_root, now=now)
        out(f"run record: {record}")
        return results, record

    # the paid runs
    folder = Path(out_root) / f"{stamp}_{mode}"
    if folder.exists():
        raise FileExistsError(f"{folder} exists; runs are never overwritten")
    if client is None:
        from eval import gemini
        client = llm.CachedClient(llm.MeteredClient(gemini.GeminiClient(llm.SETTINGS),
                                                    llm.BudgetMeter(budget, llm.SETTINGS)), llm.DEFAULT_CACHE)
    planned = plan(cases, ev if mode == "evaluation" else tu, mode)
    rows, complete, why = run_plan(planned, folder=folder, label=f"{mode}:{stamp}", client=client, render=render,
                                   **common)
    calls = folder / "calls.jsonl"
    calls.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    ledger = folder / "ledger.json"
    ledger.write_text(json.dumps({k: p for _, k, p in records.RecordStore(folder / "records.db").all("ledger")},
                                 indent=2, sort_keys=True))
    spent = sum(float(p["cost_inr"]) for p in json.loads(ledger.read_text()).values())
    metrics_ = {"planned": len(planned), "completed": len(rows), "complete": complete, "stopped": why,
                "llm_calls": sum(r["llm_key"] is not None for r in rows), "spent_inr": round(spent, 5)}
    config.update(prompt_sha256=prompt_hash, budget_inr=budget, repeats=REPEATS[mode])
    record = run_record.write("agent_run", config=config, seeds={"evaluation": EVAL_SEED, "tuning": TUNE_SEED},
                              metrics=metrics_, outputs={"calls": calls, "ledger": ledger},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    out(f"{mode}: {len(rows)} of {len(planned)} passes{'' if complete else ' (INCOMPLETE: ' + str(why) + ')'}; "
        f"Rs {spent:.4f} spent\nrun record: {record}")
    return metrics_, record


def matcher_case(r):
    """The matcher's own answer on a pass (the graph's match node), as a diag_metrics.Case."""
    return dm.Case(run=r["run"], fault=r["fault"], family=r["family"], right=r["right"],
                   ranking=tuple(tuple(b) for b in r["matcher_ranking"]), declined=bool(r["matcher_declined"]))


def _rate(x, n):
    return None if not n else x / n


def matcher_summary(rows, family_of):
    known = [matcher_case(r) for r in rows if r["kind"] == "known"]
    false_ = [matcher_case(r) for r in rows if r["kind"] == "false"]
    loo = [matcher_case(r) for r in rows if r["kind"] == "loo"]
    return {"known": len(known), "top1": _rate(dm.topk_credit(known, 1), len(known)),
            "top3": _rate(dm.topk_credit(known, 3), len(known)),
            "family": _rate(dm.family_credit(known, family_of), len(known)),
            "wrongly_declined": dm.wrongly_declined(known) if known else None,
            "false_alert_declined": dm.decline_share(false_) if false_ else None,
            "loo_declined": dm.decline_share(loo) if loo else None}


def table(record_path, *, repo_root=None, tables_dir=None, now=None, allow_dirty=False, n_boot=None, out=print):
    """The agent table from a complete agent_run record (eval/agent_metrics.py, Raj's)."""
    from eval import agent_metrics as am
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    rec_path = Path(record_path)
    rec = json.loads(rec_path.read_text())
    if rec.get("name") != "agent_run":
        raise AgentTableError(f"{rec_path} isn't an agent_run record")
    if not rec["metrics"]["complete"]:
        raise AgentTableError(f"{rec_path} is incomplete ({rec['metrics']['stopped']}); it's never reported")
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)
    files = {}
    for name in ("calls", "ledger"):
        p = repo_root / rec["outputs"][name]["path"]
        if run_record.sha256(p) != rec["outputs"][name]["sha256"]:
            raise AgentTableError(f"{p} isn't the file the record names")
        files[name] = p
    rows = [json.loads(line) for line in files["calls"].read_text().splitlines() if line]
    ledger = json.loads(files["ledger"].read_text())
    lib_t = datetime.fromisoformat(rec["config"]["library_as_of"])
    library = store.load(**ap.library_paths(repo_root))
    family_of = {e: inf.stored.revision.family for e, inf in library.in_force(lib_t).items()}
    results = {}
    for st in STAGES:
        srows = [r for r in rows if r["stage"] == st]
        reps = sorted({r["repeat"] for r in srows})
        by_rep = {k: [r for r in srows if r["repeat"] == k] for k in reps}
        agent = {k: am.summary(v, family_of) for k, v in by_rep.items()}
        base = by_rep[reps[0]]
        m = matcher_summary(base, family_of)
        keep_agent = [{"top1": agent[k]["top1"], "family": agent[k]["family"],
                       "unknowns_declined": dm.decline_share([am.to_case(r, keep_rule=True) for r in by_rep[k]
                                                              if r["kind"] == "loo"])} for k in reps]
        keep_matcher = {"top1": m["top1"], "family": m["family"], "unknowns_declined": m["loo_declined"]}
        paired = {}
        m_known = [matcher_case(r) for r in base if r["kind"] == "known"]
        for k in reps:
            a_known = [am.to_case(r) for r in by_rep[k] if r["kind"] == "known"]
            d, lo, hi = dm.paired_top1_bootstrap(a_known, m_known, np.random.default_rng(BOOTSTRAP_SEED),
                                                 **({"n": n_boot} if n_boot else {}))
            paired[str(k)] = {"difference": d, "lo": lo, "hi": hi}
        results[st] = {"agent": {str(k): v for k, v in agent.items()}, "matcher": m,
                       "keep_rule": am.keep_rule(keep_agent, keep_matcher), "paired": paired,
                       "confidence": am.confidence_table(srows), "agreement": am.agreement(srows),
                       "misses": am.miss_labels(srows),
                       "not_in_library": am.not_in_library_secondary([r for r in srows if r["kind"] == "loo"]),
                       "latency_cost": am.latency_cost(srows, ledger)}
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    tables_dir = Path(tables_dir or diag_table.DEFAULT_TABLES)
    tables_dir.mkdir(parents=True, exist_ok=True)
    md = tables_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_agent_table.md"
    md.write_text(markdown(results, rec))
    recorded = _plain(results)
    for st in recorded:                     # run records hold short lists only: the cases are in the table
        a = recorded[st]["agreement"]
        a["unstable"] = len(a["unstable"])
    record = run_record.write("agent_table", config={"agent_run": rec_path.relative_to(repo_root).as_posix(),
                                                      "agent_run_sha256": run_record.sha256(rec_path)},
                              seeds={"bootstrap": BOOTSTRAP_SEED}, metrics=diag_table.numbers(recorded),
                              outputs={"table": md}, commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    out(f"table: {md}\nrun record: {record}")
    return results, record


def _plain(x):
    """Tuples as lists and unknown scalars as themselves, for the record."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _pct(x):
    return "—" if x is None else f"{100 * float(x):.1f}"


def markdown(results, rec) -> str:
    lines = ["# Agent table (dev)", "", f"Run: {rec['config']['mode']}, library as of {rec['config']['library_as_of']}, "
             f"prompt {rec['config'].get('prompt_sha256', '')[:12]}…; rates in %.", ""]
    for st, r in results.items():
        lines += [f"## {st.capitalize()}", "", "| Method | Top-1 | Top-3 | Family | Wrongly declined | "
                  "False alerts declined | Leave-one-out declined |", "|---|---|---|---|---|---|---|"]
        m = r["matcher"]
        lines.append(f"| matcher | {_pct(m['top1'])} | {_pct(m['top3'])} | {_pct(m['family'])} | "
                     f"{_pct(m['wrongly_declined'])} | {_pct(m['false_alert_declined'])} | {_pct(m['loo_declined'])} |")
        for k, a in r["agent"].items():
            lines.append(f"| agent, repeat {k} | {_pct(a['top1'])} | {_pct(a['top3'])} | {_pct(a['family'])} | "
                         f"{_pct(a['wrongly_declined'])} | {_pct(a['false_alert_declined'])} | {_pct(a['loo_declined'])} |")
        kr = r["keep_rule"]
        lines += ["", f"Keep rule: {'KEEP' if kr['keep'] else 'not kept'}; better on {kr['better_on'] or 'none'}, "
                  f"worse on {kr['worse_on'] or 'none'}.", "",
                  f"Unstable across repeats: {len(r['agreement']['unstable'])} of {r['agreement']['cases']} cases.", ""]
        lines += [f"- {case} ({stage})" for case, stage in r["agreement"]["unstable"]]
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    modes = parser.add_mutually_exclusive_group(required=True)
    for m in ("dry-run", "project-cost", "tuning", "evaluation"):
        modes.add_argument(f"--{m}", dest="mode", action="store_const", const=m)
    modes.add_argument("--table", type=Path, default=None, help="an agent_run record")
    parser.add_argument("--library-as-of", default=None)
    parser.add_argument("--budget", type=float, default=None, help="rupees (decision 76)")
    parser.add_argument("--prompt-sha256", default=None)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    if args.table is not None:
        try:
            table(args.table, allow_dirty=args.allow_dirty)
        except (ValueError, FileNotFoundError, AgentTableError, run_record.RunRecordError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0
    if not args.library_as_of:
        parser.error("--library-as-of is required (decision 77)")
    if args.mode in ("tuning", "evaluation"):
        from dotenv import load_dotenv                       # the paid runs read the key from .env
        load_dotenv(override=False)
    try:
        run(args.mode, library_as_of=args.library_as_of, budget=args.budget, prompt_hash=args.prompt_sha256,
            bundle_dir=args.bundle, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, evidence_normals.NormalsError, cases_mod.CasesError, AgentTableError,
            diag_table.DiagTableError, bundle_mod.BundleError, llm.LLMError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
