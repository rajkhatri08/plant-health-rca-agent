"""The committed week 6 S2 files: bundle pca_v3 and the replay stream with analyzers
(app/replay/run_v2.csv), with the agent's tools on them.

These run once eval/replay_source_v2.yaml exists (written by ingest/export_replay.py).
From then on a missing or changed file fails. Like tests/test_thin_slice_artifacts.py,
nothing here reads data/.
"""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import api
from app.agent import tools
from app.detector import bundle as bm
from app.detector import replay
from app.library import store
from tests.test_leak_scan import find_leaks

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "eval" / "replay_source_v2.yaml"
V2, V3 = REPO / "app" / "bundles" / "pca_v2", REPO / "app" / "bundles" / "pca_v3"
RUN_V1 = REPO / "app" / "replay" / "run.csv"

pytestmark = pytest.mark.skipif(not SOURCE.exists(), reason="replay stream v2 not exported yet")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def source():
    return yaml.safe_load(SOURCE.read_text())


@pytest.fixture(scope="module")
def csv_path(source):
    return REPO / source["csv"]


# ---------- pca_v3 ----------

def test_v3_self_test_passes_and_v2_is_still_served():
    b = bm.load(V3)
    assert b.normals is not None and b.watch is not None and bm.self_test(b)
    assert bm.DEFAULT_BUNDLE.name == "pca_v2"


def test_v3_is_v2_plus_normals():
    assert sorted(p.name for p in V3.iterdir()) == ["limits.json", "model.npz", "normals.json", "watch.json"]
    for name in ("model.npz", "limits.json", "watch.json"):
        assert (V3 / name).read_bytes() == (V2 / name).read_bytes(), name


def test_v3_normals_come_from_a_committed_record():
    n = json.loads((V3 / "normals.json").read_text())
    records = {sha(p): p for p in (REPO / "eval" / "runs").glob("*_evidence_normals.json")}
    assert n["normals_record_sha256"] in records
    rec = json.loads(records[n["normals_record_sha256"]].read_text())
    assert rec["metrics"]["bands"] == n["tags"]
    assert n["pool"] == "calibration" and len(n["tags"]) == 52


# ---------- run_v2.csv ----------

def test_csv_matches_its_source_record(source, csv_path):
    assert source["csv"] == "app/replay/run_v2.csv"
    assert sha(csv_path) == source["csv_sha256"]
    lines = csv_path.read_text().splitlines()
    assert lines[0] == "ts,tag,value,quality" and len(lines) - 1 == source["rows"]
    assert source["rows"] == source["fast_rows"] + source["analyzer_rows"]
    assert (source["tags"], source["analyzers"], source["samples"]) == (33, 19, 500)


def test_same_run_as_the_served_stream(csv_path):
    # The fast part of run_v2.csv is exactly the served run.csv: the same run, exported by
    # the same row generator, so switching REPLAY_CSV in S9 changes no score.
    tags = bm.load(V2).model.tags
    a, b = replay.read_csv(RUN_V1, tags), replay.read_csv(csv_path, tags)
    assert a.ts == b.ts and (a.values == b.values).all()


def test_analyzers_appear_only_at_their_publications(csv_path):
    plant_analyzers = [r["tag"] for r in yaml.safe_load((REPO / "library" / "tags.yaml").read_text())["tags"]
                       if r["kind"] == "analyzer"]
    pubs = replay.read_publications(csv_path, plant_analyzers)
    assert set(pubs) == set(plant_analyzers)
    for tag, items in pubs.items():
        assert 0 < len(items) < 500, tag                       # held between publications, not repeated
        assert list(items) == sorted(items, key=lambda p: p[0])


def test_live_api_on_run_v2_equals_run_v1(csv_path):
    def status(path):
        with TestClient(api.create_app(csv_path=path, allowed_origins=[])) as c:
            info = c.get("/replay/info").json()
            return info, c.get("/replay/status", params={"upto": info["end"]}).json()
    assert status(csv_path) == status(RUN_V1)


# ---------- the tools on the committed files ----------

@pytest.fixture(scope="module")
def tk(csv_path):
    b = bm.load(V3)
    return tools.Tools(b, store.load(), {"replay": tools.load_history(csv_path, b)}), b


def first_notification(b, history):
    rows = replay.status(b, history.stream, history.stream.ts[-1])
    for i in range(1, len(rows)):
        if rows[i]["band"] == "Alert" and rows[i - 1]["band"] != "Alert":
            return history.stream.ts[i]
    pytest.fail("the committed stream has no notification")


def test_evidence_on_the_committed_stream_is_clean_and_as_of(tk):
    t, b = tk
    notified = first_notification(b, t.histories["replay"])
    at30 = t.evidence("replay", notified, notified + timedelta(minutes=30))
    at60 = t.evidence("replay", notified, notified + timedelta(minutes=60))
    assert set(at30["features"]) == {"location", "provisional"}
    assert set(at60["features"]) == {"location", "provisional", "revised"}
    assert at60["features"]["provisional"] == at30["features"]["provisional"]
    assert find_leaks(json.dumps(at60)) == []