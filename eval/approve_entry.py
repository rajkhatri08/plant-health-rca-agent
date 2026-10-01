"""The gated approval of one library revision (decisions 16, 24, 67). Builder side.

    python -m eval.approve_entry <entry_id> <revision> --approver raj-review
    python -m eval.approve_entry <entry_id> <revision> --check [--approver raj-review]

Approval happens only here, never by editing YAML and never through chat. It writes
library/entries/<entry_id>/r<k>.approval.yaml, and only when all six gates pass:

1. schema        the whole library loads (app/library/store.py: the schema, references,
                 accounts), and every source the revision cites is in eval/sources.yaml
2. leak_scan     the revision file has no benchmark or source names, raw names or labels
                 (eval/leak_scan.py, the CI patterns)
3. provenance    eval/entry_provenance.yaml maps the entry to its provenance file; that file
                 is an output of a committed authoring run record; its family is the
                 entry's; and the signature agrees with the detected authoring runs: each
                 required item on every one (REQUIRED_AGREEMENT), each supporting item on
                 at least SUPPORTING_AGREEMENT of them
4. preconditions every action has at least one safety precondition and needs approval
5. entry_tests   a clean entry_tests run record for this entry@revision says passed. The
                 entry-test runner comes with the matcher (week 5); until then this gate
                 refuses
6. gap_24h       at least 24 h between the revision's created_at and now

The approver must have the approver role and not be the author's account. "independent"
is set from the accounts: false when author and approver are the same person (shown as
"self-approved (single-person demo)"), true only for a different person (decision 67's
upgrade path). It isn't an option.

Refuses a dirty tree (the revision must be committed as it is), an existing approval file
(never overwritten), and an unknown entry or revision. It reports every failing gate at
once and writes nothing then. After writing, it loads the library again and removes the
file if the store refuses it.

--check evaluates and reports the same six gates (and the approver, if given) on any tree,
dirty or not, and never writes anything. It's for checking a draft before committing it,
since a committed revision can never be edited. It exits 0 only when every gate passes.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.library import schema, store
from eval import leak_scan, run_record

KEY = Path("eval") / "entry_provenance.yaml"
SOURCES = Path("eval") / "sources.yaml"
REQUIRED_AGREEMENT = 1.0          # a required item agrees on every detected authoring run
SUPPORTING_AGREEMENT = 0.5        # a supporting item on at least half of them
TS = "%Y-%m-%dT%H:%M:%SZ"


class ApprovalError(RuntimeError):
    pass


def library_paths(repo_root):
    lib = Path(repo_root) / "library"
    return {"root": lib / "entries", "accounts": lib / "accounts.yaml",
            "register": lib / "tags.yaml", "loops_file": lib / "loops.yaml"}


def load_sources(path) -> set:
    rows = yaml.safe_load(Path(path).read_text())["sources"]
    ids = [r["id"] for r in rows]
    bad = [i for i in ids if not schema.SOURCE_ID.match(i)]
    if bad or len(set(ids)) != len(ids):
        raise ApprovalError(f"{path}: source IDs must be unique src-NNN, got {bad or 'a repeat'}")
    return set(ids)


def load_entry_key(path) -> dict:
    """{entry_id: provenance file path, relative to the repo}."""
    doc = yaml.safe_load(Path(path).read_text()) or {}
    entries = doc.get("entries") or {}
    files = list(entries.values())
    if len(set(files)) != len(files):
        raise ApprovalError(f"{path}: one provenance file serves two entries")
    for entry_id in entries:
        if not schema.SLUG.match(entry_id):
            raise ApprovalError(f"{path}: {entry_id!r} isn't an entry_id")
    return dict(entries)


def authoring_record_for(path, repo_root):
    sha = run_record.sha256(path)
    for p in sorted((Path(repo_root) / run_record.RUNS_DIR).glob("*_authoring.json")):
        rec = json.loads(p.read_text())
        if any(o.get("sha256") == sha for o in rec.get("outputs", {}).values()):
            return p, rec
    return None, None


# ---------- does the signature agree with the authoring runs? ----------

def _items(rev):
    """(name, weight, test) for every listed item; test(features of one run) -> bool."""
    sig = rev.signature
    if sig.location.top_group:
        e = sig.location.top_group
        yield "location.top_group", e.weight, lambda f, e=e: f["location"]["top_group"] in e.one_of
    if sig.location.top_tags:
        e = sig.location.top_tags
        yield "location.top_tags", e.weight, lambda f, e=e: bool(set(e.any_of) & set(f["location"]["top_tags"]))
    for name in ("provisional", "revised"):
        r = getattr(sig, name)
        for kind in ("tags", "loops", "analyzers"):
            for key, e in getattr(r, kind).items():
                yield (f"{name}.{kind}.{key}", e.weight,
                       lambda f, n=name, k=kind, key=key, e=e: n in f and f[n][k][key] in e.accepted())
        if r.masked:
            yield f"{name}.masked", r.masked.weight, lambda f, n=name, e=r.masked: n in f and f[n]["masked"] == e.state


def agreement(rev, provenance) -> list:
    """[{item, weight, agreed, of}] over the provenance's detected runs."""
    runs = [r["features"] for r in provenance["per_run"] if r["detected"]]
    return [{"item": name, "weight": weight, "agreed": sum(test(f) for f in runs), "of": len(runs)}
            for name, weight, test in _items(rev)]


