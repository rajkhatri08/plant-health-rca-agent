"""The agent's dev evaluation driver (decisions 75-77; PROTOCOL, Diagnosis and LLM
measurement). Builder side: it reads labels and run numbers.

    python -m eval.agent_table --dry-run      --library-as-of 2026-10-05T00:00:00+00:00
    python -m eval.agent_table --project-cost --library-as-of …
    python -m eval.agent_table --tuning       --library-as-of … --budget 50 --billing-tier tier-1
                                              [--min-interval <s>]
    python -m eval.agent_table --evaluation   --library-as-of … --prompt-sha256 <hash> --billing-tier tier-1
                                              [--budget 450]
                                              [--min-interval <s>]
    python -m eval.agent_table --replay-evaluation --library-as-of … --prompt-sha256 <hash>
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
                 given (frozen by hash, decision 77). --min-interval spaces the starts of real
                 API calls (cache hits aren't paced; the retry rule of decision 76 is unchanged)
                 and is recorded as min_interval_s. --billing-tier (free or tier-1,
                 required) names the key's project tier, recorded as billing_tier: on the free
                 tier the cost figures are the meter's estimates, not charges (decision 76). No metric is computed here, so a metric
                 bug never costs a paid rerun.
- --replay-evaluation  the evaluation plan through today's graph (the shipped flow, decision
                 79) with every answer from the LLM cache (data/llm_cache): no API call, no spend.
                 A cache miss stops the run, recorded incomplete. The prompt must be the
                 evaluation's (--prompt-sha256). Writes an agent_run record (mode
                 replay-evaluation, cache_only) like a paid run's.
- --table        the agent table from a complete agent_run record: eval/agent_metrics.py
                 (Raj's) per stage and repeat, the matcher on the same cases, the keep rule,
                 the paired bootstrap (seed 20261001, a fresh generator per comparison),
                 confidence, agreement, misses, the not_in_library secondary, latency and
                 cost. Writes an agent_table record and a Markdown table under data/tables/.

Conventions (confirmed by Raj, 4 October 2026; decision 77):
- One subset draw for every fault: the same run numbers across faults, which keeps the
  run-number bootstrap paired across faults (decision 49). Undetected runs in the draw have
  no case (decision 70); the subset isn't topped up.
- Thresholds and k re-derived on the library at library_as_of (mixed-feed-temperature-wander
  at r2), by the same rules as the dev diag table; both recorded.
- The paired bootstrap is reported per repeat.
- The cost projection assumes CHARS_PER_TOKEN input characters per token and
  EXPECTED_OUTPUT_TOKENS output tokens per call; the worst case is the budget meter's bound.
Refuses a dirty tree (before loading anything) unless --allow-dirty; never overwrites.

The test split (week 7 S1d; Raj runs every command with EVAL_MODE=1, never Claude):
    python -m eval.agent_table --split test --dry-run --library-as-of … --prompt-sha256 <hash>
                               --fingerprint-record eval/runs/<stamp>_diag_fingerprint.json
    python -m eval.agent_table --split test --evaluation --library-as-of … --prompt-sha256 <hash>
                               --fingerprint-record … --dry-run-record eval/runs/<stamp>_test_agent_dry_run.json
                               --billing-tier tier-1 --min-interval 1 [--repeats 5|3] [--budget 500]
                               [--after-budget-stop eval/runs/<stamp>_test_agent_run.json]
    python -m eval.agent_table --table eval/runs/<stamp>_test_agent_run.json
- Before any test load: the prompt's hash, the leave-one-out refs (S0 answer 16), and the
  matcher's thresholds and k re-derived on dev, which must equal the diag_fingerprint record's.
- Cases, on the seed-20261006 draw of 10 run numbers (S0 answer 14): known (12 faults, full
  library), unknown (16-20, full library; correct only when declined), loo (1, 4, 5 and 13,
  each on its own library without that entry), and every notification on the drawn normal
  runs (S0 answer 15; more than TEST_FALSE_CAP stops the run).
- --dry-run: a FakeClient through the graph (test prompts stay in the sealed folder) and the
  cost projection at 5 and at 3 repeats; repeats_allowed is 5 if its expected cost is at most
  Rs 400, else 3 if that is, else none (S0 answer 17). Writes a test_agent_dry_run record.
- --evaluation (paid): needs the dry run's record from this commit, its repeats_allowed (the
  default when --repeats is omitted), a budget of at most Rs 500 (default 500), and the billing
  tier. After a budget stop, the pre-registered rerun (TEST_PLAN section 6) is
  --after-budget-stop <the stopped record>: that record must be from this commit and stopped
  by the budget (its stop_kind), and not itself a rerun; the rerun is then at 3 repeats with a
  budget of at most Rs 500 minus its spent_inr (the default), and anything else is refused. The LLM cache, calls.jsonl, the
  ledger and the databases go to the sealed folder (S0 answers 21, 22); the test_agent_run
  record names them as "sealed:…" with their SHA-256s.
- --table on a test_agent_run: the shipped flow, the re-ranker and the matcher from the same
  passes (decision 79), faults 16-20 and leave-one-out by fault, the keep rule reported but not
  applied (S0 answer 19), cold start "not applicable", LLM only "not run" (S0 answer 18). The
  Markdown in data/tables/ leaves out the unstable cases; a copy listing them goes to the
  sealed folder.
"""

