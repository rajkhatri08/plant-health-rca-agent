"""docs/entry_template.yaml stays a valid revision, so it can't drift from the schema."""

from pathlib import Path

import yaml

from app.library import schema
from tests.test_leak_scan import find_leaks

REPO = Path(__file__).resolve().parents[1]
TEXT = (REPO / "docs" / "entry_template.yaml").read_text()


def test_template_validates():
    rev = schema.Revision.model_validate(yaml.safe_load(TEXT))
    assert rev.revision == 1 and rev.governance.supersedes is None
    assert rev.iso14224.failure_mechanism == "unverified"
    assert rev.signature.provisional.tags["RX-PI-202"].one_of == ("high", "low")     # shows one_of


def test_template_is_clean_and_outside_the_library():
    assert find_leaks(TEXT) == []
    assert not list((REPO / "library").rglob("entry_template*"))
