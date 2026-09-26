"""Leak scan over agent-visible text (eval/LEAKAGE.md, wall 2)."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Whole words only: "downs" is not listed ("shutdowns", "ups and downs"); "vogel" covers the paper.
WORDS = ["tennessee", "eastman", "vogel", "rieth", "ricker", "braatz", "dataverse", "tep", "kscmh"]
# `_` is a word character, so a plain \bxmeas\b would miss xmeas_1.
RAW_NAMES = r"\b(?:xmeas|xmv|idv)(?:_?\d+)?\b"
PATTERNS = [
    re.compile(r"\b(?:" + "|".join(WORDS) + r")\b", re.IGNORECASE),
    re.compile(RAW_NAMES, re.IGNORECASE),
    re.compile(r"\bstream\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bcomponent\s+[a-h]\b", re.IGNORECASE),
    re.compile(r"\bfault\s+\d+\b", re.IGNORECASE),
]
RAW_ONLY = [re.compile(r"(?:xmeas|xmv)", re.IGNORECASE)]

AGENT_VISIBLE = ["library", "app/agent/prompts"]


def find_leaks(text, patterns=PATTERNS):
    return [m.group(0) for p in patterns for m in p.finditer(text)]


def scan(dirs, patterns):
    hits = []
    for d in dirs:
        root = REPO / d
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            hits += [f"{path.relative_to(REPO)}: {h}" for h in find_leaks(text, patterns)]
    return hits


def test_agent_visible_text_is_clean():
    assert scan(AGENT_VISIBLE, PATTERNS) == []


def test_app_has_no_raw_names():
    assert scan(["app"], RAW_ONLY) == []


@pytest.mark.parametrize("text", [
    "Check for shutdowns and breakdowns.", "Output has its ups and downs.",
    "Reactant-1 feed flow", "Purge gas composition, inert", "The component was replaced.",
    "stream of alerts", "a fault in the cooling loop", "stepwise", "septic",
])
def test_scanner_passes_ordinary_text(text):
    assert find_leaks(text) == []


@pytest.mark.parametrize("text", [
    "Vogel", "Downs and Vogel", "TEP", "the tep data", "Tennessee Eastman", "xmeas_12", "XMV_3",
    "xmeas", "IDV(4)", "idv16", "stream 9", "Stream  11", "component B", "fault 16",
    "Rieth", "Ricker", "Braatz", "Dataverse", "flow in kscmh",
])
def test_scanner_catches_leaks(text):
    assert find_leaks(text)
