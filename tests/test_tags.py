"""ingest/tag_map.yaml (builder side) and library/tags.yaml (agent-visible)."""

import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
GROUPS = {"feed", "reactor", "condenser", "separator", "compressor", "stripper"}
AREA = {"feed": "FD", "reactor": "RX", "condenser": "CD", "separator": "SP",
        "compressor": "CP", "stripper": "ST"}
KINDS = {"FV": "valve", "AI": "analyzer"}
SIGNALS = {"FI": "flow", "PI": "pressure", "LI": "level", "TI": "temperature",
           "JI": "power", "AI": "composition", "FV": "valve"}
TAG = re.compile(r"^(FD|RX|CD|SP|CP|ST)-(FI|PI|LI|TI|JI|AI|FV)-(\d{3})$")
FIELDS = {"tag", "description", "units", "group", "kind", "signal_type",
          "update_interval_min", "dead_time_min"}


@pytest.fixture(scope="module")
def tag_map():
    return yaml.safe_load((REPO / "ingest" / "tag_map.yaml").read_text())["tags"]


@pytest.fixture(scope="module")
def register():
    return yaml.safe_load((REPO / "library" / "tags.yaml").read_text())["tags"]


def test_raw_names_are_exactly_the_52_variables(tag_map):
    expected = {f"xmeas_{i}" for i in range(1, 42)} | {f"xmv_{i}" for i in range(1, 12)}
    raws = [e["raw"] for e in tag_map]
    assert len(raws) == 52 and set(raws) == expected


def test_tags_unique_and_one_to_one(tag_map, register):
    map_tags = [e["tag"] for e in tag_map]
    reg_tags = [e["tag"] for e in register]
    assert not [t for t, n in Counter(map_tags).items() if n > 1]
    assert not [t for t, n in Counter(reg_tags).items() if n > 1]
    assert set(map_tags) == set(reg_tags)


def test_register_fields(register):
    for e in register:
        assert set(e) == FIELDS, e["tag"]
        m = TAG.match(e["tag"])
        assert m, e["tag"]
        area, letters, _ = m.groups()
        assert e["group"] in GROUPS
        assert AREA[e["group"]] == area, e["tag"]
        assert e["kind"] == KINDS.get(letters, "measurement"), e["tag"]
        assert e["signal_type"] == SIGNALS[letters], e["tag"]
        assert e["description"] and e["units"]


def test_numbers_sequential_within_each_area(register):
    by_area = {}
    for e in register:
        area, _, num = TAG.match(e["tag"]).groups()
        by_area.setdefault(area, []).append(int(num))
    for area, nums in by_area.items():
        nums = sorted(nums)
        assert len(set(n // 100 for n in nums)) == 1, area  # one hundred-block per area
        assert nums == sorted(set(nums)), area


def test_counts(register):
    kinds = Counter(e["kind"] for e in register)
    assert kinds["measurement"] == 22 and kinds["valve"] == 11 and kinds["analyzer"] == 19
    fast = [e for e in register if e["kind"] != "analyzer"]
    assert len(fast) == 33
    assert all((e["update_interval_min"], e["dead_time_min"]) == (3, 0) for e in fast)


def test_analyzer_timing(tag_map, register):
    raw_of = {e["tag"]: e["raw"] for e in tag_map}
    for e in register:
        if e["kind"] != "analyzer":
            continue
        n = int(raw_of[e["tag"]].split("_")[1])
        expected = (15, 15) if n >= 37 else (6, 6)
        assert (e["update_interval_min"], e["dead_time_min"]) == expected, e["tag"]


def test_feed_valves_follow_the_flow_order(tag_map):
    tag_of = {e["raw"]: e["tag"] for e in tag_map}
    assert [tag_of[r] for r in ("xmv_3", "xmv_1", "xmv_2", "xmv_4")] == [
        "FD-FV-105", "FD-FV-106", "FD-FV-107", "FD-FV-108"]


def test_components_stay_in_ingest(register):
    text = (REPO / "library" / "tags.yaml").read_text()
    assert "component" not in text.lower()
    for e in register:
        # No single capital component letter standing alone (A-H), e.g. "feed A".
        assert not re.search(r"\b[A-H]\b", e["description"]), e["tag"]
