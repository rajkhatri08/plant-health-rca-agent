"""requirements-app.txt (the deploy's install list) against requirements.txt and app/."""

import ast
import sys
from importlib import metadata
from pathlib import Path

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parents[1]


def pins(name):
    out = {}
    for line in (REPO / name).read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            pkg, version = line.split("==")
            out[canonicalize_name(pkg)] = version
    return out


APP = pins("requirements-app.txt")
FULL = pins("requirements.txt")


def test_every_app_pin_equals_the_full_pin():
    assert set(APP) <= set(FULL), f"not in requirements.txt: {sorted(set(APP) - set(FULL))}"
    assert {k: v for k, v in APP.items() if FULL[k] != v} == {}


def app_third_party_imports():
    tops = set()
    for p in (REPO / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.Import):
                tops |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and not node.level:
                tops.add(node.module.split(".")[0])
    # Our own top-level packages ship with the repo, not through pip: app/, and shared/
    # (the leak scan app/ and eval/ both use, week 6 S2).
    return {t for t in tops if t not in sys.stdlib_module_names and t not in ("app", "shared")}


def test_app_imports_only_our_shared_package_from_the_repo():
    # app/ may import shared/, never eval/, ingest/ or dataset/ (tests/test_walls.py); and
    # shared/ is a folder in the repo that Render deploys with the code.
    assert (REPO / "shared" / "__init__.py").is_file()


def test_everything_app_imports_is_installed_by_the_deploy():
    dists = metadata.packages_distributions()
    needed = {canonicalize_name(d) for t in app_third_party_imports() for d in dists[t]}
    assert needed <= set(APP), f"missing: {sorted(needed - set(APP))}"
    assert "uvicorn" in APP                       # the start command in render.yaml


def test_the_list_is_closed_under_dependencies():
    # Every runtime dependency (no extras) of every listed package is listed too, so the
    # deploy installs nothing unpinned. Markers are evaluated on this machine; the only
    # platform-marked dependencies in this set are Windows-only.
    missing = set()
    for pkg in APP:
        for r in metadata.distribution(pkg).requires or []:
            req = Requirement(r)
            if req.marker and not req.marker.evaluate({"extra": ""}):
                continue
            if canonicalize_name(req.name) not in APP:
                missing.add(f"{pkg} -> {req.name}")
    assert missing == set()


def test_nothing_extra_is_deployed():
    # No data or test tooling on the server. httpx was listed here as test tooling (the
    # TestClient) until week 6: langgraph-sdk and langsmith need it at runtime now.
    assert not {"pandas", "pyarrow", "pyreadr", "pytest", "matplotlib"} & set(APP)
    # No LLM SDK on the server: the public demo makes no live calls (decision 76).
    assert not {"google-genai", "python-dotenv", "langchain-google-genai"} & set(APP)


def test_the_diagnosis_graph_is_deployed():
    # Week 6 S2: the agent's graph runs in app/ (decision 74).
    assert {"langgraph", "langgraph-checkpoint-sqlite"} <= set(APP)


def test_render_blueprint():
    (svc,) = yaml.safe_load((REPO / "render.yaml").read_text())["services"]
    assert svc["runtime"] == "python" and svc["region"] == "singapore" and svc["plan"] == "free"
    assert svc["buildCommand"] == "pip install -r requirements-app.txt"
    assert svc["startCommand"] == "uvicorn app.api:app --host 0.0.0.0 --port $PORT"
    assert svc["healthCheckPath"] == "/health"
    env = {e["key"]: e for e in svc["envVars"]}
    assert env["PYTHON_VERSION"]["value"] == "3.13"
    assert env["ALLOWED_ORIGIN"]["sync"] is False and "value" not in env["ALLOWED_ORIGIN"]
    assert "DATABASE_URL" not in env and "rootDir" not in svc