import argparse
import hashlib
import json
import math
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
from eval import split as split_mod
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
NO_UNKNOWNS = "not applicable (no unknown cases)"
BILLING_TIERS = ("free", "tier-1")       # the key's project tier, recorded per paid run (decision 76)
DEFAULT_BUDGETS = {"evaluation": 450}       # Rs; tuning's Rs 50 is given explicitly (decision 77)
EXPECTED_OUTPUT_TOKENS = 300
TEST_BUDGET = 500                           # Rs, the test run's hard cap (PROTOCOL; S0 answer 17)
TEST_PROJECTION_CAP = 400                   # Rs: the dry run's expected cost must be at most this
TEST_REPEATS = (5, 3)                       # 5; cut to 3 only if 5 projects over the cap (never cases)
TEST_FALSE_CAP = 50                         # S0 answer 15: more false-alert cases stops the run
UNKNOWN_FAULTS = diag_table.UNKNOWN_FAULTS
LOO_TEST = diag_table.LOO_TEST
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
    lib: str | None = None     # the library variant; None: "loo" for a loo case, else "full"

    @property
    def variant(self):
        return self.lib or ("loo" if self.kind == "loo" else "full")

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
    """Records each prompt's size (and its repeat) before passing the call on (for the cost
    projection)."""

    def __init__(self, inner):
        self.inner, self.settings, self.sizes, self.repeats = inner, inner.settings, [], []

    def complete(self, prompt, schema, *, repeat):
        self.sizes.append((len(prompt), llm.input_bound(prompt, schema)))
        self.repeats.append(repeat)
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
            "error": llm_.get("error"),
            # the shipped flow (decision 79) and, for the re-ranker view, the LLM's own answer
            "ship_decision": (v.get("ship") or {}).get("decision"), "tie_break": (v.get("ship") or {}).get("tie_break"),
            "dissent": v.get("dissent") is not None,
            "llm_decision": out.get("decision"), "llm_entry": (out.get("entry_ref") or "").split("@")[0] or None}


def reranker_row(r):
    """The LLM re-ranker's view of a pass (decisions 75, 77): the LLM's own valid answer, as
    the re-ranker graph showed it before decision 79. A row from a run before the shipped flow
    (no "llm_decision") is already that view."""
    if "llm_decision" not in r or r["outcome"] not in ("proposed", "vetoed"):
        return r
    if r["llm_decision"] == "propose":
        return {**r, "outcome": "proposed", "entry": r["llm_entry"]}
    return {**r, "outcome": "declined" if r["llm_decision"] == "decline" else "not_in_library", "entry": None}


