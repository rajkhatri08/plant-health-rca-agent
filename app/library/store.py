"""The library store: load, cross-check, and what's in force as of a time (decisions 16, 67).

Runtime code: no imports from dataset/, eval/ or ingest/. Reads library/ only.

load() reads library/entries/<entry_id>/ and refuses the whole library on the first
problem (LibraryError naming the file), so a half-valid library is never served:
- file names: r<k>.yaml, r<k>.approval.yaml, r<k>.review-<account>.yaml, nothing else;
  the IDs inside must match the names, and revisions run 1..K with no gaps
- every tag, analyzer, group and loop exists in library/tags.yaml and library/loops.yaml,
  with signature tags from the 33 fast tags and analyzers from the analyzers
- accounts (library/accounts.yaml): the author has the author role, the approver the
  approver role and isn't the author's account, a reviewer the reviewer role; Claude may
  only review; an approval between two accounts of the same person can't claim
  independence; an approval comes at least 24 h after the revision's created_at
- related entries exist, and an action_id belongs to one entry only

Library.in_force(as_of): per entry, the highest revision whose approval exists at as_of
and whose effective_from is on or before as_of. A withdrawn one takes the entry out.
Drafts are never returned. An entry past review_due is flagged overdue, not dropped.

agent_view() is what retrieval may show the agent: no sources (decision 25, LEAKAGE),
with the revision reference (entry_id@r<k>), the overdue flag and the approval label.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.detector import loops as loops_mod
from app.library import schema

REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = REPO_ROOT / "library"
ENTRIES = LIBRARY / "entries"
ACCOUNTS = LIBRARY / "accounts.yaml"
REGISTER = LIBRARY / "tags.yaml"
LOOPS_FILE = LIBRARY / "loops.yaml"
ROLES = ("author", "approver", "reviewer")
CLAUDE = "claude"                               # the person Claude's accounts belong to
MIN_GAP = timedelta(hours=24)
SELF_APPROVED = "self-approved (single-person demo)"
INDEPENDENT = "independently approved"
_FILE = re.compile(r"^r(?P<k>[1-9]\d*)(?:\.(?P<kind>approval)|\.review-(?P<reviewer>[a-z][a-z0-9-]*))?\.yaml$")


class LibraryError(ValueError):
    pass


@dataclass(frozen=True)
class Account:
    id: str
    person: str
    roles: tuple


@dataclass(frozen=True)
class Stored:
    revision: schema.Revision
    approval: schema.Approval | None
    reviews: tuple

    @property
    def ref(self):
        return f"{self.revision.entry_id}@r{self.revision.revision}"


@dataclass(frozen=True)
class InForce:
    stored: Stored
    overdue: bool
    approval_label: str

    @property
    def ref(self):
        return self.stored.ref


def load_accounts(path=ACCOUNTS) -> dict:
    rows = yaml.safe_load(Path(path).read_text())["accounts"]
    accounts = {}
    for r in rows:
        a = Account(r["id"], r["person"], tuple(r["roles"]))
        if a.id in accounts:
            raise LibraryError(f"account {a.id} appears twice")
        if not a.roles or any(role not in ROLES for role in a.roles):
            raise LibraryError(f"account {a.id} has roles {a.roles}; allowed: {ROLES}")
        if a.person == CLAUDE and a.roles != ("reviewer",):
            raise LibraryError(f"account {a.id}: Claude may only review, never author or approve")
        accounts[a.id] = a
    return accounts


def approval_label(approval, author, accounts) -> str:
    same = accounts[approval.approver].person == accounts[author].person
    return SELF_APPROVED if same else INDEPENDENT


class Library:
    def __init__(self, entries, accounts):
        self.entries = entries                  # {entry_id: (Stored, ...) by revision}
        self.accounts = accounts

    def entry_ids(self):
        return tuple(self.entries)

    def get(self, entry_id, as_of):
        """The InForce revision of one entry as of as_of, or None."""
        if as_of.tzinfo is None:
            raise ValueError("as_of must be a timezone-aware time")
        live = [s for s in self.entries.get(entry_id, ())
                if s.approval is not None and s.approval.approved_at <= as_of
                and s.revision.governance.effective_from <= as_of]
        if not live:
            return None
        top = max(live, key=lambda s: s.revision.revision)
        if top.revision.withdrawn:
            return None
        return InForce(top, top.revision.governance.review_due < as_of,
                       approval_label(top.approval, top.revision.governance.author, self.accounts))

    def in_force(self, as_of) -> dict:
        """{entry_id: InForce} for every entry in force as of as_of."""
        out = {}
        for entry_id in self.entries:
            got = self.get(entry_id, as_of)
            if got is not None:
                out[entry_id] = got
        return out


def agent_view(item: InForce) -> dict:
    """What retrieval may show the agent: the revision without its sources, plus the
    reference, the overdue flag and the approval label."""
    view = item.stored.revision.model_dump(mode="json", exclude={"sources"})
    return {**view, "ref": item.ref, "overdue": item.overdue, "approval": item.approval_label}


# ---------- loading ----------

def _read(path, model):
    try:
        return model.model_validate(yaml.safe_load(path.read_text()))
    except ValidationError as e:
        raise LibraryError(f"{path}: {e.errors()[0]['msg']} at {e.errors()[0]['loc']}") from None
    except (yaml.YAMLError, AttributeError, TypeError) as e:
        raise LibraryError(f"{path}: not a valid YAML document ({e})") from None


def _register(register):
    rows = yaml.safe_load(Path(register).read_text())["tags"]
    kinds = {r["tag"]: r["kind"] for r in rows}
    return {"all": set(kinds),
            "fast": {t for t, k in kinds.items() if k in ("measurement", "valve")},
            "analyzers": {t for t, k in kinds.items() if k == "analyzer"},
            "groups": {r["group"] for r in rows}}


def _check_references(rev, reg, loop_ids, where):
    def need(items, allowed, what):
        bad = sorted(set(items) - allowed)
        if bad:
            raise LibraryError(f"{where}: {what} not known: {bad}")

    eq, sig = rev.equipment, rev.signature
    need([eq.group], reg["groups"], "equipment group")
    need(eq.tags, reg["all"], "equipment tags")
    need(list(eq.loops) + list(rev.links.loops), loop_ids, "loops")
    if sig.location.top_group:
        need(sig.location.top_group.one_of, reg["groups"], "location groups")
    if sig.location.top_tags:
        need(sig.location.top_tags.any_of, reg["fast"], "location tags (fast tags only)")
    for reading in (sig.provisional, sig.revised):
        need(reading.tags, reg["fast"], "signature tags (fast tags only)")
        need(reading.analyzers, reg["analyzers"], "signature analyzers")
        need(reading.loops, loop_ids, "signature loops")


def _check_people(stored, accounts, where):
    rev, appr = stored.revision, stored.approval
    author = rev.governance.author

    def role(account_id, needed):
        acc = accounts.get(account_id)
        if acc is None:
            raise LibraryError(f"{where}: account {account_id} isn't in accounts.yaml")
        if needed not in acc.roles:
            raise LibraryError(f"{where}: account {account_id} doesn't have the {needed} role")
        return acc

    role(author, "author")
    if appr is not None:
        role(appr.approver, "approver")
        if appr.approver == author:
            raise LibraryError(f"{where}: the author's account can't approve its own revision")
        if appr.independent and accounts[appr.approver].person == accounts[author].person:
            raise LibraryError(f"{where}: author and approver are the same person, so the approval "
                               "can't be independent")
        if appr.approved_at - rev.governance.created_at < MIN_GAP:
            raise LibraryError(f"{where}: approved less than 24 h after the revision was created")
    for r in stored.reviews:
        role(r.reviewer, "reviewer")
        if r.reviewer == author:
            raise LibraryError(f"{where}: the author can't review their own revision")


def _load_entry(folder):
    """{k: {"revision": path, "approval": path, "reviews": [paths]}} for one entry folder."""
    files = {}
    for path in sorted(folder.iterdir()):
        m = _FILE.match(path.name)
        if not path.is_file() or m is None:
            raise LibraryError(f"{path}: not a revision, approval or review file")
        slot = files.setdefault(int(m["k"]), {"revision": None, "approval": None, "reviews": []})
        if m["kind"] == "approval":
            slot["approval"] = path
        elif m["reviewer"]:
            slot["reviews"].append((m["reviewer"], path))
        else:
            slot["revision"] = path
    return files


def load(root=ENTRIES, accounts=ACCOUNTS, register=REGISTER, loops_file=LOOPS_FILE) -> Library:
    root = Path(root)
    if not root.is_dir():
        raise LibraryError(f"{root} isn't a folder")
    people = load_accounts(accounts)
    reg = _register(register)
    loop_ids = set(loops_mod.load(loops_file, register))
    entries, owner = {}, {}
    folders = sorted(p for p in root.iterdir() if p.name != ".gitkeep")
    for folder in folders:
        if not folder.is_dir() or not schema.SLUG.match(folder.name):
            raise LibraryError(f"{folder}: entries are folders named by entry_id")
        files = _load_entry(folder)
        if sorted(files) != list(range(1, len(files) + 1)):
            raise LibraryError(f"{folder}: revisions must run 1..K with no gaps, got {sorted(files)}")
        stored = []
        for k in sorted(files):
            slot = files[k]
            if slot["revision"] is None:
                raise LibraryError(f"{folder}: r{k} has an approval or review but no revision file")
            rev = _read(slot["revision"], schema.Revision)
            if (rev.entry_id, rev.revision) != (folder.name, k):
                raise LibraryError(f"{slot['revision']}: holds {rev.entry_id} r{rev.revision}")
            appr = _read(slot["approval"], schema.Approval) if slot["approval"] else None
            if appr and (appr.entry_id, appr.revision) != (folder.name, k):
                raise LibraryError(f"{slot['approval']}: approves {appr.entry_id} r{appr.revision}")
            reviews = []
            for name, path in slot["reviews"]:
                r = _read(path, schema.Review)
                if (r.entry_id, r.revision, r.reviewer) != (folder.name, k, name):
                    raise LibraryError(f"{path}: holds {r.entry_id} r{r.revision} by {r.reviewer}")
                reviews.append(r)
            s = Stored(rev, appr, tuple(reviews))
            _check_references(rev, reg, loop_ids, slot["revision"])
            _check_people(s, people, slot["revision"])
            for a in rev.actions:
                if owner.setdefault(a.action_id, folder.name) != folder.name:
                    raise LibraryError(f"{slot['revision']}: action_id {a.action_id} already belongs "
                                       f"to {owner[a.action_id]}")
            stored.append(s)
        entries[folder.name] = tuple(stored)
    for entry_id, revs in entries.items():
        for s in revs:
            missing = sorted(set(s.revision.links.related_entries) - set(entries))
            if missing:
                raise LibraryError(f"{s.ref}: related entries not in the library: {missing}")
    return Library(entries, people)