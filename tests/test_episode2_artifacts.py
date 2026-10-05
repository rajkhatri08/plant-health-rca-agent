"""The committed episode-2 stream (week 6 S9): app/replay/episode2.csv and its builder-side source
record, as written by `python -m ingest.export_replay --episode 2`. These run once the source record
exists; from then on a missing or changed file fails. Nothing here reads data/."""

import hashlib
from pathlib import Path

import pytest
import yaml

from app.detector import bundle as bm
from app.detector import replay
from ingest import export_replay as ex
from tests.test_leak_scan import find_leaks

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "eval" / "replay_source_episode2.yaml"

pytestmark = pytest.mark.skipif(not SOURCE.exists(), reason="episode 2 isn't exported yet")


def test_the_stream_matches_its_source_record():
    doc = yaml.safe_load(SOURCE.read_text())
    csv_path = REPO / doc["csv"]
    assert doc["csv"] == "app/replay/episode2.csv" and doc["episode"] == 2
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == doc["csv_sha256"]
    assert doc["rows"] == doc["fast_rows"] + doc["analyzer_rows"] and (doc["tags"], doc["analyzers"]) == (33, 19)


def test_it_was_chosen_by_rule_the_masked_fault_on_the_lowest_dev_number():
    doc = yaml.safe_load(SOURCE.read_text())
    assert doc["fault"] == ex.masked_fault(REPO) and doc["pool"] == "dev"
    v2 = yaml.safe_load((REPO / "eval" / "replay_source_v2.yaml").read_text())
    assert doc["run"] == v2["run"]                                     # the same lowest dev run number


def test_the_fault_stays_builder_side():
    text = (REPO / "app" / "replay" / "episode2.csv").read_text()
    assert find_leaks(text) == [] and text.splitlines()[0] == "ts,tag,value,quality"
    assert SOURCE.read_text().startswith("# Builder side only")


def test_it_replays_through_the_served_bundle_and_alerts():
    b = bm.load(bm.DEFAULT_BUNDLE)
    s = replay.read_csv(REPO / "app" / "replay" / "episode2.csv", b.model.tags)
    rows = replay.status(b, s, s.ts[-1])
    assert any(r["band"] == "Alert" for r in rows)
