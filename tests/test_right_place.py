"""eval/metrics.right_place on hand-built cases (decision 65). Fails with
NotImplementedError until Raj implements it."""

import pytest

from eval import metrics

NAMES = ["feed", "reactor", "condenser", "separator", "compressor", "stripper"]


@pytest.mark.parametrize("order, allowed, expected", [
    ([1, 0, 2, 3, 4, 5], ("reactor",), True),               # reactor ranked first
    ([0, 1, 2, 3, 4, 5], ("reactor",), False),              # reactor second is still a miss
    ([5, 0, 1, 2, 3, 4], ("stripper", "feed"), True),       # a family with two groups
    ([0, 5, 1, 2, 3, 4], ("stripper", "feed"), True),
    ([2, 5, 0, 1, 3, 4], ("stripper", "feed"), False),      # both allowed groups below the top
])
def test_top_group_in_the_family(order, allowed, expected):
    assert metrics.right_place(order, NAMES, allowed) is expected


def test_accepts_numpy_order_and_tuples():
    import numpy as np
    assert metrics.right_place(np.array([2, 0, 1, 3, 4, 5]), tuple(NAMES), ["condenser"]) is True


@pytest.mark.parametrize("order, names, allowed", [
    ([], NAMES, ("feed",)),                                 # empty order
    ([0, 1, 2], NAMES, ("feed",)),                          # not every column
    ([0, 0, 1, 2, 3, 4], NAMES, ("feed",)),                 # a repeated column
    ([6, 0, 1, 2, 3, 4], NAMES, ("feed",)),                 # a column that doesn't exist
    ([0, 1], ["feed", "feed"], ("feed",)),                  # repeated names
    ([0, 1, 2, 3, 4, 5], NAMES, ()),                        # no allowed groups
    ([0, 1, 2, 3, 4, 5], NAMES, ("strippper",)),            # a typo in the map: not a miss
])
def test_refusals(order, names, allowed):
    with pytest.raises(ValueError):
        metrics.right_place(order, names, allowed)


def test_secondary_offset_is_30_minutes():
    assert metrics.SECONDARY_OFFSET * metrics.SAMPLE_MIN == 30
