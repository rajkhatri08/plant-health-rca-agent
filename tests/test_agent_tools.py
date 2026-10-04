"""app/agent/tools.py: the evidence and retrieval tools, as of the diagnosis time
(decisions 11, 16, 19, 74, 75; CLAUDE.md, Time and Leakage). Synthetic bundle and stream,
never data/.

The stream is written by the exporter's own row generator (ingest/export_replay.py) and
read back by the app's readers, so the path under test is the one the demo will use."""

import csv
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app.agent import tools
from app.detector import bundle as bm
from app.detector import features, rbc, replay
from app.library import store
from dataset.convert import VARIABLES
from eval import cases
from ingest import export_replay as ex
from ingest import tags as tagmap
from shared import leak_scan
from tests.replay_helpers import add_normals, add_watch, make_bundle
from tests.test_authoring import INTERVAL
from tests.test_export_replay import held_runs
from tests.test_fit_pca import FAST

SAMPLES, STEP_FROM, T = 60, 30, 35          # a step on the fast tags from sample 30; notified at 35
H = "h-0001"                                # an opaque history ID


def ts(sample):
    return ex.START + (sample - 1) * ex.STEP


@pytest.fixture
def v3(tmp_path):
    return bm.load(add_normals(add_watch(make_bundle(tmp_path / "pca_v3"))))


@pytest.fixture
def run_values():
    x = held_runs(numbers=[1], samples=SAMPLES, seed=11).runs[1]
    x[STEP_FROM - 1:, tagmap.column_indices(VARIABLES, FAST)] += np.float32(4.0)
    return x


def write_stream(path, x):
    pubs = ex.publications(x, VARIABLES, ex.analyzer_intervals())
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(replay.HEADER)
        w.writerows(ex.stream_rows(x, VARIABLES, FAST, pubs))
    return path


@pytest.fixture
def history(tmp_path, v3, run_values):
    return tools.load_history(write_stream(tmp_path / "stream.csv", run_values), v3)


@pytest.fixture
def library():
    return store.load()


@pytest.fixture
def tk(v3, library, history):
    return tools.Tools(v3, library, {H: history})


def at(minutes):
    return ts(T) + timedelta(minutes=minutes)


# ---------- the cut at as_of: no look-ahead ----------

def test_at_plus_30_there_is_no_revised_reading(tk):
    out = tk.evidence(H, ts(T), at(30))
    assert set(out["features"]) == {"location", "provisional"}
    assert out["notified_at"] == ts(T).strftime(ex.TS_FORMAT) and out["as_of"] == at(30).strftime(ex.TS_FORMAT)


def test_at_plus_60_both_readings(tk):
    assert set(tk.evidence(H, ts(T), at(60))["features"]) == {"location", "provisional", "revised"}


def poisoned_after(h, sample):
    """The same history with every fast value after `sample` NaN and every analyzer value
    published after it NaN. Reading any of them would raise (a gap never reads as normal),
    so an unchanged answer proves they weren't read."""
    values = h.stream.values.copy()
    values[sample:] = np.nan
    cut = ts(sample)
    analyzers = {t: tuple((w, v if w <= cut else float("nan")) for w, v in items)
                 for t, items in h.analyzers.items()}
    return tools.History(stream=replace(h.stream, values=values), analyzers=analyzers)


def test_the_plus_30_pass_cannot_see_plus_60_data(v3, library, history):
    # Decision 11, CLAUDE.md Time: everything after +30 min is poisoned. The +30 min pass
    # gives exactly the clean answer, and the +60 min pass on the poisoned stream fails,
    # so the data it needs were there and were not read at +30.
    tk = tools.Tools(v3, library, {"clean": history, "poisoned": poisoned_after(history, T + 10)})
    clean = tk.evidence("clean", ts(T), at(30))
    assert tk.evidence("poisoned", ts(T), at(30)) == clean
    with pytest.raises(tools.ToolError, match="can't be read"):
        tk.evidence("poisoned", ts(T), at(60))


def test_changing_the_future_changes_nothing_now(v3, library, history):
    # The same check with finite data: a big change after +30 min leaves the +30 answer alone
    # and changes the +60 answer. The step already reads "high", so the change goes the other
    # way: the +60 window then holds runs on both sides.
    values = history.stream.values.copy()
    values[T + 10:] -= 50.0
    later = tools.History(stream=replace(history.stream, values=values), analyzers=history.analyzers)
    tk = tools.Tools(v3, library, {"a": history, "b": later})
    assert tk.evidence("a", ts(T), at(30)) == tk.evidence("b", ts(T), at(30))
    assert tk.evidence("a", ts(T), at(60)) != tk.evidence("b", ts(T), at(60))