def disagreements(rev, provenance) -> list:
    out = []
    for a in agreement(rev, provenance):
        need = REQUIRED_AGREEMENT if a["weight"] == "required" else SUPPORTING_AGREEMENT
        if a["of"] == 0 or a["agreed"] / a["of"] < need:
            out.append(f"{a['item']} ({a['weight']}) agrees on {a['agreed']} of {a['of']} detected runs")
    return out


# ---------- the gates ----------

def gates(entry_id, k, repo_root, now):
    """({gate: [problems]}, the Stored revision or None, accounts or None)."""
    repo_root = Path(repo_root)
    problems = {g: [] for g in schema.REQUIRED_CHECKS}
    try:
        lib = store.load(**library_paths(repo_root))
    except store.LibraryError as e:
        problems["schema"].append(str(e))
        return problems, None, None
    stored = {s.revision.revision: s for s in lib.entries.get(entry_id, ())}.get(k)
    if stored is None:
        raise ApprovalError(f"{entry_id} r{k} isn't in the library")
    rev = stored.revision
    rev_path = library_paths(repo_root)["root"] / entry_id / f"r{k}.yaml"

    unknown = sorted(set(rev.sources) - load_sources(repo_root / SOURCES))
    if unknown:
        problems["schema"].append(f"sources not in {SOURCES}: {unknown}")

    leaks = leak_scan.find_leaks(rev_path.read_text())
    if leaks:
        problems["leak_scan"].append(f"{rev_path.name} contains {sorted(set(leaks))}")

    key = load_entry_key(repo_root / KEY) if (repo_root / KEY).is_file() else {}
    if entry_id not in key:
        problems["provenance"].append(f"{entry_id} has no provenance file in {KEY}")
    else:
        prov_path = repo_root / key[entry_id]
        record, _ = authoring_record_for(prov_path, repo_root) if prov_path.is_file() else (None, None)
        if record is None:
            problems["provenance"].append(f"{key[entry_id]} isn't an output of a committed authoring run record")
        else:
            prov = yaml.safe_load(prov_path.read_text())
            if prov["family"] != rev.family:
                problems["provenance"].append(f"the provenance is for {prov['family']}, the entry for {rev.family}")
            problems["provenance"] += disagreements(rev, prov)

    for a in rev.actions:
        if not a.safety_preconditions or any(not p.strip() for p in a.safety_preconditions) \
                or a.approval_required is not True:
            problems["preconditions"].append(f"action {a.action_id} lacks a precondition or approval")

    ref = f"{entry_id}@r{k}"
    passed = False
    for p in sorted((repo_root / run_record.RUNS_DIR).glob("*_entry_tests.json")):
        rec = json.loads(p.read_text())
        if rec.get("config", {}).get("entry") == ref and rec.get("dirty") is False:
            passed = rec.get("metrics", {}).get("passed") is True
    if not passed:
        problems["entry_tests"].append(f"no clean entry_tests run record says {ref} passed "
                                       "(the entry-test runner comes with the matcher, week 5)")

    if now - rev.governance.created_at < store.MIN_GAP:
        problems["gap_24h"].append(f"only {now - rev.governance.created_at} since created_at "
                                   f"{rev.governance.created_at:%Y-%m-%dT%H:%M:%SZ}")
    return problems, stored, lib.accounts


