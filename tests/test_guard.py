"""The no-network, no-key guard (week 6 S3; decision 76: tests and CI use a fake client and
never call the API). tests/conftest.py applies it to every test; these tests prove it holds.
If one of them fails, the guard is broken and any test could spend money."""

import os
import socket
from pathlib import Path

import pytest

from app.agent import llm
from eval import gemini
from tests.conftest import NetworkBlocked

REPO = Path(__file__).resolve().parents[1]


def test_no_test_sees_the_key():
    assert "GEMINI_API_KEY" not in os.environ


def test_an_outside_connection_is_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkBlocked):
            s.connect(("203.0.113.1", 443))                 # TEST-NET-3: never routable anyway
        with pytest.raises(NetworkBlocked):
            s.connect_ex(("203.0.113.1", 443))
    finally:
        s.close()
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("generativelanguage.googleapis.com", 443))


def test_name_lookups_are_blocked():
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)


def test_loopback_still_works():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()


def test_no_test_reads_dotenv():
    import dotenv
    with pytest.raises(NetworkBlocked):
        dotenv.load_dotenv()
    with pytest.raises(NetworkBlocked):                     # the smoke command's own path
        gemini.main(["--smoke"])


def test_the_real_client_refuses_without_a_key():
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY isn't set"):
        gemini.GeminiClient()


def test_no_test_file_holds_a_key():
    # Real Gemini keys share a fixed four-letter prefix (built below); no test file may hold
    # one, and the only key value a test may set is the obvious placeholder.
    prefix = "AI" + "za"                                   # split, so this file doesn't match itself
    for p in sorted((REPO / "tests").rglob("*.py")):
        assert prefix not in p.read_text(), p.name


def test_dotenv_is_gitignored():
    assert ".env" in (REPO / ".gitignore").read_text().split()