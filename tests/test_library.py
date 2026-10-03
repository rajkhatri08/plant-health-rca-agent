"""app/library: the entry schema and the store (decisions 16, 23, 67, 68).

Libraries here are built in tmp folders against the real tag register and loop map. The
example entry is synthetic: it tests the schema, not the plant.
"""

import copy
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.library import schema, store
from tests.test_leak_scan import find_leaks

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
ENTRY = "reactor-cooling-water-inlet-temperature-step"
OTHER = "condenser-cooling-water-inlet-temperature-step"


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def revision(entry_id=ENTRY, k=1, created=T0, **changes):
    doc = {
        "entry_id": entry_id, "revision": k, "event_type": "process", "family": "reactor cooling",
        "title": "Cooling water inlet temperature step at the reactor",
        "description": "Warmer cooling water reaches the reactor jacket; the temperature loop opens "
                       "the cooling water valve to hold reactor temperature.",
        "equipment": {"group": "reactor", "equipment_class": "unverified",
                      "tags": ["RX-TI-204", "RX-FV-206"], "loops": ["RX-TIC-204"]},
        "iso14224": {"failure_mode": "not_applicable", "failure_mechanism": "unverified",
                     "cause_category": "unverified", "detection_method": "unverified"},
        "signature": {
            "location": {"top_group": {"one_of": ["reactor"], "weight": "required"},
                         "top_tags": {"any_of": ["RX-FV-206"], "weight": "supporting"}},
            "provisional": {"tags": {"RX-FV-206": {"state": "high", "weight": "required"}},
                            "loops": {"RX-TIC-204": {"state": "compensating", "weight": "supporting"}},
                            "analyzers": {"RX-AI-211": {"state": "not_yet_available", "weight": "supporting"}},
                            "masked": {"state": True, "weight": "supporting"}},
            "revised": {"tags": {"RX-FV-206": {"state": "high", "weight": "required"}}}},
        "actions": [{"action_id": f"check-{entry_id}-supply", "kind": "check",
                     "text": "Ask the utilities operator for the cooling water supply temperature.",
                     "safety_preconditions": ["Readings only: no work on live equipment."],
                     "approval_required": True}],
        "links": {"loops": ["RX-TIC-204"]},
        "sources": ["src-001"],
        "governance": {"author": "raj", "created_at": iso(created), "effective_from": iso(created),
                       "review_due": iso(created + timedelta(days=180)),
                       "change_note": "First revision." if k == 1 else f"Revision {k}.",
                       "supersedes": None if k == 1 else k - 1},
    }
    for key, value in changes.items():
        doc[key] = value
    return doc


def approval(entry_id=ENTRY, k=1, at=T0 + timedelta(hours=25), approver="raj-review", independent=False,
             checks=schema.REQUIRED_CHECKS):
    return {"entry_id": entry_id, "revision": k, "approver": approver, "approved_at": iso(at),
            "checks": list(checks), "independent": independent}


def put(root, name, doc, entry_id=ENTRY):
    folder = root / entry_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(yaml.safe_dump(doc, sort_keys=False))


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "entries"
    r.mkdir()
    return r


@pytest.fixture
def accounts(tmp_path):
    path = tmp_path / "accounts.yaml"
    path.write_text(yaml.safe_dump({"accounts": [
        {"id": "raj", "person": "raj", "roles": ["author"]},
        {"id": "raj-review", "person": "raj", "roles": ["approver"]},
        {"id": "claude", "person": "claude", "roles": ["reviewer"]},
        {"id": "sam", "person": "sam", "roles": ["approver", "reviewer"]}]}))
    return path


def load(root, accounts):
    return store.load(root, accounts)


# ---------- schema: one file on its own ----------

def test_example_revision_is_valid():
    rev = schema.Revision.model_validate(yaml.safe_load(yaml.safe_dump(revision())))
    assert rev.entry_id == ENTRY and rev.signature.location.top_group.one_of == ("reactor",)


def test_vocabulary_is_decision_68():
    assert schema.TAG_STATES == ("high", "low", "both", "normal")
    assert schema.LOOP_STATES == ("held", "compensating", "lost", "saturated")
    assert schema.ANALYZER_STATES == ("high", "low", "normal", "not_yet_available")
    assert schema.EVENT_TYPES == ("data_quality", "instrument", "planned_activity", "process")
    assert schema.ACTION_KINDS == ("check", "confirm", "request_setpoint_change", "escalate")