def _now(now):
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    if now.tzinfo is None:
        raise ApprovalError("now must be a timezone-aware time")
    return now


def approver_problem(stored, accounts, approver):
    """Why this account can't approve this revision, or None."""
    acc = accounts.get(approver)
    if acc is None or "approver" not in acc.roles:
        return f"account {approver} doesn't have the approver role"
    if approver == stored.revision.governance.author:
        return "the author's account can't approve its own revision"
    return None


def report(failed):
    for g in schema.REQUIRED_CHECKS:
        print(f"{g:14s} {'FAIL' if g in failed else 'pass'}" +
              "".join(f"\n               - {p}" for p in failed.get(g, [])))


def check(entry_id, revision, approver=None, *, repo_root=None, now=None) -> dict:
    """--check: {gate: [problems]} for the gates that fail (plus "approver" when an
    approver is given and can't approve). Works on a dirty tree; writes nothing."""
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    now = _now(now)
    problems, stored, accounts = gates(entry_id, revision, repo_root, now)
    failed = {g: p for g, p in problems.items() if p}
    report(failed)
    if stored is not None and approver is not None:
        why = approver_problem(stored, accounts, approver)
        print(f"{'approver':14s} {'FAIL' if why else 'pass'} ({approver})" + (f"\n               - {why}" if why else ""))
        if why:
            failed["approver"] = [why]
    if stored is not None:
        ready = stored.revision.governance.created_at + store.MIN_GAP
        print(f"approvable by the 24 h gap from {ready:%Y-%m-%dT%H:%M:%SZ}")
    print("check only: nothing written; " + ("every gate passes" if not failed
                                              else f"failing: {', '.join(failed)}"))
    return failed


def run(entry_id, revision, approver, *, repo_root=None, now=None):
    repo_root = Path(repo_root or run_record.REPO_ROOT)
    now = _now(now)
    run_record.check_clean(repo_root, allow_dirty=False)     # the revision is committed as it is
    out = library_paths(repo_root)["root"] / entry_id / f"r{revision}.approval.yaml"
    if out.exists():
        raise FileExistsError(f"{out} exists; an approval is never overwritten")

    problems, stored, accounts = gates(entry_id, revision, repo_root, now)
    if stored is not None:
        author = stored.revision.governance.author
        why = approver_problem(stored, accounts, approver)
        if why:
            raise ApprovalError(why)
    failed = {g: p for g, p in problems.items() if p}
    report(failed)
    if failed:
        raise ApprovalError(f"not approved: {', '.join(failed)} failed; nothing written")

    independent = accounts[approver].person != accounts[author].person
    doc = {"entry_id": entry_id, "revision": revision, "approver": approver,
           "approved_at": now.strftime(TS), "checks": list(schema.REQUIRED_CHECKS),
           "independent": independent}
    with open(out, "x") as f:
        yaml.safe_dump(doc, f, sort_keys=False)
    try:
        lib = store.load(**library_paths(repo_root))
    except store.LibraryError:
        out.unlink()
        raise
    label = store.approval_label(lib.entries[entry_id][revision - 1].approval, author, accounts)
    print(f"approved {entry_id}@r{revision} by {approver} at {doc['approved_at']} ({label})")
    print(f"wrote {out}; commit it")
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("entry_id")
    parser.add_argument("revision", type=int)
    parser.add_argument("--approver", default=None)
    parser.add_argument("--check", action="store_true",
                        help="evaluate and report the gates on any tree; write nothing")
    args = parser.parse_args(argv)
    if not args.check and args.approver is None:
        parser.error("--approver is required unless --check")
    try:
        if args.check:
            return 1 if check(args.entry_id, args.revision, args.approver) else 0
        run(args.entry_id, args.revision, args.approver)
    except (ValueError, FileExistsError, FileNotFoundError, run_record.RunRecordError,
            ApprovalError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())