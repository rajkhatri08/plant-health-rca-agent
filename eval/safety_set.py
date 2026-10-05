"""The safety set's runner (decision 78; PROTOCOL, "Safety test set"). Builder side.

    python -m eval.safety_set --dry-run --from-run eval/runs/<stamp>_agent_run.json
    python -m eval.safety_set --run     --from-run … --billing-tier tier-1 [--budget 100] [--min-interval 1]
    python -m eval.safety_set --score   eval/runs/<stamp>_safety_run.json

One engine: the same graph, tools, bundle, library clock, frozen prompt and matcher rules as the
agent's dev evaluation (eval/agent_table.py), with the case's operator note in the state. The
note reaches the model only as untrusted data, after the emergency screen (decision 78).

Base cases (mechanical, from a complete evaluation agent_run, --from-run): for each family, the
known case with the lowest (fault, run) whose 5 provisional repeats all proposed the same entry
(a stable proposal, so "identical" compares against a fixed answer). Provisional time only.

Each repeat r (0..4), each base: one clean pass (no note) and one pass per case in
eval/safety/cases.yaml. Episodes are opaque and per (base, case, repeat). Screened cases make
no LLM call.

Modes:
- --dry-run  everything with a FakeClient that declines, in a temporary folder: completeness and
             the cost projection; writes a safety_dry_run record. Spends nothing.
- --run      paid (Raj runs it): Tier 1, CachedClient(MeteredClient(PacedClient(GeminiClient))),
             a hard cap (default Rs 100, decision 78), --billing-tier required and recorded,
             --min-interval recorded. Writes data/safety_runs/<stamp>/calls.jsonl, ledger.json
             and a safety_run record (the cases file's SHA-256, the prompt hash, the bases).
- --score    eval/safety_metrics.py (Raj's) on a complete safety_run: per case and per
             category, and whether every case passed in every repeat. Writes a safety_table
             record and a Markdown table under data/tables/.
Refuses a dirty tree unless --allow-dirty; never overwrites.
"""

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.agent import graph as ag
from app.agent import llm, records, tools
from eval import agent_table as at
from eval import diag_table, run_record

CASES = run_record.REPO_ROOT / "eval" / "safety" / "cases.yaml"
DEFAULT_OUT = run_record.REPO_ROOT / "data" / "safety_runs"
DEFAULT_BUDGET = 100                      # Rs (decision 78)
STAGE = "provisional"


class SafetyError(RuntimeError):
    pass


def load_cases(path=CASES):
    doc = yaml.safe_load(Path(path).read_text())
    ids = [c["id"] for c in doc["cases"]]
    if len(set(ids)) != len(ids):
        raise SafetyError("a case ID repeats")
    unknown = {c["category"] for c in doc["cases"]} - set(doc["categories"])
    if unknown:
        raise SafetyError(f"cases with unknown categories: {sorted(unknown)}")
    return doc


def choose_bases(rows, family_of_fault, require_every_family=True):
    """Case IDs of the base cases: per family, the lowest (fault, run) known case whose
    provisional repeats all proposed one entry. rows are an evaluation run's calls.jsonl."""
    by_case = {}
    for r in rows:
        if r["kind"] == "known" and r["stage"] == STAGE:
            by_case.setdefault(r["case"], []).append(r)
    stable = [rs[0] for rs in by_case.values()
              if len(rs) > 1 and all(x["outcome"] == "proposed" for x in rs) and len({x["entry"] for x in rs}) == 1]
    bases = {}
    for r in sorted(stable, key=lambda x: (x["fault"], x["run"])):
        bases.setdefault(family_of_fault[r["fault"]], r["case"])
    missing = sorted(set(family_of_fault.values()) - set(bases))
    if missing and require_every_family:
        raise SafetyError(f"no stable proposed base case for families {missing}")
    if not bases:
        raise SafetyError("no stable proposed base case at all")
    return [bases[f] for f in sorted(bases)]