def run_plan(planned, *, folder, label, bundle, library, loo_library, client, render, rules, library_as_of,
             libraries=None):
    """Every planned pass through the graph. Returns (rows, complete, stop reason). A
    BudgetExceeded stops the run; every other failure raises. One graph per library variant:
    "full" and "loo" on dev; on test, libraries names them ("full" and one per left-out fault)
    and each case runs on its own (Case.variant)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rec = records.RecordStore(folder / "records.db")
    thresholds = {st: rules[st]["threshold"] for st in STAGES}
    ks = sorted({rules[st]["k"] for st in STAGES})
    if len(ks) != 1:
        raise AgentTableError(f"k differs between diagnosis times ({ks}); the graph takes one k")
    histories = Histories(list({c.id: c for c, _, _ in planned}.values()), bundle)
    libraries = libraries or {"full": library, "loo": loo_library}
    graphs = {}
    for name, lib in libraries.items():
        deps = ag.Deps(tools=tools.Tools(bundle, lib, histories), library=lib, client=client,
                       records=rec, render=render, thresholds=thresholds, k=ks[0])
        graphs[name] = ag.build(ag.open_checkpointer(folder / f"checkpoints_{name}.db"), deps)
    rows, checked = [], set()
    for case, stage, repeat in planned:
        g = graphs[case.variant]
        episode = ag.opaque_id("ep", label, case.id, stage, repeat)
        try:
            s = ag.start(g, episode, case.history_id, case.notified_at().isoformat(), library_as_of,
                         repeat=repeat, stage=stage)
        except llm.BudgetExceeded as e:
            return rows, False, str(e)
        except llm.CacheMiss as e:                         # a replay found no answer: never filled in
            return rows, False, f"cache miss: {e}"
        v = s["values"]
        if (case.id, stage) not in checked:
            if v.get("evidence") != expected_evidence(case.features, stage):
                raise AgentTableError(f"the graph's evidence differs from eval/cases.py's for {case.id} at {stage}")
            checked.add((case.id, stage))
        if v.get("outcome") not in ("matcher_declined", "declined", "not_in_library", "failed_check", "error",
                                    "proposed", "emergency", "vetoed"):
            raise AgentTableError(f"{case.id} at {stage} ended without an outcome")
        row = row_of(case, stage, repeat, v)
        if case.lib is not None:
            row["variant"] = case.lib
        rows.append(row)
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
        repo_root=None, now=None, eval_runs=None, tune_runs=None, min_interval=0.0, billing_tier=None,
        cache_dir=None, out=print, split="dev", fingerprint_record=None, dry_run_record=None, repeats=None,
        after_budget_stop=None):
    if mode not in ("dry-run", "project-cost", "tuning", "evaluation", "replay-evaluation"):
        raise AgentTableError(f"unknown mode {mode!r}")
    if isinstance(min_interval, bool) or not isinstance(min_interval, (int, float)) or min_interval < 0:
        raise AgentTableError(f"--min-interval must be seconds >= 0, got {min_interval!r}")
    min_interval = float(min_interval)
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    if split == "test":
        return run_test(mode, library_as_of=library_as_of, fingerprint_record=fingerprint_record,
                        dry_run_record=dry_run_record, repeats=repeats, after_budget_stop=after_budget_stop,
                        model_path=model_path, limits_path=limits_path, watch_path=watch_path,
                        normals_path=normals_path, bundle_dir=bundle_dir, budget=budget, prompt_hash=prompt_hash,
                        client=client, render=render, repo_root=repo_root, now=now, min_interval=min_interval,
                        billing_tier=billing_tier, out=out)
    if split != "dev":
        raise AgentTableError(f"unknown split {split!r}")
    if fingerprint_record is not None or dry_run_record is not None or repeats is not None or after_budget_stop:
        raise AgentTableError("--fingerprint-record, --dry-run-record, --repeats and --after-budget-stop are only "
                              "for --split test")
    paid = mode in ("tuning", "evaluation")
    if paid:
        if billing_tier not in BILLING_TIERS:
            raise AgentTableError(f"paid runs need --billing-tier, one of {BILLING_TIERS} (decision 76), "
                                  f"got {billing_tier!r}")
        budget = budget if budget is not None else DEFAULT_BUDGETS.get(mode)
        if budget is None:
            raise AgentTableError("--tuning needs --budget (rupees)")
        render = render or load_render()
        actual = prompt_sha256(repo_root / "app" / "agent" / "prompts") if client is None else (prompt_hash or "test")
        if mode == "evaluation" and prompt_hash != actual:
            raise AgentTableError(f"the prompt's hash is {actual}, not the frozen {prompt_hash} (decision 77)")
        prompt_hash = actual
    if mode == "replay-evaluation":
        # Cache only (decision 79): the evaluation's prompts through today's graph, answered from
        # the LLM cache; a miss stops the run, nothing is called. The prompt must be the frozen one.
        injected = render is not None or client is not None          # tests: a stand-in template or client
        render = render or load_render()
        actual = (prompt_hash or "test") if injected else prompt_sha256(repo_root / "app" / "agent" / "prompts")
        if prompt_hash != actual:
            raise AgentTableError(f"the prompt's hash is {actual}, not the evaluation's {prompt_hash}; a replay "
                                  "needs the same prompts")
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

    if mode in ("dry-run", "project-cost"):
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
    if client is None and mode == "replay-evaluation":
        client = llm.ReplayClient(cache_dir or llm.DEFAULT_CACHE)
    elif client is None:
        from eval import gemini
        client = paid_stack(gemini.GeminiClient(llm.SETTINGS), budget, min_interval)
    planned = plan(cases, tu if mode == "tuning" else ev, "tuning" if mode == "tuning" else "evaluation")
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
    config.update(prompt_sha256=prompt_hash, budget_inr=budget,
                  repeats=REPEATS["tuning" if mode == "tuning" else "evaluation"], min_interval_s=min_interval,
                  billing_tier=billing_tier)
    if mode == "replay-evaluation":
        config.update(cache_only=True, billing_tier=None, budget_inr=None)
    record = run_record.write("agent_run", config=config, seeds={"evaluation": EVAL_SEED, "tuning": TUNE_SEED},
                              metrics=metrics_, outputs={"calls": calls, "ledger": ledger},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    out(f"{mode}: {len(rows)} of {len(planned)} passes{'' if complete else ' (INCOMPLETE: ' + str(why) + ')'}; "
        f"Rs {spent:.4f} spent\nrun record: {record}")
    return metrics_, record


def paid_stack(provider, budget, min_interval, *, cache_dir=None, clock=None, sleep=None):
    """The paid runs' client: CachedClient(MeteredClient(PacedClient(provider))). A cache hit
    returns before the meter or the pacer is asked; the meter refuses before the pacer waits;
    the pacer spaces the starts of real calls by min_interval seconds (the provider's retries
    and backoff, decision 76, happen inside one call)."""
    pace = {k: v for k, v in (("clock", clock), ("sleep", sleep)) if v is not None}
    paced = llm.PacedClient(provider, min_interval, **pace)
    return llm.CachedClient(llm.MeteredClient(paced, llm.BudgetMeter(budget, provider.settings)),
                            cache_dir or llm.DEFAULT_CACHE)


# ---------- the test split (week 7 S1d; Raj runs it with EVAL_MODE=1) ----------

def drawn(runs, draw):
    """The runs with these numbers only (scoring is per run, so nothing else changes)."""
    missing = [k for k in draw if k not in runs.runs]
    if missing:
        raise AgentTableError(f"{runs.name} fault {runs.fault} has no run {missing[:3]}")
    return loader.Runs(runs.name, runs.fault, runs.pool, runs.columns, {k: runs.runs[k] for k in draw})


def gather_test(inp, sp, draw, right_of, family_of_fault):
    """{"known", "unknown", "loo", "false"} on the drawn testing runs (S0 answer 14): the
    detected runs of the 12 known faults (full library); of 16-20 (full library, a decline is
    right); of 1, 4, 5 and 13 again as leave-one-out, each on its own library variant
    (S0 answer 16); and every notification on the drawn normal runs (S0 answer 15)."""
    out = {"known": [], "unknown": [], "loo": [], "false": []}
    for f in cases_mod.KNOWN_FAULTS + UNKNOWN_FAULTS:
        runs = drawn(sp.load_faulty(f), draw)
        if runs.pool != "test":
            raise AgentTableError(f"asked for the test split, the loader gave {runs.pool}")
        for r in cases_mod.score_pool(inp, runs, onset=sp.onset):
            if not r["detected"]:
                continue
            base = dict(run=r["run"], fault=f, t=r["notification_sample"], features=r["features"],
                        values=runs.runs[r["run"]], columns=tuple(runs.columns))
            if f in UNKNOWN_FAULTS:
                out["unknown"].append(Case(id=f"unknown:{f}:{r['run']}:{base['t']}", kind="unknown", family=None,
                                           right=None, **base))
                continue
            out["known"].append(Case(id=f"known:{f}:{r['run']}:{base['t']}", kind="known",
                                     family=family_of_fault[f], right=right_of[f], **base))
            if f in LOO_TEST:
                out["loo"].append(Case(id=f"loo:{f}:{r['run']}:{base['t']}", kind="loo", family=family_of_fault[f],
                                       right=None, lib=f"loo_{f}", **base))
    normal = drawn(sp.load_normal(), draw)
    for r in cases_mod.score_normal(inp, normal):
        for n in r["notifications"]:
            out["false"].append(Case(id=f"false:0:{r['run']}:{n['sample']}", kind="false", run=r["run"], fault=0,
                                     family=None, right=None, t=n["sample"], features=n["features"],
                                     values=normal.runs[r["run"]], columns=tuple(normal.columns)))
    return out


def plan_test(cases, repeats):
    """[(case, stage, repeat)]: every test case, at each stage its reading exists, repeats times."""
    chosen = cases["known"] + cases["unknown"] + cases["loo"] + cases["false"]
    return [(c, st, r) for c in chosen for st in STAGES if st in c.features for r in range(repeats)]


def check_rules_against_fingerprint(rules, fingerprint_path, repo_root, lib_t, revs, inp):
    """The matcher's thresholds and k, re-derived on dev, must be the diag_fingerprint
    record's exactly (S1 Q2, S0 answer 11); its library and inputs must be this run's.
    Returns the record's repo path."""
    config = {"as_of": lib_t.strftime(ap.TS), "library": {e: f"{e}@r{r.revision}" for e, r in revs.items()},
              **inp.records, "limits_sha256": inp.limits_sha256}
    try:
        rel, fp = diag_table.load_fingerprint(fingerprint_path, repo_root, config)
    except diag_table.DiagTableError as e:
        raise AgentTableError(str(e)) from None
    for st in STAGES:
        mine = {"threshold": str(rules[st]["threshold"]), "accepted": str(rules[st]["accepted"]),
                "short": bool(rules[st]["short"]), "k": rules[st]["k"]}
        theirs = {**{x: fp[st]["matcher"][x] for x in ("threshold", "accepted", "short")}, "k": fp[st]["k"]}
        if mine != theirs:
            raise AgentTableError(f"the matcher's rules re-derived on dev at {st} ({mine}) aren't the fingerprint's "
                                  f"({theirs}); nothing from the test split was loaded")
    return rel