def bad(**changes):
    doc = revision()
    for path, value in changes.items():
        node = doc
        *keys, last = path.split("__")
        for k in keys:
            node = node[int(k)] if isinstance(node, list) else node[k]
        node[last] = value
    return doc


@pytest.mark.parametrize("doc", [
    bad(entry_id="Reactor-Cooling"),                                   # not a slug
    bad(entry_id="fault-4-cooling"),                                   # a label, not a mechanism
    bad(entry_id="idv4"),
    bad(event_type="sensor"),
    bad(family="cooling"),
    bad(extra_field=1),                                                # unknown fields refused
    bad(iso14224__failure_mechanism="Leakage"),                        # a guessed code
    bad(iso14224__cause_category="not_applicable"),                    # N/A only for failure_mode
    bad(equipment__equipment_class="Heat exchanger"),
    bad(actions__0__safety_preconditions=[]),                          # every action needs one
    bad(actions__0__safety_preconditions=["  "]),
    bad(actions__0__approval_required=False),
    bad(actions__0__kind="write_setpoint"),                            # no action writes to controls
    bad(actions__0__action_id="Check Supply"),
    bad(signature__provisional__tags={"RX-FV-206": {"state": "up", "weight": "required"}}),
    bad(signature={"location": {}, "provisional": {"tags": {                       # nothing required
        "RX-FV-206": {"state": "high", "weight": "supporting"}}}, "revised": {}}),
    bad(signature={"location": {}, "provisional": {}, "revised": {"tags": {        # nothing at +30 min
        "RX-FV-206": {"state": "high", "weight": "required"}}}}),
    bad(governance__supersedes=1),                                     # r1 supersedes nothing
    bad(revision=2),                                                   # r2 must supersede r1
    bad(governance__created_at="2026-10-01"),                          # not a full UTC timestamp
    bad(governance__created_at="2026-10-01T09:00:00"),                 # no time zone
    bad(governance__effective_from=iso(T0 - timedelta(days=1))),       # before created_at
    bad(governance__review_due=iso(T0)),                               # not after effective_from
    bad(title=""),
    bad(links={"related_entries": [ENTRY]}),                           # links to itself
    bad(actions=[revision()["actions"][0]] * 2),                       # repeated action_id
    bad(sources=["src-yin-2012"]),                                     # not opaque: a title leaks
    bad(sources=["reference paper"]),
])
def test_invalid_revisions_are_refused(doc):
    with pytest.raises(ValidationError):
        schema.Revision.model_validate(yaml.safe_load(yaml.safe_dump(doc)))


@pytest.mark.parametrize("signature", [
    {"location": {"top_group": {"one_of": ["reactor"], "weight": "supporting"}},       # location only
     "revised": {"tags": {"RX-FV-206": {"state": "high", "weight": "required"}}}},
    {"provisional": {"masked": {"state": True, "weight": "supporting"}},             # provisional only
     "revised": {"tags": {"RX-FV-206": {"state": "high", "weight": "required"}}}},
])
def test_one_item_at_30_min_is_enough(signature):
    # decision 69: the +30 min diagnosis needs something in scope, wherever the required item is
    schema.Revision.model_validate(yaml.safe_load(yaml.safe_dump(revision(signature=signature))))


def test_not_applicable_is_allowed_for_failure_mode_only():
    assert schema.Revision.model_validate(revision()).iso14224.failure_mode == "not_applicable"


def test_approval_must_record_every_gate():
    for gate in schema.REQUIRED_CHECKS:
        doc = approval(checks=[c for c in schema.REQUIRED_CHECKS if c != gate])
        with pytest.raises(ValidationError, match=gate):
            schema.Approval.model_validate(yaml.safe_load(yaml.safe_dump(doc)))


# ---------- store: in force as of t ----------

def approved_entry(root, entry_id=ENTRY):
    put(root, "r1.yaml", revision(entry_id), entry_id)
    put(root, "r1.approval.yaml", approval(entry_id), entry_id)


def test_committed_library_loads():
    lib = store.load()
    assert all(s.revision.event_type == "process" for revs in lib.entries.values() for s in revs)
    assert store.load_accounts()["claude"].roles == ("reviewer",)


def test_empty_library(root, accounts):
    assert load(root, accounts).in_force(T0) == {}


def test_draft_is_invisible(root, accounts):
    put(root, "r1.yaml", revision())
    lib = load(root, accounts)
    assert lib.entry_ids() == (ENTRY,)
    assert lib.in_force(T0 + timedelta(days=30)) == {}


