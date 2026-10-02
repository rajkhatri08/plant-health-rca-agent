"""Entry tests (decisions 24, 67, 71): what a library revision must pass before it can be
approved. Builder side: it reads the provenance files, which carry labels and run numbers.

    python -m eval.entry_tests <entry_id> <revision> [--allow-dirty]

Authoring runs only, never dev: the cases are the detected runs in each entry's
provenance file (eval/entry_provenance.yaml), which must be an output of a committed
authoring run record, as the approval gate requires. Nothing is loaded from data/.

The library under test is every revision in force now, with the subject (usually a
draft) in place of its own entry's revision. Other drafts are left out. At both
diagnosis times (provisional, revised), through app/diagnosis/matcher.py:
- self          on each of the subject's own detected runs: no required contradiction,
                and first or tied for first
- specificity   on every other entry's detected runs: the subject never ranks strictly
                above that run's own entry
- regression    every other entry in the library passes its own self and specificity
                tests on this larger library (decision 71: a failure revises the new entry)
An entry whose provenance has no detected run fails its self test.

Writes eval/runs/<stamp>_entry_tests.json with config.entry = entry_id@r<k>, the library
it ran against (each revision's reference and file SHA-256, each provenance file and its
SHA-256), and metrics.passed, the shape eval/approve_entry.py's entry_tests gate reads.
Prints each failure. Refuses a dirty tree unless --allow-dirty, before reading anything
(a dirty record never satisfies the gate). Never writes under library/.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.diagnosis import matcher
from app.library import store
from eval import approve_entry as ap
from eval import run_record

TIMES = tuple(matcher.SCOPES)              # ("provisional", "revised")


class EntryTestError(RuntimeError):
    pass


def library_under_test(lib, entry_id, k, as_of) -> dict:
    """{entry_id: schema.Revision}: the revisions in force as of as_of, with the subject
    entry_id r<k> in place of its entry's."""
    stored = {s.revision.revision: s for s in lib.entries.get(entry_id, ())}.get(k)
    if stored is None:
        raise EntryTestError(f"{entry_id} r{k} isn't in the library")
    revs = {e: inf.stored.revision for e, inf in lib.in_force(as_of).items()}
    revs[entry_id] = stored.revision
    return dict(sorted(revs.items()))


def load_cases(entry_ids, repo_root) -> tuple:
    """({entry_id: [(run, features), ...] over the detected runs}, {entry_id: provenance
    path}). Every entry needs a provenance file in the entry key that a committed
    authoring record wrote."""
    repo_root = Path(repo_root)
    key = ap.load_entry_key(repo_root / ap.KEY) if (repo_root / ap.KEY).is_file() else {}
    cases, files = {}, {}
    for e in entry_ids:
        if e not in key:
            raise EntryTestError(f"{e} has no provenance file in {ap.KEY}")
        path = repo_root / key[e]
        if not path.is_file():
            raise EntryTestError(f"{key[e]} (for {e}) doesn't exist")
        record, _ = ap.authoring_record_for(path, repo_root)
        if record is None:
            raise EntryTestError(f"{key[e]} (for {e}) isn't an output of a committed authoring run record")
        doc = yaml.safe_load(path.read_text())
        cases[e] = [(r["run"], r["features"]) for r in doc["per_run"] if r["detected"]]
        files[e] = path
    return cases, files


def _position(ranking, entry_id):
    """The index of the tied block holding entry_id."""
    return next(i for i, block in enumerate(ranking) if any(s.entry_id == entry_id for s in block))


def rankings(revs, cases) -> dict:
    """{(owner, run, at): ranking} for every detected run of every entry, at both times."""
    out = {}
    for owner, runs in cases.items():
        for run, f in runs:
            for at in TIMES:
                out[(owner, run, at)] = matcher.rank([matcher.score(r, f, at) for r in revs.values()])
    return out


