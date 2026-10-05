"""web/index.html and web/vercel.json: static checks (the page's text is also leak-scanned
in tests/test_leak_scan.py)."""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = (REPO / "web" / "index.html").read_text()


def test_api_base_is_one_marked_constant_and_local_uses_127():
    assert PAGE.count("const RENDER_API_URL = ") == 1
    assert "Fill this in after the Render deploy" in PAGE
    assert 'LOCAL_HOSTS.includes(location.hostname) ? "http://127.0.0.1:8000" : RENDER_API_URL' in PAGE


def test_says_advisory_and_watch_not_built():
    assert "Advisory only." in PAGE and "never changes plant controls" in PAGE
    assert "Watch band isn't built yet" in PAGE


def test_calls_only_the_read_routes():
    routes = set(re.findall(r'getJSON\([`"](/[a-z/]+)', PAGE))
    assert routes == {"/health", "/replay/info", "/replay/status", "/diagnosis"}
    assert "method:" not in PAGE                     # fetch defaults to GET


def test_no_external_scripts_styles_or_urls():
    assert "<script src" not in PAGE and "<link" not in PAGE
    urls = set(re.findall(r"https?://[^\s\"'`)]+", PAGE))
    assert urls <= {"http://127.0.0.1:8000", "https://plant-health-api.onrender.com"}


def test_never_names_a_run_or_label():
    assert not re.search(r"\b(run|fault)\s*(number|no\.?|#|\d)", PAGE, re.IGNORECASE)


def test_vercel_config_is_static():
    cfg = json.loads((REPO / "web" / "vercel.json").read_text())
    assert not {"builds", "functions", "rewrites"} & set(cfg)


def test_group_panel_is_hidden_until_the_api_reports_groups():
    assert '<section id="groups-panel" class="panel" aria-label="Equipment groups" hidden>' in PAGE
    assert '<span id="legend-watch" hidden>' in PAGE and '<li id="attributed-note" hidden>' in PAGE
    assert "if (state.info.groups) {" in PAGE


def test_watch_and_attribution_wording_is_advisory():
    assert "Watch is an early, silent signal: it doesn't raise an alert." in PAGE
    assert "It shows where the symptoms appear, not what caused them, and it isn't an instruction to act." in PAGE
    # The marker names a symptom location, never a cause, a label or a diagnosis.
    marker = re.search(r'tag\.textContent = "([^"]+)"', PAGE).group(1)
    assert marker == "Symptoms show here first (attributed when the alert began)"
    assert not re.search(r"\b(cause|diagnos\w*|root)\b", marker, re.IGNORECASE)


def test_watch_band_has_a_colour_everywhere_it_is_drawn():
    assert PAGE.count("--watch:") == 3                           # light, dark (media), dark (attribute)
    assert ".pill.Watch" in PAGE and 'Watch: css("--watch")' in PAGE



# ---------- the diagnosis panel (week 6 S9) ----------

def test_the_diagnosis_panel_sits_under_the_group_panel_and_is_hidden_until_ready():
    assert PAGE.index('id="groups-panel"') < PAGE.index('id="diagnosis-panel"') < PAGE.index('aria-label="Replay controls"')
    assert '<section id="diagnosis-panel" class="panel" aria-label="Diagnosis" hidden>' in PAGE
    assert 'if (health.diagnosis === "ready") {' in PAGE


def test_no_free_text_only_the_three_fixed_notes():
    assert "<input" not in PAGE and "<textarea" not in PAGE and "contenteditable" not in PAGE
    notes = re.findall(r'<option value="(none|emergency|injection)"', PAGE)
    assert notes == ["none", "emergency", "injection"]
    from app.agent import demo
    for note in demo.NOTES.values():
        if note:
            assert f'"{note}"' in PAGE                       # the page offers exactly the precomputed notes


def test_says_the_answers_are_precomputed_and_advisory():
    assert "The explanations were computed once, in advance; this page never contacts a language model." in PAGE
    assert "Diagnosis of the alert (advisory)" in PAGE and "Nothing here approves or carries out an action." in PAGE
    assert "needs the supervisor's approval" in PAGE


def test_api_text_is_never_inserted_as_html():
    assert "innerHTML" not in PAGE and "insertAdjacentHTML" not in PAGE and "outerHTML" not in PAGE


# ---------- the episode selector (week 6 S9) ----------

def test_two_fixed_episodes_labelled_by_number_only():
    sel = re.search(r'<select id="episode"[^>]*>(.*?)</select>', PAGE, re.S).group(1)
    options = re.findall(r'<option value="(\d)"[^>]*>([^<]*)</option>', sel)
    assert options == [("1", "Episode 1"), ("2", "Episode 2")]


def test_every_call_names_the_selected_episode():
    calls = re.findall(r"getJSON\(`(/[a-z/]+)\?[^`]*`\)", PAGE)
    assert set(calls) == {"/replay/info", "/replay/status", "/diagnosis"}
    for route in ("/replay/info", "/replay/status", "/diagnosis"):
        for call in re.findall(r"getJSON\(`" + re.escape(route) + r"\?([^`]*)`\)", PAGE):
            assert "episode=${state.episode}" in call, route


def test_the_page_never_describes_an_episode():
    # Labels come from the fixed options; nothing on the page ties an episode to a fault,
    # a family or a mechanism.
    for m in re.finditer(r"Episode \d", PAGE):
        context = PAGE[max(0, m.start() - 80): m.end() + 80].lower()
        assert not re.search(r"fault|mask|cooling|feed|reaction|condenser|kinetic", context)
