"""Build the public demo's diagnosis once (week 6 S9; decision 79). Builder side; paid, Raj runs it.

    python -m eval.build_demo --from-run eval/runs/<stamp>_agent_run.json --billing-tier tier-1
                              [--budget 5] [--min-interval 1]

Runs both episodes (app/agent/demo.EPISODES: app/replay/run_v2.csv and app/replay/episode2.csv,
each from its first alert; bundle pca_v3) through the shipped graph for the three fixed notes
(app/agent/demo.NOTES) at both diagnosis times, twelve passes in all, with
GeminiClient behind the budget meter, the pacer and a cache. Then it proves the cache is
complete: the same six passes through llm.ReplayClient give identical views. Every cache file and
view is leak-checked. Only then are app/replay/llm_cache/ and app/replay/demo.json written
(committed with the code; the API serves them). Never overwrites either.

The demo uses the dev evaluation's settings (--from-run, a complete evaluation agent_run): its
library clock, the matcher's thresholds and k, and its frozen prompt, which must be the committed
one. The emergency note and any pass the matcher declines make no call; at most eight calls,
well under Rs 1.
Writes a build_demo run record (the files' SHA-256, the spend, each view's outcome).
"""

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.agent import demo, llm, tools
from app.agent import graph as ag
from app.detector import bundle as bundle_mod
from app.library import store
from eval import agent_table as at
from eval import run_record
from shared import leak_scan

DEFAULT_BUDGET = 5                          # Rs


class BuildDemoError(RuntimeError):
    pass


def _from_run(record_path, repo_root):
    p = Path(record_path)
    p = (p if p.is_absolute() else Path(repo_root) / p).resolve()
    rec = json.loads(p.read_text())
    if rec.get("name") != "agent_run" or rec["config"]["mode"] != "evaluation" or not rec["metrics"]["complete"]:
        raise BuildDemoError(f"{record_path} isn't a complete evaluation agent_run")
    return p, rec


def run(*, from_run, billing_tier, budget=None, min_interval=0.0, provider=None, render=None, out_dir=None,
        bundle_dir=None, streams=None, repo_root=None, allow_dirty=False, now=None, out=print):
    if billing_tier not in at.BILLING_TIERS:
        raise BuildDemoError(f"--billing-tier is one of {at.BILLING_TIERS}, got {billing_tier!r}")
    if isinstance(min_interval, bool) or not isinstance(min_interval, (int, float)) or min_interval < 0:
        raise BuildDemoError(f"--min-interval must be seconds >= 0, got {min_interval!r}")
    budget = DEFAULT_BUDGET if budget is None else budget
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    out_dir = Path(out_dir or demo.DEMO_DIR)
    for target in (out_dir / demo.CONFIG, out_dir / demo.CACHE):
        if target.exists():
            raise FileExistsError(f"{target} exists; the demo is built once (delete both to rebuild)")
    src_path, src = _from_run(from_run, repo_root)
    cfg = src["config"]
    if render is None:
        actual = at.prompt_sha256(repo_root / "app" / "agent" / "prompts")
        if actual != cfg["prompt_sha256"]:
            raise BuildDemoError(f"the committed prompt's hash is {actual}, not the evaluation's frozen "
                                 f"{cfg['prompt_sha256']}")
        render = at.load_render()
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)

    b = bundle_mod.load(bundle_dir or bundle_mod.DEFAULT_BUNDLE)
    bundle_mod.self_test(b)
    library = store.load()
    streams = {e: Path((streams or {}).get(e) or repo_root / "app" / "replay" / name) for e, name in demo.EPISODES.items()}
    histories = {e: tools.load_history(streams[e], b) for e in demo.EPISODES}
    notified = {e: demo.notification_time(b, h.stream) for e, h in histories.items()}
    config = {"library_as_of": cfg["library_as_of"],
              "thresholds": {st: r["threshold"] for st, r in cfg["rules"].items()},
              "k": next(iter({r["k"] for r in cfg["rules"].values()})),
              "prompt_sha256": cfg["prompt_sha256"], "schema_version": ag.sc.SCHEMA_VERSION,
              "settings": llm.SETTINGS.as_dict(), "notes": demo.NOTES, "bundle": b.name,
              "episodes": {e: {"stream": demo.EPISODES[e], "notified_at": notified[e].strftime("%Y-%m-%dT%H:%M:%SZ")}
                           for e in demo.EPISODES}}
    if len({r["k"] for r in cfg["rules"].values()}) != 1:
        raise BuildDemoError("k differs between diagnosis times")

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_dir) as tmp:
        stage_cache = Path(tmp) / demo.CACHE
        if provider is None:
            from eval import gemini
            provider = gemini.GeminiClient(llm.SETTINGS)
        paid = at.paid_stack(provider, budget, float(min_interval), cache_dir=stage_cache)
        views, replayed = {}, {}
        for e in demo.EPISODES:
            views[e] = demo.build_views(b, library, histories[e], paid, render, config, notified_at=notified[e],
                                        episode=e, workdir=Path(tmp) / f"w1_{e}")
        for e in demo.EPISODES:
            replayed[e] = demo.build_views(b, library, histories[e], llm.ReplayClient(stage_cache), render, config,
                                           notified_at=notified[e], episode=e, workdir=Path(tmp) / f"w2_{e}")
        if replayed != views:
            raise BuildDemoError("the cache-only replay doesn't give the same views; nothing written")
        files = sorted(stage_cache.rglob("*.json")) if stage_cache.exists() else []
        for f in files:
            leak_scan.check(f.read_text(), f"cache file {f.name}")
        spent = sum(float(paid.inner.meter.ledger[k]["cost_inr"]) for k in paid.inner.meter.ledger)
        if stage_cache.exists():
            stage_cache.rename(out_dir / demo.CACHE)
        else:
            (out_dir / demo.CACHE).mkdir()                       # no call was needed (all screened or declined)
        (out_dir / demo.CONFIG).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")

    outputs = {"config": out_dir / demo.CONFIG}
    for f in sorted((out_dir / demo.CACHE).rglob("*.json")):
        outputs[f"cache_{f.stem[:12]}"] = f
    summary = {f"episode{e}_{n}_{st}": v["outcome"] for e, by_note in views.items()
               for n, by in by_note.items() for st, v in by.items()}
    record = run_record.write("build_demo",
                              config={"from_run": src_path.relative_to(repo_root.resolve()).as_posix(),
                                      "from_run_sha256": run_record.sha256(src_path), "billing_tier": billing_tier,
                                      "budget_inr": budget, "min_interval_s": float(min_interval), **config},
                              seeds={}, metrics={"calls": len(outputs) - 1, "spent_inr": round(spent, 5),
                                                 "outcomes": summary},
                              outputs=outputs, commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    out(f"demo built: {len(outputs) - 1} cached answers, Rs {spent:.4f}; outcomes {summary}\nrun record: {record}")
    return views, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from-run", type=Path, required=True, help="the complete evaluation agent_run")
    parser.add_argument("--billing-tier", choices=at.BILLING_TIERS, required=True)
    parser.add_argument("--budget", type=float, default=None)
    parser.add_argument("--min-interval", type=float, default=0.0)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(override=False)
    try:
        run(from_run=args.from_run, billing_tier=args.billing_tier, budget=args.budget,
            min_interval=args.min_interval, allow_dirty=args.allow_dirty)
    except (ValueError, FileExistsError, FileNotFoundError, BuildDemoError, demo.DemoError, llm.LLMError,
            leak_scan.LeakError, run_record.RunRecordError, bundle_mod.BundleError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())