"""The committed thin-slice files: the bundle, the replay CSV and a live API on them.

These run once eval/replay_source.yaml exists (written by ingest/export_replay.py).
From then on a missing or changed file fails.
"""

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import api
from app.detector import bundle as bm
from tests.test_leak_scan import find_leaks

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "eval" / "replay_source.yaml"

pytestmark = pytest.mark.skipif(not SOURCE.exists(), reason="replay stream not exported yet")


def test_bundle_self_test_passes():
    assert bm.DEFAULT_BUNDLE.name == "pca_v2"
    assert bm.self_test(bm.load(bm.DEFAULT_BUNDLE))


def test_pca_v1_is_kept_and_still_passes():
    v1 = bm.load(bm.DEFAULT_BUNDLE.parent / "pca_v1")
    assert v1.watch is None and bm.self_test(v1)


def test_watch_record_is_a_committed_run_record():
    w = json.loads((bm.DEFAULT_BUNDLE / "watch.json").read_text())
    shas = {hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (REPO / "eval" / "runs").glob("*_calibrate_watch.json")}
    assert w["watch_record_sha256"] in shas


def test_bundle_records_are_committed_run_records():
    lim = json.loads((bm.DEFAULT_BUNDLE / "limits.json").read_text())
    shas = {hashlib.sha256(p.read_bytes()).hexdigest() for p in (REPO / "eval" / "runs").glob("*.json")}
    assert lim["fit_record_sha256"] in shas and lim["calibration_record_sha256"] in shas


def test_csv_matches_its_source_record():
    doc = yaml.safe_load(SOURCE.read_text())
    csv_path = REPO / doc["csv"]
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == doc["csv_sha256"]


def test_live_api_on_the_committed_files_is_clean():
    with TestClient(api.create_app(allowed_origins=[])) as c:
        assert c.get("/health").json()["self_test"] == "pass"
        info = c.get("/replay/info").json()
        body = c.get("/replay/status", params={"upto": info["end"]}).text
    assert info["groups"] == ["feed", "reactor", "condenser", "separator", "compressor", "stripper"]
    assert "Watch" in info["bands"] and "note" not in info
    assert find_leaks(body) == []