def test_an_analyzer_published_after_as_of_is_unseen(v3, library, history):
    # Remove every analyzer publication after +30 min: the +30 answer can't change.
    cut = at(30)
    early = tools.History(stream=history.stream,
                          analyzers={t: tuple(p for p in items if p[0] <= cut)
                                     for t, items in history.analyzers.items()})
    tk = tools.Tools(v3, library, {"a": history, "b": early})
    assert tk.evidence("a", ts(T), cut) == tk.evidence("b", ts(T), cut)


def test_a_gap_before_the_window_is_never_scored(v3, library, history):
    # RBC is computed on the triggering samples only, so a gap earlier in the stream
    # (outside the window) doesn't stop the evidence.
    values = history.stream.values.copy()
    values[5] = np.nan
    gappy = tools.History(stream=replace(history.stream, values=values), analyzers=history.analyzers)
    tk = tools.Tools(v3, library, {"a": history, "b": gappy})
    assert tk.evidence("a", ts(T), at(30)) == tk.evidence("b", ts(T), at(30))


# ---------- one engine: the same features as evaluation ----------

def eval_features(b, x, t):
    """The evaluation's own path (eval/cases._features_at) on the whole run."""
    plant = features.plant_from_files(b.model.tags)
    names = list(b.watch["groups"])
    inp = SimpleNamespace(plant=plant, bands=b.bands(), lim=b.limits, names=names,
                          w_group=np.array([b.watch["groups"][g]["w"] for g in names]),
                          w_tag=np.array([b.watch["tags"][tg] for tg in b.model.tags]),
                          interval=INTERVAL)
    fast_cols = tagmap.column_indices(VARIABLES, b.model.tags)
    an_cols = dict(zip(plant.analyzers, tagmap.column_indices(VARIABLES, plant.analyzers)))
    M = rbc.index_matrix(b.model, b.limits["t2_lim"], b.limits["spe_lim"])
    cols = [tuple(b.model.tags.index(tg) for tg in b.watch["groups"][g]["tags"]) for g in names]
    X = x[:, fast_cols]
    by_group, by_tag = {1: rbc.group_rbc(b.model, M, X, cols)}, {1: rbc.tag_rbc(b.model, M, X)}
    return cases._features_at(inp, x, t, 1, by_group, by_tag, fast_cols, an_cols)


def test_parity_with_the_evaluation_path(v3, tk, run_values):
    want = eval_features(v3, run_values, T)
    assert tk.evidence(H, ts(T), at(60))["features"] == want
    assert tk.evidence(H, ts(T), at(30))["features"] == {k: want[k] for k in ("location", "provisional")}


def test_the_evidence_is_states_only(tk):
    f = tk.evidence(H, ts(T), at(60))["features"]
    leaves = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        else:
            leaves.append(v)
    walk(f)
    assert all(isinstance(v, (str, bool)) for v in leaves)          # no raw values (decision 75)


# ---------- refusals ----------

def test_needs_a_v3_bundle(tmp_path, library, history):
    v2 = bm.load(add_watch(make_bundle(tmp_path / "pca_v2")))
    with pytest.raises(tools.ToolError, match="pca_v3"):
        tools.Tools(v2, library, {H: history})


@pytest.mark.parametrize("hid, notified, as_of, match", [
    (H, ts(T).replace(tzinfo=None), at(30), "timezone-aware"),
    (H, ts(T), at(30).replace(tzinfo=None), "timezone-aware"),
    (H, ts(T), ts(T) - timedelta(minutes=3), "before the notification"),
    ("h-9999", ts(T), at(30), "no history"),
    (H, ts(T) + timedelta(minutes=1), at(30), "isn't a sample"),
    (H, ts(1), ts(1) + timedelta(minutes=30), "fewer than n"),
])
def test_refusals(tk, hid, notified, as_of, match):
    with pytest.raises(tools.ToolError, match=match):
        tk.evidence(hid, notified, as_of)


def test_times_in_another_zone_mean_the_same_instant(tk):
    ist = timezone(timedelta(hours=5, minutes=30))
    assert tk.evidence(H, ts(T).astimezone(ist), at(30).astimezone(ist)) == tk.evidence(H, ts(T), at(30))


