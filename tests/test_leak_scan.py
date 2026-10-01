"""Leak scan over agent-visible text (eval/LEAKAGE.md, wall 2)."""

import re
from pathlib import Path

import pytest

from eval.leak_scan import PATTERNS, RAW_NAMES, WORDS, find_leaks  # noqa: F401 (re-exported for other tests)

REPO = Path(__file__).resolve().parents[1]

RAW_ONLY = [re.compile(r"(?:xmeas|xmv)", re.IGNORECASE)]

AGENT_VISIBLE = ["library", "app/agent/prompts"]
# What the API and the web page serve or are built from: the API source, the replay stream, the bundle
# text files and web/ (binary .npz is skipped: random bytes can spell a short word).
SERVED = ["app/api.py", "app/replay", "app/bundles", "web"]
TEXT_SUFFIXES = {".py", ".json", ".csv", ".yaml", ".yml", ".md", ".txt", ".html"}


def scan(dirs, patterns, suffixes=None):
    hits = []
    for d in dirs:
        root = REPO / d
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if suffixes is not None and path.suffix not in suffixes:
                continue
            text = path.read_text(errors="ignore")
            hits += [f"{path.relative_to(REPO)}: {h}" for h in find_leaks(text, patterns)]
    return hits


def test_agent_visible_text_is_clean():
    assert scan(AGENT_VISIBLE, PATTERNS) == []


def test_app_has_no_raw_names():
    assert scan(["app"], RAW_ONLY) == []


def test_served_text_is_clean():
    # No raw names, labels, benchmark or source names in the API source or the files
    # it serves (the live responses are scanned in tests/test_api.py).
    assert (REPO / "app" / "api.py").is_file()
    assert scan(SERVED, PATTERNS, TEXT_SUFFIXES) == []


@pytest.mark.parametrize("text", [
    "Check for shutdowns and breakdowns.", "Output has its ups and downs.",
    "Reactant-1 feed flow", "Purge gas composition, inert", "The component was replaced.",
    "stream of alerts", "a fault in the cooling loop", "stepwise", "septic",
    "yinyang flow", "a restorer valve", "ding dong",
])
def test_scanner_passes_ordinary_text(text):
    assert find_leaks(text) == []


@pytest.mark.parametrize("text", [
    "Vogel", "Downs and Vogel", "TEP", "the tep data", "Tennessee Eastman", "xmeas_12", "XMV_3",
    "xmeas", "IDV(4)", "idv16", "stream 9", "Stream  11", "component B", "fault 16",
    "Rieth", "Ricker", "Braatz", "Dataverse", "flow in kscmh",
    "Yin et al.", "Haghani", "Russell's code", "Storer", "Chiang", "Lyman", "Georgakis", "Bathelt",
])
def test_scanner_catches_leaks(text):
    assert find_leaks(text)
