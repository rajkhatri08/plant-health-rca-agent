"""The leak scan's patterns (eval/LEAKAGE.md, wall 2): one definition for CI
(tests/test_leak_scan.py), the gated approval command (eval/approve_entry.py, through
eval/leak_scan.py) and the agent's tool outputs at runtime (app/agent/tools.py).

It lives outside app/ on purpose: the patterns spell the benchmark's and its sources'
names and the raw tag prefixes, which must never appear in app/ (CLAUDE.md). app/ and
eval/ both import it, so app/ never imports eval/.

find_leaks(text) lists every match of: the benchmark's and its sources' names, raw tag
names and fault labels (XMEAS, XMV, IDV), "stream N", "component A-H" and "fault N".
check(text, where) raises LeakError if there is any.
"""

import re

# Whole words only: "downs" is not listed ("shutdowns", "ups and downs"); "vogel" covers the paper.
WORDS = ["tennessee", "eastman", "vogel", "rieth", "ricker", "braatz", "dataverse", "tep", "kscmh",
         # authors of the control-strategy sources (decision 61)
         "chiang", "lyman", "georgakis", "larsson", "skogestad", "bathelt", "jelali",
         # authors of the other registered sources (eval/sources.yaml; Raj, 2 October 2026).
         # Very short or common ones (Ku, Ding, Hao, Zhang) would false-positive and aren't
         # listed; "downs" isn't either ("ups and downs"). Exact titles are checked in
         # tests/test_sources.py.
         "yin", "haghani", "russell", "storer"]
# `_` is a word character, so a plain \bxmeas\b would miss xmeas_1.
RAW_NAMES = r"\b(?:xmeas|xmv|idv)(?:_?\d+)?\b"
PATTERNS = [
    re.compile(r"\b(?:" + "|".join(WORDS) + r")\b", re.IGNORECASE),
    re.compile(RAW_NAMES, re.IGNORECASE),
    re.compile(r"\bstream\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bcomponent\s+[a-h]\b", re.IGNORECASE),
    re.compile(r"\bfault\s+\d+\b", re.IGNORECASE),
]


class LeakError(ValueError):
    pass


def find_leaks(text, patterns=PATTERNS):
    return [m.group(0) for p in patterns for m in p.finditer(text)]


def check(text, where):
    """Raise LeakError naming where, and the distinct matches, if text leaks anything."""
    leaks = find_leaks(text)
    if leaks:
        raise LeakError(f"{where} would leak {sorted(set(leaks))}; it is withheld")
    return text