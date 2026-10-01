"""eval/sources.yaml: opaque IDs, and no title, author or link ever in library/ (decision 67)."""

import re
from pathlib import Path

import yaml

from app.library import schema
from eval import approve_entry

REPO = Path(__file__).resolve().parents[1]
ROWS = yaml.safe_load((REPO / "eval" / "sources.yaml").read_text())["sources"]


def test_ids_are_unique_opaque_and_in_order():
    ids = [r["id"] for r in ROWS]
    assert all(schema.SOURCE_ID.match(i) for i in ids)
    assert ids == [f"src-{n:03d}" for n in range(1, len(ids) + 1)]       # never renumbered or reused
    assert approve_entry.load_sources(REPO / "eval" / "sources.yaml") == set(ids)


def test_every_source_has_a_title_role_and_licence():
    for r in ROWS:
        assert set(r) == {"id", "title", "role", "licence", "cited"} and all(str(v).strip() for v in r.values())


def test_no_title_author_or_link_reaches_the_library():
    library = "\n".join(p.read_text() for p in (REPO / "library").rglob("*.yaml")).lower()
    for r in ROWS:
        assert r["title"].lower() not in library
        for link in re.findall(r"(?:https?://\S+|doi:\S+)", r["title"]):
            assert link.lower().rstrip(",") not in library


def test_the_register_is_builder_side():
    assert not (REPO / "library" / "sources.yaml").exists()
