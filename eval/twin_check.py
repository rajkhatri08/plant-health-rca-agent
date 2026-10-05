"""Do the test twins share streams? (decision 57; PROTOCOL, Detection metrics; S0 answer 9)

    EVAL_MODE=1 python -m eval.twin_check          (Raj runs it; it opens sealed data)

For every testing-file fault 1-20 and every run k, compares samples 1-160 (the pre-fault
part) of faulty run k with normal testing run k, by exact equality of the stored float32
values on the 33 fast tags (metrics.first_divergence). Every file load is access-logged.

The verdict is all or nothing (Raj, S1 Q3): "shared" only if every run of every fault
matches its twin; otherwise "not shared", and the test detection table's "detected before
divergence" column reads "not reported". The per-fault counts are recorded either way.
The record holds counts only, never values or run numbers. Prints only counts.
"""

import argparse
import sys

from dataset import loader
from eval import metrics, run_record
from eval import split as split_mod
from ingest import tags as tagmap

NAME = "twin_check"


def run(*, repo_root=None, now=None, out=print):
    commit, dirty = run_record.check_clean(repo_root)
    sp = split_mod.get("test", NAME)
    normal = sp.load_normal()
    cols = tagmap.column_indices(normal.columns, tagmap.fast_tags())
    pre = sp.onset                                       # samples 1..160 are pre-fault
    twins = {k: a[:pre, cols] for k, a in normal.runs.items()}
    per_fault = {}
    for f in sp.faults:
        faulty = sp.load_faulty(f)
        if sorted(faulty.runs) != sorted(twins):
            raise ValueError(f"fault {f}'s test run numbers aren't the normal test run numbers")
        same = sum(metrics.first_divergence(a[:pre, cols], twins[k]) is None for k, a in faulty.runs.items())
        per_fault[str(f)] = {"runs": len(faulty.runs), "match": int(same)}
        out(f"fault {f}: {same} of {len(faulty.runs)} runs match their twin on samples 1-{pre}")
        del faulty
    shared = all(v["match"] == v["runs"] for v in per_fault.values())
    metrics_ = {"verdict": "shared" if shared else "not shared", "faults": per_fault}
    config = {"split": "test", "samples": [1, pre], "tags": "fast", "n_tags": len(cols),
              "comparison": "exact float32 equality", "rule": "all or nothing (S1 Q3)"}
    record = run_record.write(NAME, config=config, seeds={}, metrics=metrics_, outputs={},
                              commit=commit, dirty=dirty, repo_root=repo_root, now=now)
    out(f"verdict: {metrics_['verdict']}\nrun record: {record}")
    return metrics_, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.parse_args(argv)          # no --allow-dirty: the loader refuses a dirty tree anyway
    try:
        run()
    except (loader.LoaderError, run_record.RunRecordError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())