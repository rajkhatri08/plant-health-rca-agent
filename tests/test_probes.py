"""eval/probes.py and eval/probes/probes.yaml (LEAKAGE wall 2): the PROPOSED probes. Fakes only."""

import json

import pytest
import yaml

from app.agent import llm
from eval import probes as pr
from shared.leak_scan import find_leaks
from tests.test_approve_entry import commit

from pathlib import Path
REPO = Path(__file__).resolve().parents[1]     # the conftest points run_record's root nowhere


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(pr.PROBES.read_text())


def test_every_rendered_probe_is_clean_and_holds_its_material(doc):
    ps = pr.prompts(doc, REPO)
    assert [p for p, _ in ps] == [x["id"] for x in doc["probes"]]
    for pid, text in ps:
        assert find_leaks(text) == [], pid
    texts = dict(ps)
    assert "RX-PI-202" in texts["tags"] and "CP-FIC-501" in texts["loops"]
    assert "drift" in texts["entry-drift"].lower()


def test_a_probe_that_would_leak_is_refused(doc, tmp_path):
    bad = {**doc, "question_plant": doc["question_plant"] + " Is it the Tennessee plant?"}
    with pytest.raises(pr.leak_scan.LeakError):
        pr.prompts(bad, REPO)


@pytest.mark.parametrize("raw, parsed, recognised", [
    ('{"recognised": false}', {"recognised": False, "number": None}, False),
    ('{"recognised": true, "name": "the Tennessee Eastman process"}', {"recognised": True, "number": None}, True),
    ('{"recognised": true, "name": "IDV(13)"}', {"recognised": True, "number": None}, True),
    ('{"recognised": true, "number": 6}', {"recognised": True, "number": 6}, True),
    ('{"recognised": true, "name": "a reactor"}', {"recognised": True, "number": None}, False),   # claims, names nothing
])
def test_verdict(raw, parsed, recognised):
    v = pr.verdict(raw, parsed)
    assert v["recognised"] is recognised and v["model_says"] is parsed["recognised"]


def test_the_dry_run_writes_nothing(tmp_path):
    results, record = pr.run("dry-run", out_dir=tmp_path, repo_root=REPO, out=lambda s: None)
    assert record is None and len(results) == 5 and not any(v["recognised"] for v in results.values())
    assert list(tmp_path.iterdir()) == []


def test_a_run_needs_a_billing_tier(tmp_path):
    with pytest.raises(pr.ProbeError, match="billing-tier"):
        pr.run("run", out_dir=tmp_path, repo_root=REPO, client=llm.FakeClient(lambda p, s, r: pr.FAKE_ANSWER))


def test_a_run_saves_answers_and_a_record(tmp_path, git_repo):
    import shutil
    from pathlib import Path
    real = Path(pr.__file__).resolve().parents[1]
    shutil.copytree(real / "library", git_repo / "library")
    (git_repo / "eval" / "probes").mkdir(parents=True)
    shutil.copyfile(pr.PROBES, git_repo / "eval" / "probes" / "probes.yaml")
    commit(git_repo)
    answer = json.dumps({"recognised": True, "name": "the Tennessee Eastman process", "source": None,
                         "number": None, "explanation": "x"})
    results, record = pr.run("run", probes_path=git_repo / "eval" / "probes" / "probes.yaml",
                             out_dir=git_repo / "eval" / "probes", billing_tier="tier-1", repo_root=git_repo,
                             client=llm.FakeClient(lambda p, s, r: answer), out=lambda s: None)
    rec = json.loads(record.read_text())
    assert rec["name"] == "probes" and rec["config"]["billing_tier"] == "tier-1" and rec["config"]["budget_inr"] == 5
    assert rec["metrics"]["recognised"] == 5
    saved = json.loads((git_repo / rec["outputs"]["answers"]["path"]).read_text())
    assert set(saved["answers"]) == set(results) and all("prompt" in a for a in saved["answers"].values())


def test_a_run_records_its_spend_and_a_cached_rerun_costs_nothing(tmp_path, git_repo):
    # Week 7 (carried from week 6): the probes record carries spent_inr; each answer its cost.
    import shutil
    from datetime import datetime, timezone
    from decimal import Decimal
    from pathlib import Path
    real = Path(pr.__file__).resolve().parents[1]
    shutil.copytree(real / "library", git_repo / "library")
    (git_repo / "eval" / "probes").mkdir(parents=True)
    shutil.copyfile(pr.PROBES, git_repo / "eval" / "probes" / "probes.yaml")
    commit(git_repo)
    client = llm.CachedClient(llm.FakeClient(lambda p, s, r: pr.FAKE_ANSWER), tmp_path / "cache")
    kw = dict(probes_path=git_repo / "eval" / "probes" / "probes.yaml", out_dir=git_repo / "eval" / "probes",
              billing_tier="tier-1", repo_root=git_repo, client=client, out=lambda s: None)
    _, first = pr.run("run", now=datetime(2026, 10, 5, 10, tzinfo=timezone.utc), **kw)
    commit(git_repo)                                     # the answers file is committed, as Raj does
    _, second = pr.run("run", now=datetime(2026, 10, 5, 11, tzinfo=timezone.utc), **kw)
    rec1, rec2 = (json.loads(r.read_text()) for r in (first, second))
    saved = json.loads((git_repo / rec1["outputs"]["answers"]["path"]).read_text())["answers"]
    expected = sum(llm.cost_inr(llm.SETTINGS, a["tokens_in"], a["tokens_out"], a["tokens_thinking"])
                   for a in saved.values())
    assert expected > 0 and rec1["metrics"]["spent_inr"] == round(float(expected), 5)
    assert all(not a["cached"] and Decimal(a["cost_inr"]) > 0 for a in saved.values())
    again = json.loads((git_repo / rec2["outputs"]["answers"]["path"]).read_text())["answers"]
    assert rec2["metrics"]["spent_inr"] == 0 and all(a["cached"] and a["cost_inr"] == "0" for a in again.values())