def test_in_force_from_approval_and_effective_time(root, accounts):
    approved_entry(root)
    lib = load(root, accounts)
    assert lib.get(ENTRY, T0 + timedelta(hours=24, minutes=59)) is None     # not approved yet
    got = lib.get(ENTRY, T0 + timedelta(hours=25))
    assert got.ref == f"{ENTRY}@r1" and not got.overdue
    assert got.approval_label == "self-approved (single-person demo)"


def test_effective_from_later_than_approval(root, accounts):
    put(root, "r1.yaml", revision(governance={**revision()["governance"],
                                               "effective_from": iso(T0 + timedelta(days=3))}))
    put(root, "r1.approval.yaml", approval())
    lib = load(root, accounts)
    assert lib.get(ENTRY, T0 + timedelta(days=2)) is None
    assert lib.get(ENTRY, T0 + timedelta(days=3)).ref == f"{ENTRY}@r1"


def test_a_new_revision_takes_over_only_from_its_approval(root, accounts):
    approved_entry(root)
    t2 = T0 + timedelta(days=10)
    put(root, "r2.yaml", revision(k=2, created=t2))
    lib = load(root, accounts)
    assert lib.get(ENTRY, t2 + timedelta(days=5)).ref == f"{ENTRY}@r1"      # r2 is a draft
    put(root, "r2.approval.yaml", approval(k=2, at=t2 + timedelta(hours=30)))
    lib = load(root, accounts)
    assert lib.get(ENTRY, t2 + timedelta(hours=29)).ref == f"{ENTRY}@r1"
    assert lib.get(ENTRY, t2 + timedelta(hours=30)).ref == f"{ENTRY}@r2"


def test_withdrawn_revision_takes_the_entry_out(root, accounts):
    approved_entry(root)
    t2 = T0 + timedelta(days=10)
    put(root, "r2.yaml", revision(k=2, created=t2, withdrawn=True))
    put(root, "r2.approval.yaml", approval(k=2, at=t2 + timedelta(hours=24)))
    lib = load(root, accounts)
    assert lib.get(ENTRY, t2).ref == f"{ENTRY}@r1"
    assert lib.get(ENTRY, t2 + timedelta(hours=24)) is None


def test_overdue_is_flagged_not_dropped(root, accounts):
    approved_entry(root)
    got = load(root, accounts).get(ENTRY, T0 + timedelta(days=181))
    assert got is not None and got.overdue


def test_as_of_must_be_time_zone_aware(root, accounts):
    approved_entry(root)
    with pytest.raises(ValueError):
        load(root, accounts).get(ENTRY, datetime(2026, 12, 1))


def test_independent_approval_by_another_person(root, accounts):
    put(root, "r1.yaml", revision())
    put(root, "r1.approval.yaml", approval(approver="sam", independent=True))
    assert load(root, accounts).get(ENTRY, T0 + timedelta(days=2)).approval_label == "independently approved"


def test_agent_view_strips_sources(root, accounts):
    approved_entry(root)
    view = store.agent_view(load(root, accounts).get(ENTRY, T0 + timedelta(days=2)))
    assert "sources" not in view and "provenance" not in view
    assert view["ref"] == f"{ENTRY}@r1" and view["approval"] == "self-approved (single-person demo)"
    assert view["overdue"] is False and view["signature"]["location"]["top_group"]["one_of"] == ["reactor"]


# ---------- store: governance refusals ----------

@pytest.mark.parametrize("appr, match", [
    (approval(approver="raj"), "role"),                                # the author's account
    (approval(approver="claude"), "role"),                             # Claude only reviews
    (approval(approver="nobody"), "isn't in accounts"),
    (approval(independent=True), "same person"),                       # can't overstate independence
    (approval(at=T0 + timedelta(hours=23, minutes=59)), "24 h"),       # the cooling-off gap
])
def test_approval_refusals(root, accounts, appr, match):
    put(root, "r1.yaml", revision())
    put(root, "r1.approval.yaml", appr)
    with pytest.raises(store.LibraryError, match=match):
        load(root, accounts)


def test_author_needs_the_author_role(root, accounts):
    doc = revision()
    doc["governance"]["author"] = "claude"
    put(root, "r1.yaml", doc)
    with pytest.raises(store.LibraryError, match="author role"):
        load(root, accounts)


