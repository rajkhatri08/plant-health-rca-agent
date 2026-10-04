"""The leak scan's patterns, re-exported from shared/leak_scan.py (one definition for CI,
the gated approval command and the agent's tool outputs at runtime). Kept so
eval/approve_entry.py and the tests import it unchanged.
"""

from shared.leak_scan import PATTERNS, RAW_NAMES, WORDS, LeakError, check, find_leaks  # noqa: F401