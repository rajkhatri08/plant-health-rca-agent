"""ingest/export_replay.py on synthetic runs (never data/).

The second export (week 6 S2) adds the 19 analyzers, each at its publication time only.
The synthetic runs hold every analyzer on its register schedule, as the stored data does."""

import csv
import json
import re
import hashlib

import numpy as np
import pytest
import yaml

import dataset.loader as loader_mod
from app.detector import replay
from dataset import splits
from dataset.convert import VARIABLES
from dataset.loader import Runs
from eval import cases
from ingest import export_replay as ex
from ingest import tags as tagmap
from tests.test_authoring import ANALYZERS, INTERVAL, hold
from tests.test_fit_pca import FAST, two_factor_runs
from tests.test_leak_scan import find_leaks

DEV = [44, 7, 301]
SAMPLES = 30


def held_runs(numbers=DEV, samples=SAMPLES, seed=0):
    runs = two_factor_runs(numbers=numbers, samples=samples, seed=seed)
    an = dict(zip(ANALYZERS, tagmap.column_indices(VARIABLES, ANALYZERS)))
    for x in runs.runs.values():
        for t, c in an.items():
            x[:, c] = hold(x[:, c], INTERVAL[t])
    return runs


def expected_publications(x):
    an = dict(zip(ANALYZERS, tagmap.column_indices(VARIABLES, ANALYZERS)))
    return {t: cases.publications_from_held(x[:, c], INTERVAL[t]) for t, c in an.items()}


@pytest.fixture
def fake(tmp_path, monkeypatch, git_repo):
    calls = []
    runs = held_runs()

    def load_faulty(fault, pool):
        calls.append((fault, pool))
        return Runs("faulty_training", fault, pool, VARIABLES, runs.runs)

    monkeypatch.setattr(loader_mod, "load_faulty", load_faulty)
    monkeypatch.setattr(splits, "load", lambda repo_root=None: {"pools": {"dev": DEV}})
    return {"csv": git_repo / "app" / "replay" / "run_v2.csv",
            "source": git_repo / "eval" / "replay_source_v2.yaml",
            "repo": git_repo, "runs": runs, "calls": calls}


def export(f):
    return ex.run(f["csv"], f["source"], repo_root=f["repo"])