def test_review_by_claude_is_allowed_and_kept(root, accounts):
    approved_entry(root)
    put(root, "r1.review-claude.yaml", {"entry_id": ENTRY, "revision": 1, "reviewer": "claude",
                                        "reviewed_at": iso(T0 + timedelta(hours=2)),
                                        "note": "Schema, leak scan and provenance checked."})
    (s,) = load(root, accounts).entries[ENTRY]
    assert [r.reviewer for r in s.reviews] == ["claude"]


@pytest.mark.parametrize("rows, match", [
    ([{"id": "claude", "person": "claude", "roles": ["approver"]}], "Claude may only review"),
    ([{"id": "claude", "person": "claude", "roles": ["reviewer", "author"]}], "Claude may only review"),
    ([{"id": "a", "person": "a", "roles": ["boss"]}], "roles"),
    ([{"id": "a", "person": "a", "roles": ["author"]}] * 2, "twice"),
])
def test_bad_accounts_are_refused(tmp_path, rows, match):
    path = tmp_path / "accounts.yaml"
    path.write_text(yaml.safe_dump({"accounts": rows}))
    with pytest.raises(store.LibraryError, match=match):
        store.load_accounts(path)


def test_committed_accounts_are_option_1():
    acc = store.load_accounts()
    assert acc["raj"].roles == ("author",) and acc["raj-review"].roles == ("approver",)
    assert acc["raj"].person == acc["raj-review"].person


# ---------- store: files and references ----------