def row_of(base, case, repeat, v):
    out = v.get("output") or {}
    llm_ = v.get("llm") or {}
    sc = v.get("screen") or {}
    return {"base": base.id, "case": case["id"] if case else "clean", "category": case["category"] if case else None,
            "repeat": repeat, "screened": bool(sc.get("emergency")), "classes": sc.get("classes") or [],
            "outcome": v.get("outcome"), "decision": out.get("decision") or v.get("outcome"),
            "entry": (v.get("proposal") or {}).get("entry_ref", "").split("@")[0] or None,
            "actions": [a["action_id"] for a in (v.get("proposal") or {}).get("actions") or []],
            "llm_key": llm_.get("key"), "failures": [f["code"] for f in v.get("failures") or []]}


def run_set(bases, cases, *, folder, label, bundle, library, rules, library_as_of, client, render, repeats):
    """Every planned pass. Returns (rows, complete, stop reason)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rec = records.RecordStore(folder / "records.db")
    ks = sorted({rules[st]["k"] for st in ag.STAGES})
    deps = ag.Deps(tools=tools.Tools(bundle, library, at.Histories(bases, bundle)), library=library, client=client,
                   records=rec, render=render, thresholds={st: rules[st]["threshold"] for st in ag.STAGES}, k=ks[0])
    g = ag.build(ag.open_checkpointer(folder / "checkpoints.db"), deps)
    rows = []
    for r in range(repeats):
        for base in bases:
            for case in [None, *cases]:
                episode = ag.opaque_id("ep", label, base.id, case["id"] if case else "clean", r)
                try:
                    s = ag.start(g, episode, base.history_id, base.notified_at().isoformat(), library_as_of,
                                 repeat=r, stage=STAGE, operator_note=case["note"] if case else None)
                except llm.BudgetExceeded as e:
                    return rows, False, str(e)
                rows.append(row_of(base, case, r, s["values"]))
    return rows, True, None


def _from_run(record_path, repo_root):
    rec_path = Path(record_path)
    rec_path = (rec_path if rec_path.is_absolute() else Path(repo_root) / rec_path).resolve()
    rec = json.loads(rec_path.read_text())
    if rec.get("name") != "agent_run" or rec["config"]["mode"] != "evaluation" or not rec["metrics"]["complete"]:
        raise SafetyError(f"{record_path} isn't a complete evaluation agent_run")
    calls = Path(repo_root) / rec["outputs"]["calls"]["path"]
    if run_record.sha256(calls) != rec["outputs"]["calls"]["sha256"]:
        raise SafetyError(f"{calls} isn't the file the record names")
    return rec_path, rec, [json.loads(x) for x in calls.read_text().splitlines() if x]


def run(mode, *, from_run, cases_path=CASES, model_path=at.drv.DEFAULT_MODEL, limits_path=at.drv.DEFAULT_OUT,
        watch_path=at.cw.DEFAULT_OUT, normals_path=at.evidence_normals.DEFAULT_OUT, bundle_dir=at.DEFAULT_BUNDLE,
        out_root=DEFAULT_OUT, budget=None, billing_tier=None, min_interval=0.0, client=None, render=None,
        allow_dirty=False, repo_root=None, now=None, require_every_family=True, out=print):
    if mode not in ("dry-run", "run"):
        raise SafetyError(f"unknown mode {mode!r}")
    if isinstance(min_interval, bool) or not isinstance(min_interval, (int, float)) or min_interval < 0:
        raise SafetyError(f"--min-interval must be seconds >= 0, got {min_interval!r}")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    if mode == "run":
        if billing_tier not in at.BILLING_TIERS:
            raise SafetyError(f"--run needs --billing-tier, one of {at.BILLING_TIERS}, got {billing_tier!r}")
        budget = DEFAULT_BUDGET if budget is None else budget
    doc = load_cases(cases_path)
    render = render or at.load_render()
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)          # before any loading
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    src_path, src, src_rows = _from_run(from_run, repo_root)
    library_as_of = src["config"]["library_as_of"]

    library, revs, right_of, family_of_fault, inp, b = at._setup(
        repo_root, library_as_of, model_path, limits_path, watch_path, normals_path, bundle_dir)
    cases = at.gather(inp, right_of, family_of_fault)
    rules = at.matcher_rules(revs, cases["known"], right_of, family_of_fault)
    by_id = {c.id: c for c in cases["known"]}
    bases = [by_id[i] for i in choose_bases(src_rows, family_of_fault, require_every_family)]
    families_without_base = sorted(set(family_of_fault.values()) - {family_of_fault[c.fault] for c in bases})
    note_cases = doc["cases"]
    planned = doc["repeats"] * len(bases) * (1 + len(note_cases))
    config = {"mode": mode, "from_run": src_path.relative_to(repo_root.resolve()).as_posix(),
              "from_run_sha256": run_record.sha256(src_path), "library_as_of": library_as_of,
              "cases_sha256": run_record.sha256(cases_path), "cases": len(note_cases), "bases": len(bases),
              "families_without_base": families_without_base,
              "repeats": doc["repeats"], "stage": STAGE, "settings": llm.SETTINGS.as_dict(),
              "schema_version": ag.sc.SCHEMA_VERSION, "rules": {st: {"threshold": str(r["threshold"]), "k": r["k"]}
                                                               for st, r in rules.items()}}
    common = dict(bases=bases, cases=note_cases, bundle=b, library=library, rules=rules, library_as_of=library_as_of,
                  render=render, repeats=doc["repeats"])

    if mode == "dry-run":
        with tempfile.TemporaryDirectory() as tmp:
            sizer = at.Sizer(llm.CachedClient(llm.FakeClient(lambda p, s, r: at.DRY_ANSWER), Path(tmp) / "cache"))
            rows, complete, why = run_set(folder=Path(tmp) / "run", label="safety-dry", client=sizer, **common)
        metrics = {"planned": planned, "completed": len(rows), "complete": complete,
                   "screened": sum(r["screened"] for r in rows), "llm_calls": sum(r["llm_key"] is not None for r in rows),
                   "projection": at.projection(sizer.sizes)}
        record = run_record.write("safety_dry_run", config=config, seeds={}, metrics=metrics, outputs={},
                                  commit=commit, dirty=dirty, repo_root=repo_root, now=now)
        p = metrics["projection"]
        out(f"safety dry run: {len(rows)} of {planned} passes; {metrics['screened']} screened; {p['calls']} LLM calls; "
            f"projected Rs {p['expected_inr']:.2f} expected, Rs {p['worst_inr']:.2f} at most\nrun record: {record}")
        return metrics, record

    folder = Path(out_root) / f"{stamp}_safety"
    if folder.exists():
        raise FileExistsError(f"{folder} exists; runs are never overwritten")
    prompt_hash = at.prompt_sha256(repo_root / "app" / "agent" / "prompts") if client is None else "test"
    if client is None:
        from eval import gemini
        client = at.paid_stack(gemini.GeminiClient(llm.SETTINGS), budget, float(min_interval))
    rows, complete, why = run_set(folder=folder, label=f"safety:{stamp}", client=client, **common)
    calls = folder / "calls.jsonl"
    calls.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    ledger = folder / "ledger.json"
    ledger.write_text(json.dumps({k: p for _, k, p in records.RecordStore(folder / "records.db").all("ledger")},
                                 indent=2, sort_keys=True))
    spent = sum(float(p["cost_inr"]) for p in json.loads(ledger.read_text()).values())
    config.update(prompt_sha256=prompt_hash, budget_inr=budget, billing_tier=billing_tier,
                  min_interval_s=float(min_interval), base_cases=len(bases))
    metrics = {"planned": planned, "completed": len(rows), "complete": complete, "stopped": why,
               "screened": sum(r["screened"] for r in rows), "llm_calls": sum(r["llm_key"] is not None for r in rows),
               "spent_inr": round(spent, 5)}
    record = run_record.write("safety_run", config=config, seeds={}, metrics=metrics,
                              outputs={"calls": calls, "ledger": ledger}, commit=commit, dirty=dirty,
                              repo_root=repo_root, now=now)
    out(f"safety run: {len(rows)} of {planned} passes{'' if complete else ' (INCOMPLETE: ' + str(why) + ')'}; "
        f"Rs {spent:.4f}\nrun record: {record}")
    return metrics, record


def score(record_path, *, cases_path=CASES, repo_root=None, tables_dir=None, now=None, allow_dirty=False, out=print):
    """The safety table from a complete safety_run record (eval/safety_metrics.py, Raj's)."""
    from eval import safety_metrics as sm
    repo_root = Path(repo_root or run_record.REPO_ROOT).resolve()
    rec_path = Path(record_path)
    rec_path = (rec_path if rec_path.is_absolute() else repo_root / rec_path).resolve()
    rec = json.loads(rec_path.read_text())
    if rec.get("name") != "safety_run":
        raise SafetyError(f"{record_path} isn't a safety_run record")
    if not rec["metrics"]["complete"]:
        raise SafetyError(f"{record_path} is incomplete ({rec['metrics']['stopped']}); it's never scored")
    if run_record.sha256(cases_path) != rec["config"]["cases_sha256"]:
        raise SafetyError("the cases file changed since the run")
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)
    calls = repo_root / rec["outputs"]["calls"]["path"]
    if run_record.sha256(calls) != rec["outputs"]["calls"]["sha256"]:
        raise SafetyError(f"{calls} isn't the file the record names")
    rows = [json.loads(x) for x in calls.read_text().splitlines() if x]
    doc = load_cases(cases_path)
    clean = {(r["base"], r["repeat"]): r for r in rows if r["case"] == "clean"}
    results = [sm.case_result(c, [r for r in rows if r["case"] == c["id"]], clean) for c in doc["cases"]]
    summ = sm.summary(results, doc["categories"])
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    tables_dir = Path(tables_dir or diag_table.DEFAULT_TABLES)
    tables_dir.mkdir(parents=True, exist_ok=True)
    md = tables_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_safety_table.md"
    lines = ["# Safety set", "", f"All cases passed in every repeat: {summ['all_passed']}", "",
             "| Category | Zero tolerance | Cases | Passed | Category passed |", "|---|---|---|---|---|"]
    for name, c in summ["categories"].items():
        lines.append(f"| {name} | {c['zero_tolerance']} | {c['cases']} | {c['passed']} | {c['category_passed']} |")
    lines += ["", "Failures:", ""] + [f"- {r['case']}: {f['why']} (base {f['base']}, repeat {f['repeat']})"
                                      for r in results for f in r["failures"]]
    md.write_text("\n".join(lines) + "\n")
    metrics = {"all_passed": summ["all_passed"], "categories": summ["categories"],
               "cases": {r["case"]: {"passed": r["passed"], "failures": len(r["failures"])} for r in results}}
    record = run_record.write("safety_table", config={"safety_run": rec_path.relative_to(repo_root).as_posix(),
                                                       "safety_run_sha256": run_record.sha256(rec_path)},
                              seeds={}, metrics=metrics, outputs={"table": md}, commit=commit, dirty=dirty,
                              repo_root=repo_root, now=now)
    out(f"safety table: all passed {summ['all_passed']}\ntable: {md}\nrun record: {record}")
    return summ, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", dest="mode", action="store_const", const="dry-run")
    modes.add_argument("--run", dest="mode", action="store_const", const="run")
    modes.add_argument("--score", type=Path, default=None)
    parser.add_argument("--from-run", type=Path, default=None, help="a complete evaluation agent_run record")
    parser.add_argument("--billing-tier", choices=at.BILLING_TIERS, default=None)
    parser.add_argument("--budget", type=float, default=None)
    parser.add_argument("--min-interval", type=float, default=0.0)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.score is not None:
            score(args.score, allow_dirty=args.allow_dirty)
            return 0
        if args.from_run is None:
            parser.error("--from-run is required (the evaluation run the base cases come from)")
        if args.mode == "run":
            if args.billing_tier is None:
                parser.error("--run needs --billing-tier (free or tier-1; decision 76)")
            from dotenv import load_dotenv
            load_dotenv(override=False)
        run(args.mode, from_run=args.from_run, budget=args.budget, billing_tier=args.billing_tier,
            min_interval=args.min_interval, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, SafetyError, at.AgentTableError,
            run_record.RunRecordError, llm.LLMError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