def body(f):
    with open(f["csv"], newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["ts", "tag", "value", "quality"]
    return rows[1:]


def test_defaults_are_new_files_so_the_served_stream_is_untouched():
    assert ex.DEFAULT_CSV.name == "run_v2.csv" and ex.DEFAULT_SOURCE.name == "replay_source_v2.yaml"
    from app import api
    assert api.DEFAULT_CSV.name == "run_v2.csv"                      # served since week 6 S9


def test_mechanical_choice_is_fault_13_on_the_lowest_dev_number(fake):
    doc = export(fake)
    assert fake["calls"] == [(13, "dev")]
    assert doc["fault"] == 13 and doc["run"] == 7 and doc["pool"] == "dev"


def test_each_sample_has_the_fast_tags_then_the_analyzers_that_published(fake):
    export(fake)
    rows = body(fake)
    pubs = expected_publications(fake["runs"].runs[7])
    at = {}
    for t, items in pubs.items():
        for s, _ in items:
            at.setdefault(s, []).append(t)
    i = 0
    for s in range(1, SAMPLES + 1):
        ts = (ex.START + (s - 1) * ex.STEP).strftime(ex.TS_FORMAT)
        block = rows[i:i + 33 + len(at.get(s, []))]
        assert {r[0] for r in block} == {ts}
        assert [r[1] for r in block] == FAST + at.get(s, [])          # register order in each part
        i += len(block)
    assert i == len(rows)
    assert {r[3] for r in rows} == {"good"}


def test_an_analyzer_appears_only_at_its_publications(fake):
    export(fake)
    rows = body(fake)
    pubs = expected_publications(fake["runs"].runs[7])
    for t in ANALYZERS:
        seen = [(r[0], float(r[2])) for r in rows if r[1] == t]
        want = [((ex.START + (s - 1) * ex.STEP).strftime(ex.TS_FORMAT), v) for s, v in pubs[t]]
        assert seen == want
        assert len(seen) < SAMPLES                                    # not one row per sample


def test_values_round_trip_float32_exactly(fake):
    export(fake)
    rows = body(fake)
    cols = tagmap.column_indices(VARIABLES, FAST)
    x = fake["runs"].runs[7]
    got = np.array([float(r[2]) for r in rows if r[1] in FAST]).reshape(SAMPLES, 33)
    assert np.array_equal(got, x[:, cols].astype(np.float64))
    assert np.array_equal(got.astype(np.float32), x[:, cols])
    an = dict(zip(ANALYZERS, tagmap.column_indices(VARIABLES, ANALYZERS)))
    for r in rows:
        if r[1] in an:
            assert np.float32(float(r[2])) in x[:, an[r[1]]]


def test_the_replay_reader_still_sees_only_the_fast_tags(fake):
    # The live API reads with replay.read_csv(model tags): analyzer rows are skipped, so the
    # new file scores exactly like the 33-tag one.
    export(fake)
    s = replay.read_csv(fake["csv"], FAST)
    cols = tagmap.column_indices(VARIABLES, FAST)
    assert len(s.ts) == SAMPLES and np.array_equal(s.values, fake["runs"].runs[7][:, cols].astype(np.float64))


def test_csv_reveals_neither_the_fault_nor_the_run(fake):
    export(fake)
    text = fake["csv"].read_text()
    assert find_leaks(text) == []
    assert text.splitlines()[0] == "ts,tag,value,quality"


def test_source_is_builder_side_and_pins_the_csv(fake):
    export(fake)
    doc = yaml.safe_load(fake["source"].read_text())
    n_an = sum(len(v) for v in expected_publications(fake["runs"].runs[7]).values())
    assert doc["csv"] == "app/replay/run_v2.csv"
    assert doc["csv_sha256"] == hashlib.sha256(fake["csv"].read_bytes()).hexdigest()
    assert doc["samples"] == SAMPLES and doc["tags"] == 33 and doc["analyzers"] == 19
    assert doc["fast_rows"] == SAMPLES * 33 and doc["analyzer_rows"] == n_an
    assert doc["rows"] == SAMPLES * 33 + n_an
    assert len(doc["commit"]) == 40 and doc["dirty"] is False
    assert fake["source"].read_text().startswith("# Builder side only: which run app/replay/run_v2.csv")


def test_an_off_schedule_analyzer_is_refused_before_writing(fake):
    x = fake["runs"].runs[7]
    c = tagmap.column_indices(VARIABLES, [ANALYZERS[0]])[0]
    x[:, c] = np.arange(SAMPLES, dtype=np.float32)                   # changes every sample
    with pytest.raises(cases.CasesError, match="off the"):
        export(fake)
    assert not fake["csv"].exists() and not fake["source"].exists()


@pytest.mark.parametrize("which", ["csv", "source"])
def test_refuses_to_overwrite_before_loading(fake, which):
    fake[which].parent.mkdir(parents=True, exist_ok=True)
    fake[which].write_text("old")
    with pytest.raises(FileExistsError):
        export(fake)
    assert fake["calls"] == [] and fake[which].read_text() == "old"

# ---------- episode 2: the masked fault (week 6 S9) ----------

def masked_record(repo, faults=(4,)):
    p = repo / ex.MASKED_RECORD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"name": "masked_faults", "metrics": {"masked_faults": list(faults)}}))


def export2(f):
    return ex.run(f["repo"] / "app" / "replay" / "episode2.csv", f["repo"] / "eval" / "replay_source_episode2.yaml",
                  episode=2, repo_root=f["repo"])


def test_episode_2_is_the_masked_fault_on_the_lowest_dev_number(fake):
    masked_record(fake["repo"])
    doc = export2(fake)
    assert fake["calls"] == [(4, "dev")]
    assert (doc["episode"], doc["fault"], doc["run"], doc["pool"]) == (2, 4, 7, "dev")
    assert "masked fault (decision 62" in doc["rule"]


def test_episode_2_writes_an_opaque_stream_and_keeps_the_fault_builder_side(fake):
    masked_record(fake["repo"])
    export2(fake)
    csv_path = fake["repo"] / "app" / "replay" / "episode2.csv"
    text = csv_path.read_text()
    assert text.splitlines()[0] == "ts,tag,value,quality" and find_leaks(text) == []
    assert not re.search(r"(fault|idv|masked|f0?4)", csv_path.name, re.IGNORECASE)
    src = (fake["repo"] / "eval" / "replay_source_episode2.yaml").read_text()
    assert src.startswith("# Builder side only") and yaml.safe_load(src)["fault"] == 4


@pytest.mark.parametrize("faults", [(), (4, 5)])
def test_episode_2_needs_exactly_one_masked_fault(fake, faults):
    masked_record(fake["repo"], faults)
    with pytest.raises(ex.ExportError, match="exactly one"):
        export2(fake)
    assert fake["calls"] == []                                             # refused before loading


def test_the_episode_defaults(fake):
    assert ex.EPISODES[1]["csv"] == ex.DEFAULT_CSV and ex.EPISODES[2]["csv"].name == "episode2.csv"
    assert ex.MASKED_RECORD.as_posix() == "eval/runs/20260928T155738Z_masked_faults.json"
    with pytest.raises(ex.ExportError):
        ex.run(episode=3)


def test_the_committed_masked_record_names_one_fault():
    from pathlib import Path
    assert ex.masked_fault(Path(ex.__file__).resolve().parents[1]) == 4