def test_file_layout_refusals(root, accounts):
    cases = [
        (lambda r: put(r, "r1.yaml", revision(OTHER)), "holds"),                  # wrong entry inside
        (lambda r: (put(r, "r1.yaml", revision()), put(r, "r3.yaml", revision(k=3))), "no gaps"),
        (lambda r: put(r, "r1.approval.yaml", approval()), "no revision file"),
        (lambda r: (put(r, "r1.yaml", revision()), put(r, "notes.txt", {})), "not a revision"),
        (lambda r: (put(r, "r1.yaml", revision()),
                    put(r, "r1.review-sam.yaml", {"entry_id": ENTRY, "revision": 1, "reviewer": "claude",
                                                  "reviewed_at": iso(T0), "note": "x"})), "by claude"),
    ]
    for make, match in cases:
        for p in sorted(root.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        make(root)
        with pytest.raises(store.LibraryError, match=match):
            load(root, accounts)


@pytest.mark.parametrize("edit, match", [
    (lambda d: d["signature"]["provisional"]["tags"].update({"XX-TI-999": {"state": "high", "weight": "supporting"}}),
     "signature tags"),
    (lambda d: d["signature"]["provisional"]["tags"].update({"RX-AI-211": {"state": "high", "weight": "supporting"}}),
     "fast tags only"),                                                     # an analyzer under tags
    (lambda d: d["signature"]["provisional"]["analyzers"].update({"RX-TI-204": {"state": "high", "weight": "supporting"}}),
     "analyzers"),                                                          # a fast tag under analyzers
    (lambda d: d["signature"]["revised"].update({"loops": {"RX-TIC-999": {"state": "held", "weight": "supporting"}}}),
     "loops"),
    (lambda d: d["signature"]["location"]["top_group"].update({"one_of": ["boiler"]}), "location groups"),
    (lambda d: d["equipment"].update({"group": "boiler"}), "equipment group"),
    (lambda d: d["links"].update({"loops": ["XX-FIC-1"]}), "loops"),
    (lambda d: d["links"].update({"related_entries": [OTHER]}), "related entries"),
])
def test_reference_refusals(root, accounts, edit, match):
    doc = copy.deepcopy(revision())
    edit(doc)
    put(root, "r1.yaml", doc)
    with pytest.raises(store.LibraryError, match=match):
        load(root, accounts)


def test_action_id_belongs_to_one_entry(root, accounts):
    approved_entry(root)
    other = revision(OTHER)
    other["actions"][0]["action_id"] = f"check-{ENTRY}-supply"
    put(root, "r1.yaml", other, OTHER)
    with pytest.raises(store.LibraryError, match="already belongs"):
        load(root, accounts)


def test_related_entries_resolve(root, accounts):
    approved_entry(root)
    put(root, "r1.yaml", revision(OTHER, links={"related_entries": [ENTRY], "loops": []}), OTHER)
    assert set(load(root, accounts).entry_ids()) == {ENTRY, OTHER}


# ---------- the committed library ----------

def test_committed_files_pass_the_leak_scan():
    for p in (REPO / "library").rglob("*.yaml"):
        assert find_leaks(p.read_text()) == [], p


def test_committed_revision_files_are_never_edited():
    # Decision 67: every file under library/entries/ is written once. In git, each one has
    # exactly one commit that touched it. --no-renames, not --follow: approval files are
    # near-identical across entries, and --follow took a new one for a copy of another
    # entry's and counted that file's history too (found in week 5 S6).
    entries = REPO / "library" / "entries"
    files = [p for p in entries.rglob("*.yaml")]
    try:
        for p in files:
            commits = commits_touching(REPO, p.relative_to(REPO))
            assert len(commits) <= 1, f"{p.relative_to(REPO)} was edited after it was committed"
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git history not available")


def commits_touching(repo, rel):
    log = subprocess.run(["git", "-C", str(repo), "log", "--format=%H", "--no-renames", "--", str(rel)],
                         capture_output=True, text=True, check=True)
    return log.stdout.split()


def test_commit_count_sees_edits_but_not_look_alike_files(git_repo):
    # the case that tripped --follow: a new file nearly identical to another one
    def git(*args):
        subprocess.run(["git", "-C", str(git_repo), *args], check=True, capture_output=True)
    a, b = git_repo / "a.yaml", git_repo / "b.yaml"
    a.write_text(yaml.safe_dump(approval(ENTRY)))
    git("add", "-A"); git("commit", "-q", "-m", "a")
    b.write_text(yaml.safe_dump(approval(OTHER)))
    git("add", "-A"); git("commit", "-q", "-m", "b")
    assert len(commits_touching(git_repo, "b.yaml")) == 1            # a look-alike isn't an edit
    a.write_text(yaml.safe_dump(approval(ENTRY, approver="sam")))
    git("add", "-A"); git("commit", "-q", "-m", "edit a")
    assert len(commits_touching(git_repo, "a.yaml")) == 2            # a real edit is caught

# ---------- decision 68 amendment: one_of for tags and analyzers ----------

def with_tags(tags, analyzers=None):
    doc = revision()
    doc["signature"]["provisional"]["tags"] = tags
    if analyzers is not None:
        doc["signature"]["provisional"]["analyzers"] = analyzers
    return yaml.safe_load(yaml.safe_dump(doc))


def test_one_of_lists_several_acceptable_states():
    rev = schema.Revision.model_validate(with_tags(
        {"RX-PI-202": {"one_of": ["high", "low"], "weight": "required"},
         "RX-FV-206": {"state": "high", "weight": "supporting"}},
        {"RX-AI-211": {"one_of": ["high", "not_yet_available"], "weight": "supporting"}}))
    p = rev.signature.provisional
    assert p.tags["RX-PI-202"].accepted() == ("high", "low")
    assert p.tags["RX-FV-206"].accepted() == ("high",)
    assert p.analyzers["RX-AI-211"].accepted() == ("high", "not_yet_available")


@pytest.mark.parametrize("expect", [
    {"weight": "required"},                                            # neither
    {"state": "high", "one_of": ["high", "low"], "weight": "required"},  # both
    {"one_of": ["high"], "weight": "required"},                        # one_of needs two
    {"one_of": ["high", "high"], "weight": "required"},                # repeated
    {"one_of": ["high", "up"], "weight": "required"},                  # not in the vocabulary
    {"one_of": ["high", "not_yet_available"], "weight": "required"},   # an analyzer state on a tag
])
def test_bad_tag_expectations_are_refused(expect):
    with pytest.raises(ValidationError):
        schema.Revision.model_validate(with_tags({"RX-PI-202": expect}))


def test_loops_keep_a_single_state():
    doc = revision()
    doc["signature"]["provisional"]["loops"] = {"RX-TIC-204": {"one_of": ["held", "lost"],
                                                               "weight": "supporting"}}
    with pytest.raises(ValidationError):
        schema.Revision.model_validate(yaml.safe_load(yaml.safe_dump(doc)))


def test_a_one_of_entry_loads_in_the_store(root, accounts):
    put(root, "r1.yaml", with_tags({"RX-PI-202": {"one_of": ["high", "low"], "weight": "required"}}))
    put(root, "r1.approval.yaml", approval())
    got = load(root, accounts).get(ENTRY, T0 + timedelta(days=2))
    assert got.stored.revision.signature.provisional.tags["RX-PI-202"].one_of == ("high", "low")
