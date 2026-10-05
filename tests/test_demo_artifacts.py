"""The committed demo (week 6 S9): app/replay/demo.json and app/replay/llm_cache/, as written by
eval/build_demo.py. These run once demo.json exists; from then on a missing, changed or
unservable file fails. Nothing here calls a model: the API serves through ReplayClient."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api
from app.agent import demo
from app.detector import replay
from eval import agent_table as at
from tests.test_leak_scan import find_leaks

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "app" / "replay" / demo.CONFIG

pytestmark = pytest.mark.skipif(not CONFIG.exists(), reason="the demo isn't built yet (eval/build_demo.py)")


def test_the_demo_was_built_with_the_frozen_prompt_and_is_recorded():
    cfg = json.loads(CONFIG.read_text())
    assert cfg["prompt_sha256"] == at.prompt_sha256(REPO / "app" / "agent" / "prompts")
    assert cfg["notes"] == demo.NOTES and cfg["bundle"] == "pca_v3" and cfg["stream"] == "run_v2.csv"
    shas = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in (REPO / "eval" / "runs").glob("*_build_demo.json")}
    recs = [json.loads(p.read_text()) for p in shas.values()]
    assert any(r["outputs"]["config"]["sha256"] == hashlib.sha256(CONFIG.read_bytes()).hexdigest() for r in recs)


def test_the_live_api_serves_every_note_at_every_time_cleanly():
    cfg = json.loads(CONFIG.read_text())
    n = replay.parse_ts(cfg["notified_at"])
    with TestClient(api.create_app(allowed_origins=[])) as c:
        assert c.get("/health").json()["diagnosis"] == "ready"
        bodies = []
        for note in demo.NOTES:
            for m in (-30, 0, 15, 30, 45, 60, 180):
                r = c.get("/diagnosis", params={"upto": (n + timedelta(minutes=m)).strftime(replay.TS_FORMAT),
                                                "note": note})
                assert r.status_code == 200
                body = r.json()
                assert body["available"] is (m >= 30)
                if m < 0:
                    assert "alert_at" not in body
                bodies.append(r.text)
    assert all(find_leaks(b) == [] for b in bodies)


def test_the_emergency_note_was_never_sent_to_the_model():
    cfg = json.loads(CONFIG.read_text())
    n = replay.parse_ts(cfg["notified_at"])
    with TestClient(api.create_app(allowed_origins=[])) as c:
        for m in (30, 60):
            d = c.get("/diagnosis", params={"upto": (n + timedelta(minutes=m)).strftime(replay.TS_FORMAT),
                                            "note": "emergency"}).json()["diagnosis"]
            assert d["outcome"] == "emergency"