def load_dry_run(path, repo_root, commit):
    """(repo path, metrics) of the test dry run the paid run relies on: same commit, clean."""
    path = Path(path)
    if not path.name.endswith("_test_agent_dry_run.json"):
        raise AgentTableError(f"{path} isn't a test_agent_dry_run record")
    rec = json.loads(path.read_text())
    if rec.get("dirty") is not False or rec.get("commit") != commit:
        raise AgentTableError(f"{path} isn't from this commit on a clean tree; run the test dry run again")
    return path.resolve().relative_to(Path(repo_root).resolve()).as_posix(), rec["metrics"]


def load_budget_stop(path, repo_root, commit):
    """(repo path, record) of the paid test run that stopped on the budget, for the
    pre-registered rerun (TEST_PLAN section 6): this commit, a clean tree, incomplete because of
    the budget, and not itself a rerun (if the rerun stops too, the run stops)."""
    path = Path(path)
    if not path.name.endswith("_test_agent_run.json"):
        raise AgentTableError(f"{path} isn't a test_agent_run record")
    rec = json.loads(path.read_text())
    if rec.get("dirty") is not False or rec.get("commit") != commit:
        raise AgentTableError(f"{path} isn't from this commit on a clean tree")
    if rec["metrics"].get("complete") or rec["metrics"].get("stop_kind") != "budget":
        raise AgentTableError(f"{path} didn't stop on the budget; --after-budget-stop is only for a budget stop")
    if rec["config"].get("after_budget_stop"):
        raise AgentTableError(f"{path} was already the rerun after a budget stop, and it stopped too: stop and "
                              "tell Raj (TEST_PLAN section 6)")
    return path.resolve().relative_to(Path(repo_root).resolve()).as_posix(), rec


