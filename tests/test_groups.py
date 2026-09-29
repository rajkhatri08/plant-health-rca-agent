"""app/detector/groups.py: equipment groups as column indices (decisions 48, 64)."""

import pytest

from app.detector import bundle, groups

FAST = bundle.fast_tags()                  # the detector's 33 tags, in register order


def test_fast_tags_group_sizes_in_register_order():
    g = groups.load(FAST)
    assert list(g) == ["feed", "reactor", "condenser", "separator", "compressor", "stripper"]
    assert {k: len(v) for k, v in g.items()} == {"feed": 8, "reactor": 6, "condenser": 2,
                                                 "separator": 7, "compressor": 3, "stripper": 7}


def test_groups_partition_the_columns():
    g = groups.load(FAST)
    cols = sorted(i for v in g.values() for i in v)
    assert cols == list(range(len(FAST)))


def test_indices_follow_the_given_order_not_the_register():
    reordered = tuple(reversed(FAST))
    g = groups.load(reordered)
    for name, cols in g.items():
        assert {reordered[i] for i in cols} == {FAST[i] for i in groups.load(FAST)[name]}
    assert g["condenser"] == tuple(sorted(g["condenser"]))


def test_known_members():
    g = groups.load(FAST)
    assert {FAST[i] for i in g["condenser"]} == {"CD-TI-301", "CD-FV-302"}
    assert "RX-FV-206" in {FAST[i] for i in g["reactor"]}


def test_groups_with_no_given_tags_are_left_out():
    assert groups.load(("CD-FV-302", "FD-FI-101")) == {"feed": (1,), "condenser": (0,)}


@pytest.mark.parametrize("bad", [("XX-TI-999",), ("RX-TI-204@t-1",), ("RX-TI-204", "RX-TI-204")])
def test_unknown_lagged_or_repeated_tags_refused(bad):
    with pytest.raises(groups.GroupError):
        groups.load(bad)


def test_register_row_without_a_group_refused(tmp_path):
    reg = tmp_path / "tags.yaml"
    reg.write_text("tags:\n- {tag: RX-TI-204, kind: measurement}\n")
    with pytest.raises(groups.GroupError, match="no group"):
        groups.load(("RX-TI-204",), register=reg)