def self_failures(entry_id, cases, ranked) -> list:
    if not cases[entry_id]:
        return [f"{entry_id}: no detected authoring run to test on"]
    out = []
    for (owner, run, at), ranking in ranked.items():
        if owner != entry_id:
            continue
        mine = next(s for block in ranking for s in block if s.entry_id == entry_id)
        if mine.required_contradictions:
            out.append(f"{entry_id}: {mine.required_contradictions} required contradiction(s) "
                       f"on its own run {run} at {at}")
        elif _position(ranking, entry_id) != 0:
            top = ", ".join(s.ref for s in ranking[0])
            out.append(f"{entry_id}: not first on its own run {run} at {at} (first: {top})")
    return out


def specificity_failures(entry_id, ranked) -> list:
    out = []
    for (owner, run, at), ranking in ranked.items():
        if owner != entry_id and _position(ranking, entry_id) < _position(ranking, owner):
            out.append(f"{entry_id}: ranks above {owner} on {owner}'s run {run} at {at}")
    return out


def evaluate(entry_id, revs, cases) -> dict:
    """{"self": [...], "specificity": [...], "regression": {other: [...]}}: failure messages."""
    ranked = rankings(revs, cases)
    return {"self": self_failures(entry_id, cases, ranked),
            "specificity": specificity_failures(entry_id, ranked),
            "regression": {e: self_failures(e, cases, ranked) + specificity_failures(e, ranked)
                           for e in revs if e != entry_id}}


def run(entry_id, k, *, repo_root=None, allow_dirty=False, now=None):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    commit, dirty = run_record.check_clean(repo_root, allow_dirty)    # before reading anything
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    if now.tzinfo is None:
        raise EntryTestError("now must be a timezone-aware time")
    paths = ap.library_paths(repo_root)
    lib = store.load(**paths)
    revs = library_under_test(lib, entry_id, k, now)
    cases, files = load_cases(revs, repo_root)
    result = evaluate(entry_id, revs, cases)
    regression = [m for msgs in result["regression"].values() for m in msgs]
    passed = not (result["self"] or result["specificity"] or regression)

    ref = f"{entry_id}@r{k}"
    rel = lambda p: Path(p).relative_to(repo_root).as_posix()     # noqa: E731
    record = run_record.write(
        "entry_tests",
        config={"entry": ref, "as_of": now.strftime(ap.TS),
                "library": {e: f"{e}@r{r.revision}" for e, r in revs.items()},
                "revision_sha256": {e: run_record.sha256(paths["root"] / e / f"r{r.revision}.yaml")
                                    for e, r in revs.items()},
                "provenance": {e: rel(p) for e, p in files.items()},
                "provenance_sha256": {e: run_record.sha256(p) for e, p in files.items()}},
        seeds={},
        metrics={"passed": passed, "entries": len(revs),
                 "runs": {e: len(c) for e, c in cases.items()},
                 "self_failures": len(result["self"]),
                 "specificity_failures": len(result["specificity"]),
                 "regression_failures": len(regression)},
        outputs={}, commit=commit, dirty=dirty, repo_root=repo_root, now=now)

    for name in ("self", "specificity"):
        print(f"{name:12s} {'FAIL' if result[name] else 'pass'}" +
              "".join(f"\n             - {m}" for m in result[name]))
    print(f"{'regression':12s} {'FAIL' if regression else 'pass'} ({len(revs) - 1} other entries)" +
          "".join(f"\n             - {m}" for m in regression))
    print(f"{ref}: {'passed' if passed else 'failed'}; run record: {record}")
    return passed, record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("entry_id")
    parser.add_argument("revision", type=int)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run on a dirty tree; the record says dirty: true and can't approve")
    args = parser.parse_args(argv)
    try:
        passed, _ = run(args.entry_id, args.revision, allow_dirty=args.allow_dirty)
    except (ValueError, FileNotFoundError, run_record.RunRecordError, ap.ApprovalError,
            EntryTestError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())