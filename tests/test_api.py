"""app/api.py with FastAPI's TestClient, on a synthetic bundle and stream."""

import json

import pytest
from fastapi.testclient import TestClient

from app import api
from dataset.convert import VARIABLES
from ingest import export_replay
from tests.replay_helpers import edit_limits, make_bundle, stream_run, write_csv
from tests.test_leak_scan import find_leaks

FMT = export_replay.TS_FORMAT


def ts(sample):
    return (export_replay.START + (sample - 1) * export_replay.STEP).strftime(FMT)


@pytest.fixture
def paths(tmp_path):
    folder = make_bundle(tmp_path / "pca_v1")
    csv_path = write_csv(tmp_path / "run.csv", stream_run()[0], VARIABLES)
    return folder, csv_path


def client(paths, origins=()):
    return TestClient(api.create_app(*paths, allowed_origins=list(origins)))


def test_health_ok(paths):
    with client(paths) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "self_test": "pass", "bundle": "pca_v1"}


def test_failed_self_test_blocks_scoring(paths):
    edit_limits(paths[0], n=9)                            # breaks decision 52 (warm-up 3)
    with client(paths) as c:
        h, s = c.get("/health"), c.get("/replay/status", params={"upto": ts(40)})
    assert h.status_code == 503 and h.json()["self_test"] == "fail"
    assert "decision 52" in h.json()["detail"]
    assert s.status_code == 503


def test_missing_stream_blocks_scoring(paths):
    paths[1].unlink()
    with client(paths) as c:
        assert c.get("/health").status_code == 503
        assert c.get("/replay/info").status_code == 503


def test_info(paths):
    with client(paths) as c:
        r = c.get("/replay/info").json()
    assert r["start"] == ts(1) and r["end"] == ts(60) and r["samples"] == 60
    assert r["step_min"] == 3 and r["warmup_samples"] == 3
    assert r["bands"] == ["Normal", "Alert", "Unknown"] and "Watch" in r["note"]


def test_status_is_as_of(paths):
    with client(paths) as c:
        early = c.get("/replay/status", params={"upto": ts(20)}).json()
        full = c.get("/replay/status", params={"upto": ts(60)}).json()
    assert len(early["samples"]) == 20 and early["current"] == early["samples"][-1]
    assert early["samples"] == full["samples"][:20]
    assert early["as_of"] == ts(20)
    assert "Alert" in {s["band"] for s in full["samples"]}


def test_status_before_start_is_empty(paths):
    with client(paths) as c:
        r = c.get("/replay/status", params={"upto": "2020-01-01T00:00:00Z"}).json()
    assert r["samples"] == [] and r["current"] is None


@pytest.mark.parametrize("upto", ["yesterday", "2026-01-05 07:00:00", "2026-01-05T07:00:00"])
def test_bad_upto_is_422(paths, upto):
    with client(paths) as c:
        assert c.get("/replay/status", params={"upto": upto}).status_code == 422


def test_upto_is_required(paths):
    with client(paths) as c:
        assert c.get("/replay/status").status_code == 422


def test_cors_only_for_the_allowed_origin(paths):
    ok, other = "https://plant.example.app", "https://elsewhere.example"
    with client(paths, [ok]) as c:
        allowed = c.get("/health", headers={"Origin": ok})
        refused = c.get("/health", headers={"Origin": other})
    assert allowed.headers.get("access-control-allow-origin") == ok
    assert "access-control-allow-origin" not in refused.headers


def test_no_cors_by_default(paths):
    with client(paths) as c:
        r = c.get("/health", headers={"Origin": "https://plant.example.app"})
    assert "access-control-allow-origin" not in r.headers


def test_no_write_routes(paths):
    # Advisory only: every route is a GET.
    methods = {m for route in api.create_app(*paths).routes for m in getattr(route, "methods", ())}
    assert methods <= {"GET", "HEAD"}


def test_live_responses_have_no_leaks(paths):
    # eval/LEAKAGE.md, CI checks: tool and API outputs carry no raw names, labels,
    # benchmark or source names. Scan every response body, including errors.
    with client(paths) as c:
        bodies = [c.get("/health").text, c.get("/replay/info").text,
                  c.get("/replay/status", params={"upto": ts(60)}).text,
                  c.get("/replay/status", params={"upto": "bad"}).text]
    for body in bodies:
        assert find_leaks(body) == []
        assert not {"run", "fault", "sample_number"} & set(_keys(json.loads(body)))


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)