def test_a_leak_withholds_the_whole_output(tk, monkeypatch):
    real = features.extract
    monkeypatch.setattr(features, "extract", lambda *a, **k: {**real(*a, **k), "note": "fault 4"})
    with pytest.raises(leak_scan.LeakError, match="evidence tool"):
        tk.evidence(H, ts(T), at(30))


# ---------- the historian readers ----------

def test_publications_are_read_at_their_times_only(tmp_path, v3, run_values, history):
    pubs = ex.publications(run_values, VARIABLES, ex.analyzer_intervals())
    for tag, items in pubs.items():
        assert [(w, v) for w, v in history.analyzers[tag]] == [(ts(s), v) for s, v in items]
    assert np.array_equal(history.stream.values,
                          run_values[:, tagmap.column_indices(VARIABLES, FAST)].astype(np.float64))


def test_a_bad_quality_publication_reads_as_a_gap(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("ts,tag,value,quality\n"
                    "2026-01-05T06:00:00Z,RX-AI-901,1.5,good\n"
                    "2026-01-05T06:18:00Z,RX-AI-901,2.5,bad\n")
    (a, b), = [replay.read_publications(path, ["RX-AI-901"])["RX-AI-901"]]
    assert a[1] == 1.5 and np.isnan(b[1])


def test_a_repeated_publication_is_refused(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("ts,tag,value,quality\n"
                    "2026-01-05T06:00:00Z,RX-AI-901,1.5,good\n"
                    "2026-01-05T06:00:00Z,RX-AI-901,2.5,good\n")
    with pytest.raises(replay.ReplayError, match="twice"):
        replay.read_publications(path, ["RX-AI-901"])


# ---------- retrieval ----------

AFTER_R2 = datetime(2026, 10, 5, tzinfo=timezone.utc)          # mixed-feed-temperature-wander r2 approved 4 Oct 08:09
BEFORE_R2 = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
BEFORE_ALL = datetime(2026, 9, 1, tzinfo=timezone.utc)
WANDER = "mixed-feed-temperature-wander"


def test_retrieve_gives_the_revision_in_force_without_sources(tk):
    out = tk.retrieve([WANDER, "reaction-rate-drift"], AFTER_R2)
    assert [e["ref"] for e in out["entries"]] == [f"{WANDER}@r2", "reaction-rate-drift@r1"]
    assert out["not_in_force"] == [] and out["as_of"] == "2026-10-05T00:00:00Z"
    assert all("sources" not in e for e in out["entries"])
    assert tk.retrieve([WANDER], BEFORE_R2)["entries"][0]["ref"] == f"{WANDER}@r1"


def test_retrieve_never_returns_what_isnt_in_force(tk):
    out = tk.retrieve([WANDER, "no-such-entry"], BEFORE_ALL)
    assert out["entries"] == [] and out["not_in_force"] == [WANDER, "no-such-entry"]


def test_retrieve_keeps_the_order_asked_and_each_once(tk):
    ids = ["reaction-rate-drift", WANDER, "reaction-rate-drift"]
    assert [e["entry_id"] for e in tk.retrieve(ids, AFTER_R2)["entries"]] == ["reaction-rate-drift", WANDER]


def test_retrieve_refuses_a_naive_time(tk):
    with pytest.raises(tools.ToolError, match="timezone-aware"):
        tk.retrieve([WANDER], AFTER_R2.replace(tzinfo=None))


def test_a_leak_in_retrieval_withholds_it(tk, monkeypatch):
    real = store.agent_view
    monkeypatch.setattr(store, "agent_view", lambda item: {**real(item), "title": "Tennessee"})
    with pytest.raises(leak_scan.LeakError, match="retrieval tool"):
        tk.retrieve([WANDER], AFTER_R2)


def test_retrieved_entries_are_clean_json(tk):
    out = tk.retrieve(list(tk.library.entry_ids()), AFTER_R2)
    assert len(out["entries"]) == 12
    assert leak_scan.find_leaks(json.dumps(out)) == []


# ---------- walls ----------

def test_tools_import_the_shared_scan_not_eval():
    from pathlib import Path
    from tests.test_walls import imported_top_modules
    mods = imported_top_modules(Path(tools.__file__).read_text())
    assert "shared" in mods and not {"eval", "ingest", "dataset"} & mods