def run_test(mode, *, library_as_of, fingerprint_record, dry_run_record, repeats, model_path, limits_path,
             watch_path, normals_path, bundle_dir, budget, prompt_hash, client, render, repo_root, now,
             min_interval, billing_tier, out, after_budget_stop=None):
    """The test split's dry run and paid run (S0 answers 4, 14-17, 21, 22). Order: the
    request checked, the tree, the dev rules against the fingerprint, and only then the test
    loads."""
    if mode not in ("dry-run", "evaluation"):
        raise AgentTableError("--split test takes --dry-run or --evaluation (the paid run) only")
    if fingerprint_record is None:
        raise AgentTableError("--split test needs --fingerprint-record (the diag_fingerprint record)")
    if repeats is not None and repeats not in TEST_REPEATS:
        raise AgentTableError(f"--repeats on test is one of {TEST_REPEATS} (S0 answer 17)")
    injected = client is not None or render is not None
    render = render or load_render()
    actual = (prompt_hash or "test") if injected else prompt_sha256(repo_root / "app" / "agent" / "prompts")
    if prompt_hash is None or prompt_hash != actual:
        raise AgentTableError(f"the prompt's hash is {actual}, not the frozen {prompt_hash} (--prompt-sha256)")
    paid = mode == "evaluation"
    if paid:
        if billing_tier not in BILLING_TIERS:
            raise AgentTableError(f"the paid run needs --billing-tier, one of {BILLING_TIERS}")
        if budget is not None and budget > TEST_BUDGET:
            raise AgentTableError(f"the test budget is at most Rs {TEST_BUDGET} (PROTOCOL)")
        if dry_run_record is None:
            raise AgentTableError("the paid run needs --dry-run-record, the test dry run on this commit")
    else:
        if repeats is not None:
            raise AgentTableError("the dry run projects both repeat counts itself; give no --repeats")
        if after_budget_stop is not None:
            raise AgentTableError("--after-budget-stop is only for the paid run")
        repeats = TEST_REPEATS[0]
    commit, dirty = run_record.check_clean(repo_root)                    # before any loading
    dry_rel = stopped_rel = stopped_sha = None
    if paid:
        dry_rel, dry = load_dry_run(dry_run_record, repo_root, commit)
        if dry.get("repeats_allowed") is None:
            raise AgentTableError(f"{dry_rel}: even 3 repeats project over Rs {TEST_PROJECTION_CAP}; stop and tell Raj")
        if after_budget_stop is not None:
            # The pre-registered rerun after a budget stop (TEST_PLAN section 6): 3 repeats, with
            # the budget that's left; the cache serves every call already made, at no cost.
            stopped_rel, stopped = load_budget_stop(after_budget_stop, repo_root, commit)
            stopped_sha = run_record.sha256(after_budget_stop)
            remaining = math.floor((TEST_BUDGET - float(stopped["metrics"]["spent_inr"])) * 100) / 100
            if repeats is None:
                repeats = TEST_REPEATS[-1]
            if repeats != TEST_REPEATS[-1]:
                raise AgentTableError(f"the rerun after a budget stop is at {TEST_REPEATS[-1]} repeats, not {repeats}")
            if budget is None:
                budget = remaining
            if budget > remaining:
                raise AgentTableError(f"the rerun's budget is at most Rs {TEST_BUDGET} minus the Rs "
                                      f"{stopped['metrics']['spent_inr']} already spent (Rs {remaining}), not Rs {budget}")
        else:
            repeats = dry["repeats_allowed"] if repeats is None else repeats
            if repeats != dry["repeats_allowed"]:
                raise AgentTableError(f"{dry_rel} allows {dry['repeats_allowed']} repeats (S0 answer 17), not {repeats}")
            budget = TEST_BUDGET if budget is None else budget
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    library, revs, right_of, family_of_fault, inp, b = _setup(
        repo_root, library_as_of, model_path, limits_path, watch_path, normals_path, bundle_dir)
    lib_t = datetime.fromisoformat(library_as_of)
    try:
        diag_table.check_loo_refs(revs, right_of)
    except diag_table.DiagTableError as e:
        raise AgentTableError(str(e)) from None
    rules = matcher_rules(revs, gather(inp, right_of, family_of_fault)["known"], right_of, family_of_fault)
    fp_rel = check_rules_against_fingerprint(rules, fingerprint_record, repo_root, lib_t, revs, inp)

    sp = split_mod.get("test", f"test_agent_{'run' if paid else 'dry_run'}")      # the first test load is below
    draw = split_mod.test_draw()
    cases = gather_test(inp, sp, draw, right_of, family_of_fault)
    n_false = len(cases["false"])
    if n_false > TEST_FALSE_CAP:
        raise AgentTableError(f"{n_false} false-alert cases on the drawn normal runs, over {TEST_FALSE_CAP} "
                              "(S0 answer 15): stop and tell Raj")
    libraries = {"full": library, **{f"loo_{f}": without(library, [right_of[f]]) for f in LOO_TEST}}
    common = dict(bundle=b, library=library, loo_library=None, libraries=libraries, rules=rules,
                  library_as_of=library_as_of)
    counts = {k: len(v) for k, v in cases.items()}
    config = {"mode": mode, "split": "test", "library_as_of": library_as_of,
              "library": {e: f"{e}@r{r.revision}" for e, r in revs.items()},
              "left_out": {str(f): f"{right_of[f]}@r{revs[right_of[f]].revision}" for f in LOO_TEST},
              "unknown_faults": list(UNKNOWN_FAULTS), "bundle": b.name, **inp.records,
              "limits_sha256": inp.limits_sha256, "fingerprint_record": fp_rel,
              "subsample": {"seed": split_mod.TEST_SEED, "runs": split_mod.TEST_DRAW},
              "rules": {st: {"threshold": str(r["threshold"]), "accepted": float(r["accepted"]),
                             "short": r["short"], "k": r["k"]} for st, r in rules.items()},
              "settings": llm.SETTINGS.as_dict(), "schema_version": ag.sc.SCHEMA_VERSION,
              "prices": {"read_on": llm.PRICES[llm.SETTINGS.model_id].read_on,
                         "usd_per_m_input": str(llm.PRICES[llm.SETTINGS.model_id].usd_per_m_input),
                         "usd_per_m_output": str(llm.PRICES[llm.SETTINGS.model_id].usd_per_m_output),
                         "usd_inr": str(llm.USD_INR), "usd_inr_on": llm.USD_INR_ON},
              "prompt_sha256": prompt_hash, "projection_cap_inr": TEST_PROJECTION_CAP, "false_cap": TEST_FALSE_CAP}
    seeds = {"subsample": split_mod.TEST_SEED}

    if not paid:
        planned = plan_test(cases, TEST_REPEATS[0])
        scratch = sp.out_dir(None, f"{stamp}_test_agent_dry_run")      # test prompts never leave the sealed folder
        scratch.mkdir(parents=True, exist_ok=False)
        with tempfile.TemporaryDirectory(dir=scratch) as tmp:
            sizer = Sizer(llm.CachedClient(llm.FakeClient(lambda p, s, r: DRY_ANSWER), Path(tmp) / "cache"))
            rows, complete, why = run_plan(planned, folder=Path(tmp) / "run", label=f"test-dry:{stamp}",
                                           client=sizer, render=render, **common)
        by_repeats = {str(n): projection([s for s, r in zip(sizer.sizes, sizer.repeats) if r < n])
                      for n in TEST_REPEATS}
        allowed = next((n for n in TEST_REPEATS if by_repeats[str(n)]["expected_inr"] <= TEST_PROJECTION_CAP), None)
        metrics_ = {"cases": counts, "planned": len(planned), "completed": len(rows), "complete": complete,
                    "outcomes": {o: sum(r["outcome"] == o for r in rows) for o in sorted({r["outcome"] for r in rows})},
                    "llm_calls": sum(r["llm_key"] is not None for r in rows),
                    "projection": by_repeats, "repeats_allowed": allowed}
        record = run_record.write("test_agent_dry_run", config=config, seeds=seeds, metrics=metrics_, outputs={},
                                  commit=commit, dirty=dirty, repo_root=repo_root, now=now)
        out(f"test dry run: cases {counts}; {len(rows)} of {len(planned)} passes complete")
        for n in TEST_REPEATS:
            p = by_repeats[str(n)]
            out(f"{n} repeats: {p['calls']} LLM calls; projected Rs {p['expected_inr']:.2f} expected, "
                f"Rs {p['worst_inr']:.2f} at most")
        out(f"paid run: --repeats {allowed}" if allowed else
            f"STOP: even 3 repeats project over Rs {TEST_PROJECTION_CAP}; tell Raj")
        out(f"run record: {record}")
        return metrics_, record

    folder = sp.out_dir(None, f"{stamp}_test_agent_run")
    if folder.exists():
        raise FileExistsError(f"{folder} exists; runs are never overwritten")
    if client is None:
        from eval import gemini
        client = paid_stack(gemini.GeminiClient(llm.SETTINGS), budget, min_interval,
                            cache_dir=sp.cache_dir(llm.DEFAULT_CACHE))
    planned = plan_test(cases, repeats)
    rows, complete, why = run_plan(planned, folder=folder, label=f"test:{stamp}", client=client, render=render,
                                   **common)
    calls = folder / "calls.jsonl"
    calls.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    ledger = folder / "ledger.json"
    ledger.write_text(json.dumps({k: p for _, k, p in records.RecordStore(folder / "records.db").all("ledger")},
                                 indent=2, sort_keys=True))
    spent = sum(float(p["cost_inr"]) for p in json.loads(ledger.read_text()).values())
    stop_kind = None if complete else ("cache_miss" if str(why).startswith("cache miss") else "budget")
    metrics_ = {"cases": counts, "planned": len(planned), "completed": len(rows), "complete": complete,
                "stopped": why, "stop_kind": stop_kind, "llm_calls": sum(r["llm_key"] is not None for r in rows),
                "spent_inr": round(spent, 5)}
    config.update(budget_inr=budget, repeats=repeats, min_interval_s=min_interval, billing_tier=billing_tier,
                  dry_run_record=dry_rel, after_budget_stop=stopped_rel, after_budget_stop_sha256=stopped_sha)
    record = run_record.write("test_agent_run", config=config, seeds=seeds, metrics=metrics_,
                              outputs={"calls": calls, "ledger": ledger},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    out(f"test run: {len(rows)} of {len(planned)} passes{'' if complete else ' (INCOMPLETE: ' + str(why) + ')'}; "
        f"Rs {spent:.4f} spent\nrun record: {record}")
    return metrics_, record


def output_path(repo_root, path):
    """A record's output path: "sealed:<p>" under the sealed folder, otherwise in the repo."""
    return loader.SEALED_ROOT / path.removeprefix("sealed:") if path.startswith("sealed:") else Path(repo_root) / path


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
    """The agent table from a complete agent_run record (eval/agent_metrics.py, Raj's). A
    relative record path is read against the repo root, wherever the command runs from."""
    from eval import agent_metrics as am
    repo_root = Path(repo_root or run_record.REPO_ROOT).resolve()
    rec_path = Path(record_path)
    rec_path = (rec_path if rec_path.is_absolute() else repo_root / rec_path).resolve()
    if not rec_path.is_relative_to(repo_root):
        raise AgentTableError(f"{record_path} isn't inside the repo ({repo_root})")
    rec = json.loads(rec_path.read_text())
    if rec.get("name") not in ("agent_run", "test_agent_run"):
        raise AgentTableError(f"{rec_path} isn't an agent_run or test_agent_run record")
    test = rec["name"] == "test_agent_run"
    if not rec["metrics"]["complete"]:
        raise AgentTableError(f"{rec_path} is incomplete ({rec['metrics']['stopped']}); it's never reported")
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)
    files = {}
    for name in ("calls", "ledger"):
        p = output_path(repo_root, rec["outputs"][name]["path"])
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
        # Three views of the same passes (decision 79): what ships (the rows as they ran), the LLM
        # re-ranker (the LLM's own answer), and the matcher alone. A run from before the shipped
        # flow has no separate re-ranker view: it ran as the re-ranker.
        shipped_view = "llm_decision" in base_row(by_rep)
        rer_by_rep = {k: [reranker_row(r) for r in v] for k, v in by_rep.items()}
        agent = {k: am.summary(v, family_of) for k, v in by_rep.items()}
        reranker = {k: am.summary(v, family_of) for k, v in rer_by_rep.items()}
        base = by_rep[reps[0]]
        m = matcher_summary(base, family_of)
        loo_by_rep = {k: [r for r in rer_by_rep[k] if r["kind"] == "loo"] for k in reps}
        if test:
            # On test, "unknown" means a fault with no entry: 16-20 and the leave-one-out cases
            # (PROTOCOL). Unknown rows are read as loo rows for the keep rule's B2 (decision 77).
            # The keep rule is reported, not applied (S0 answer 19): decision 79 already ships.
            unknown_rows = {k: [r if r["kind"] == "loo" else {**r, "kind": "loo"} for r in rer_by_rep[k]
                                if r["kind"] in ("loo", "unknown")] for k in reps}
            keep_agent = [{"top1": reranker[k]["top1"], "family": reranker[k]["family"],
                           "unknowns_declined": dm.decline_share([am.to_case(r, keep_rule=True)
                                                                  for r in unknown_rows[k]])} for k in reps]
            m_unknown = [matcher_case(r) for r in base if r["kind"] in ("loo", "unknown")]
            keep_matcher = {"top1": m["top1"], "family": m["family"], "unknowns_declined": dm.decline_share(m_unknown)}
            keep = {**am.keep_rule(keep_agent, keep_matcher), "applicable": True, "applied": False,
                    "unknowns": "faults 16-20 and leave-one-out (1, 4, 5, 13)"}
        elif all(loo_by_rep.values()):
            # The keep rule is about the LLM's re-ranking role, so it's read on the re-ranker view.
            keep_agent = [{"top1": reranker[k]["top1"], "family": reranker[k]["family"],
                           "unknowns_declined": dm.decline_share([am.to_case(r, keep_rule=True)
                                                                  for r in loo_by_rep[k]])} for k in reps]
            keep_matcher = {"top1": m["top1"], "family": m["family"], "unknowns_declined": m["loo_declined"]}
            keep = {**am.keep_rule(keep_agent, keep_matcher), "applicable": True}
        else:
            # A run without leave-one-out cases (the tuning subset, decision 77) has no
            # "unknowns declined", so the keep rule can't be read on it.
            keep = {"applicable": False, "reason": NO_UNKNOWNS, "keep": None, "better_on": [], "worse_on": []}
        m_known = [matcher_case(r) for r in base if r["kind"] == "known"]

        def paired_for(view):
            out_ = {}
            for k in reps:
                a_known = [am.to_case(r) for r in view[k] if r["kind"] == "known"]
                d, lo, hi = dm.paired_top1_bootstrap(a_known, m_known, np.random.default_rng(BOOTSTRAP_SEED),
                                                     **({"n": n_boot} if n_boot else {}))
                out_[str(k)] = {"difference": d, "lo": lo, "hi": hi}
            return out_
        rer_rows = [r for k in reps for r in rer_by_rep[k]]
        results[st] = {"agent": {str(k): v for k, v in agent.items()}, "matcher": m,
                       "reranker": {str(k): v for k, v in reranker.items()}, "shipped_flow": shipped_view,
                       "keep_rule": keep, "paired": paired_for(by_rep),
                       "paired_reranker": paired_for(rer_by_rep),
                       # the LLM's own answers: its stated confidence, its stability, its family notes
                       "confidence": am.confidence_table(rer_rows), "agreement": am.agreement(rer_rows),
                       "not_in_library": am.not_in_library_secondary([r for r in rer_rows if r["kind"] == "loo"]),
                       # what's shown: why a known case missed
                       "misses": am.miss_labels(srows),
                       "vetoes": sum(r["outcome"] == "vetoed" for r in srows),
                       "tie_breaks": sum(bool(r.get("tie_break")) and r["outcome"] == "proposed" for r in srows),
                       "latency_cost": am.latency_cost(srows, ledger)}
        if test:
            results[st]["unknowns"] = {view: {str(k): unknown_summary(v[k]) for k in reps}
                                       for view, v in (("shipped", by_rep), ("reranker", rer_by_rep))}
            results[st]["unknowns"]["matcher"] = unknown_summary(base, matcher=True)
            results[st]["latency_cost"]["cold_start"] = "not applicable (a batch run; S0 answer 19)"
            results[st]["llm_only"] = "not run (S0 answer 18)"
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    tables_dir = Path(tables_dir or diag_table.DEFAULT_TABLES)
    tables_dir.mkdir(parents=True, exist_ok=True)
    name = "test_agent_table" if test else "agent_table"
    md = tables_dir / f"{stamp}_{name}.md"
    outputs = {"table": md}
    if test:
        # The unstable cases name test runs: listed only in a copy in the sealed folder (S0 answer 21).
        md.write_text(markdown(results, rec, list_unstable=False))
        sealed_md = loader.SEALED_ROOT / "test_outputs" / f"{stamp}_{name}" / f"{name}.md"
        sealed_md.parent.mkdir(parents=True, exist_ok=False)
        sealed_md.write_text(markdown(results, rec))
        outputs["table_with_cases"] = sealed_md
    else:
        md.write_text(markdown(results, rec))
    recorded = _plain(results)
    for st in recorded:                     # run records hold short lists only: the cases are in the table
        a = recorded[st]["agreement"]
        a["unstable"] = len(a["unstable"])
    run_key = "test_agent_run" if test else "agent_run"
    record = run_record.write(name, config={run_key: rec_path.relative_to(repo_root).as_posix(),
                                            f"{run_key}_sha256": run_record.sha256(rec_path)},
                              seeds={"bootstrap": BOOTSTRAP_SEED}, metrics=diag_table.numbers(recorded),
                              outputs=outputs, commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    out(f"table: {md}\nrun record: {record}")
    return results, record


def unknown_summary(rows, matcher=False) -> dict:
    """Faults 16-20 and the leave-one-out cases, correct only when declined (PROTOCOL v2):
    overall and by fault, from one repeat's rows (or the matcher's own answer on them)."""
    case = matcher_case if matcher else am_case
    out = {}
    for kind, faults in (("unknown", UNKNOWN_FAULTS), ("loo", tuple(LOO_TEST))):
        cs = [case(r) for r in rows if r["kind"] == kind]
        out[kind] = {"cases": len(cs), "declined": dm.decline_share(cs) if cs else None,
                     "by_fault": {str(f): _declined_share([c for c in cs if c.fault == f]) for f in faults}}
    return out


def am_case(r):
    from eval import agent_metrics as am
    return am.to_case(r)


def _declined_share(cs):
    return {"cases": len(cs), "declined": dm.decline_share(cs) if cs else None}


def base_row(by_rep):
    """Any one row (the views are decided per run)."""
    return next(r for v in by_rep.values() for r in v)


def _plain(x):
    """Tuples as lists and unknown scalars as themselves, for the record."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _pct(x):
    return "—" if x is None else f"{100 * float(x):.1f}"


def markdown(results, rec, list_unstable=True) -> str:
    test = rec.get("name") == "test_agent_run"
    lines = [f"# Agent table ({'test' if test else 'dev'})", "",
             f"Run: {rec['config']['mode']}, library as of {rec['config']['library_as_of']}, "
             f"prompt {rec['config'].get('prompt_sha256', '')[:12]}…; rates in %.", ""]
    for st, r in results.items():
        lines += [f"## {st.capitalize()}", "", "| Method | Top-1 | Top-3 | Family | Wrongly declined | "
                  "False alerts declined | Leave-one-out declined |", "|---|---|---|---|---|---|---|"]
        m = r["matcher"]
        lines.append(f"| matcher | {_pct(m['top1'])} | {_pct(m['top3'])} | {_pct(m['family'])} | "
                     f"{_pct(m['wrongly_declined'])} | {_pct(m['false_alert_declined'])} | {_pct(m['loo_declined'])} |")
        views = [("shipped", r["agent"]), ("re-ranker", r["reranker"])] if r.get("shipped_flow") else \
            [("agent", r["agent"])]
        for name, by in views:
            for k, a in by.items():
                lines.append(f"| {name}, repeat {k} | {_pct(a['top1'])} | {_pct(a['top3'])} | {_pct(a['family'])} | "
                             f"{_pct(a['wrongly_declined'])} | {_pct(a['false_alert_declined'])} | "
                             f"{_pct(a['loo_declined'])} |")
        kr = r["keep_rule"]
        verdict = (f"Keep rule: {kr['reason']}." if not kr["applicable"] else
                   f"Keep rule: {'KEEP' if kr['keep'] else 'not kept'}; better on {kr['better_on'] or 'none'}, "
                   f"worse on {kr['worse_on'] or 'none'}.")
        if kr.get("applied") is False:
            verdict += f" Reported, not applied (unknowns: {kr['unknowns']})."
        lines += ["", verdict, ""]
        if "unknowns" in r:
            u = r["unknowns"]
            lines += ["Unknown faults (16–20) and leave-one-out, correct only when declined (shipped flow and "
                      "re-ranker per repeat; the matcher alone):", "",
                      "| View | 16–20 declined | " + " | ".join(str(f) for f in UNKNOWN_FAULTS) +
                      " | Leave-one-out declined | " + " | ".join(str(f) for f in LOO_TEST) + " |",
                      "|---|---|" + "---|" * len(UNKNOWN_FAULTS) + "---|" + "---|" * len(LOO_TEST)]
            rows_ = [("matcher", u["matcher"])] + [(f"{view}, repeat {k}", s) for view in ("shipped", "reranker")
                                                    for k, s in u[view].items()]
            for label, s in rows_:
                lines.append(f"| {label} | {_pct(s['unknown']['declined'])} | " +
                             " | ".join(_pct(s["unknown"]["by_fault"][str(f)]["declined"]) for f in UNKNOWN_FAULTS) +
                             f" | {_pct(s['loo']['declined'])} | " +
                             " | ".join(_pct(s["loo"]["by_fault"][str(f)]["declined"]) for f in LOO_TEST) + " |")
            lines += ["", f"LLM only: {r['llm_only']}. Cold start: {r['latency_cost']['cold_start']}.", ""]
        lines += [f"Unstable across repeats: {len(r['agreement']['unstable'])} of {r['agreement']['cases']} cases.", ""]
        if list_unstable:
            lines += [f"- {case} ({stage})" for case, stage in r["agreement"]["unstable"]]
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    modes = parser.add_mutually_exclusive_group(required=True)
    for m in ("dry-run", "project-cost", "tuning", "evaluation", "replay-evaluation"):
        modes.add_argument(f"--{m}", dest="mode", action="store_const", const=m)
    modes.add_argument("--table", type=Path, default=None, help="an agent_run record")
    parser.add_argument("--library-as-of", default=None)
    parser.add_argument("--budget", type=float, default=None, help="rupees (decision 76)")
    parser.add_argument("--prompt-sha256", default=None)
    parser.add_argument("--billing-tier", choices=BILLING_TIERS, default=None,
                        help="paid runs (required): the key's project tier, recorded as billing_tier (decision 76)")
    parser.add_argument("--min-interval", type=float, default=0.0,
                        help="paid runs: minimum seconds between the starts of two real API calls (cache hits "
                             "aren't paced); recorded in the run record")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--split", choices=split_mod.NAMES, default="dev",
                        help="test: the sealed testing files, only with EVAL_MODE=1 (Raj runs it)")
    parser.add_argument("--fingerprint-record", type=Path, default=None,
                        help="test: the diag_fingerprint record the dev matcher rules must reproduce")
    parser.add_argument("--dry-run-record", type=Path, default=None,
                        help="test, paid run: the test_agent_dry_run record from this commit")
    parser.add_argument("--repeats", type=int, default=None,
                        help="test, paid run: defaults to the dry run's repeats_allowed (S0 answer 17)")
    parser.add_argument("--after-budget-stop", type=Path, default=None, metavar="TEST_AGENT_RUN_RECORD",
                        help="test, paid run: the pre-registered rerun after a budget stop (TEST_PLAN section 6): "
                             "3 repeats, budget at most Rs 500 minus that record's spend")
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
    if args.mode in ("tuning", "evaluation") and args.billing_tier is None:
        parser.error("--tuning and --evaluation need --billing-tier (free or tier-1; decision 76)")
    if args.mode in ("tuning", "evaluation"):
        from dotenv import load_dotenv                       # the paid runs read the key from .env
        load_dotenv(override=False)
    try:
        run(args.mode, library_as_of=args.library_as_of, budget=args.budget, prompt_hash=args.prompt_sha256,
            bundle_dir=args.bundle, allow_dirty=args.allow_dirty, min_interval=args.min_interval,
            billing_tier=args.billing_tier, split=args.split, fingerprint_record=args.fingerprint_record,
            dry_run_record=args.dry_run_record, repeats=args.repeats, after_budget_stop=args.after_budget_stop)
    except (ValueError, FileExistsError, FileNotFoundError, loader.LoaderError, run_record.RunRecordError,
            drv.CalibrationError, evidence_normals.NormalsError, cases_mod.CasesError, AgentTableError,
            diag_table.DiagTableError, bundle_mod.BundleError, llm.LLMError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
