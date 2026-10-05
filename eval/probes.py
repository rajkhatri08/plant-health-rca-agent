"""The memorization probes (eval/LEAKAGE.md, wall 2): run once on the pinned model, results
saved in eval/probes/. Builder side.

    python -m eval.probes --dry-run
    python -m eval.probes --run --billing-tier tier-1 [--budget 5]

Each probe (eval/probes/probes.yaml, PROPOSED) shows the model only agent-visible material and
asks whether it recognises the plant or a disturbance. Prompts are leak-checked before they're
sent, so a probe can never hand the model the answer. The model answers in a small JSON schema
(PROBE_SCHEMA). A probe recognises the plant when the answer trips the leak scan's patterns
(the benchmark's or a source's name, a raw name, a label) or gives a fault number.

--run (paid; Raj runs it): the pinned settings (decision 76), 1 repeat, behind the budget meter
(default Rs 5) and the cache, --billing-tier required and recorded. Writes
eval/probes/<stamp>_answers.json (committed: the answers are the finding) and a probes run
record. --dry-run: a FakeClient that recognises nothing; checks the plumbing, writes nothing.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.agent import llm
from app.library import store
from eval import agent_table as at
from eval import run_record
from shared import leak_scan

PROBES = run_record.REPO_ROOT / "eval" / "probes" / "probes.yaml"
OUT_DIR = run_record.REPO_ROOT / "eval" / "probes"
DEFAULT_BUDGET = 5
LIB_T = datetime(2026, 10, 5, tzinfo=timezone.utc)
PROBE_SCHEMA = llm.OutputSchema("probe-1", {
    "type": "object",
    "properties": {"recognised": {"type": "boolean"}, "name": {"type": ["string", "null"]},
                   "source": {"type": ["string", "null"]}, "number": {"type": ["integer", "null"]},
                   "explanation": {"type": "string", "maxLength": 400}},
    "required": ["recognised", "name", "source", "number", "explanation"], "additionalProperties": False})
FAKE_ANSWER = json.dumps({"recognised": False, "name": None, "source": None, "number": None,
                          "explanation": "dry run"})


class ProbeError(RuntimeError):
    pass


def material(spec, repo_root):
    """The agent-visible text a probe shows: the tag register, the loop map, or one entry."""
    repo_root = Path(repo_root)
    if spec == "tag_register":
        rows = yaml.safe_load((repo_root / "library" / "tags.yaml").read_text())["tags"]
        return "\n".join(f"{r['tag']}: {r['description']} ({r['units']})" for r in rows)
    if spec == "loop_map":
        tags = {r["tag"]: r["description"] for r in yaml.safe_load((repo_root / "library" / "tags.yaml").read_text())["tags"]}
        loops = yaml.safe_load((repo_root / "library" / "loops.yaml").read_text())["loops"]
        return "\n".join(f"{lp['id']}: holds {lp['controlled']} ({tags.get(lp['controlled'], '')}) by moving "
                         f"{lp['output'].get('valve') or 'the setpoint of ' + lp['output'].get('setpoint_of', '')}"
                         for lp in loops)
    if spec.startswith("entry:"):
        got = store.load().get(spec.split(":", 1)[1], LIB_T)
        if got is None:
            raise ProbeError(f"no entry in force for {spec}")
        rev = got.stored.revision
        return f"{rev.title}\n{rev.description}"
    raise ProbeError(f"unknown material {spec!r}")


def prompts(doc, repo_root):
    """[(probe id, prompt)], each leak-checked (the probe must not contain the answer)."""
    out = []
    for p in doc["probes"]:
        q = doc[f"question_{p['question']}"]
        text = f"{q}\n\n---\n{material(p['material'], repo_root)}\n---"
        leak_scan.check(text, f"probe {p['id']}")
        out.append((p["id"], text))
    return out


def verdict(answer_raw, parsed):
    """{"recognised": bool, "model_says": bool, "leaks": [...], "number": int|None}."""
    leaks = sorted(set(leak_scan.find_leaks(answer_raw or "")))
    number = (parsed or {}).get("number")
    says = bool((parsed or {}).get("recognised"))
    return {"recognised": bool(leaks) or number is not None, "model_says": says, "leaks": leaks, "number": number}


def run(mode, *, probes_path=PROBES, out_dir=OUT_DIR, budget=None, billing_tier=None, min_interval=0.0,
        client=None, repo_root=None, allow_dirty=False, now=None, out=print):
    if mode not in ("dry-run", "run"):
        raise ProbeError(f"unknown mode {mode!r}")
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    doc = yaml.safe_load(Path(probes_path).read_text())
    ps = prompts(doc, repo_root)
    if mode == "dry-run":
        fake = llm.FakeClient(lambda p, s, r: FAKE_ANSWER)
        results = {pid: verdict(fake.complete(text, PROBE_SCHEMA, repeat=0).raw, json.loads(FAKE_ANSWER))
                   for pid, text in ps}
        out(f"probes dry run: {len(results)} probes, prompts leak-checked; nothing written")
        return results, None
    if billing_tier not in at.BILLING_TIERS:
        raise ProbeError(f"--run needs --billing-tier, one of {at.BILLING_TIERS}, got {billing_tier!r}")
    budget = DEFAULT_BUDGET if budget is None else budget
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    answers_path = Path(out_dir) / f"{now.strftime('%Y%m%dT%H%M%SZ')}_answers.json"
    if answers_path.exists():
        raise FileExistsError(f"{answers_path} exists; probe results are never overwritten")
    if client is None:
        from eval import gemini
        client = at.paid_stack(gemini.GeminiClient(llm.SETTINGS), budget, float(min_interval))
    answers, results = {}, {}
    for pid, text in ps:
        r = client.complete(text, PROBE_SCHEMA, repeat=0)
        answers[pid] = {"prompt": text, "raw": r.raw, "model_version": r.model_version,
                        "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "tokens_thinking": r.tokens_thinking}
        results[pid] = verdict(r.raw, r.parsed)
    answers_path.parent.mkdir(parents=True, exist_ok=True)
    answers_path.write_text(json.dumps({"answers": answers, "results": results}, indent=2, sort_keys=True) + "\n")
    metrics = {"probes": len(ps), "recognised": sum(v["recognised"] for v in results.values()),
               "model_says": sum(v["model_says"] for v in results.values()),
               "by_probe": {k: {"recognised": v["recognised"], "model_says": v["model_says"], "leaks": len(v["leaks"])}
                            for k, v in results.items()}}
    config = {"probes_sha256": run_record.sha256(probes_path), "settings": llm.SETTINGS.as_dict(),
              "schema_version": PROBE_SCHEMA.version, "billing_tier": billing_tier, "budget_inr": budget,
              "min_interval_s": float(min_interval)}
    record = run_record.write("probes", config=config, seeds={}, metrics=metrics, outputs={"answers": answers_path},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    out(f"probes: {metrics['recognised']} of {metrics['probes']} recognised the plant\nanswers: {answers_path}\n"
        f"run record: {record}")
    return results, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", dest="mode", action="store_const", const="dry-run")
    modes.add_argument("--run", dest="mode", action="store_const", const="run")
    parser.add_argument("--billing-tier", choices=at.BILLING_TIERS, default=None)
    parser.add_argument("--budget", type=float, default=None)
    parser.add_argument("--min-interval", type=float, default=0.0)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "run":
        if args.billing_tier is None:
            parser.error("--run needs --billing-tier (free or tier-1; decision 76)")
        from dotenv import load_dotenv
        load_dotenv(override=False)
    try:
        run(args.mode, budget=args.budget, billing_tier=args.billing_tier, min_interval=args.min_interval,
            allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, ProbeError, run_record.RunRecordError, llm.LLMError,
            leak_scan.LeakError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())