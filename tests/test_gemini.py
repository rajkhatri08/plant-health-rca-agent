"""eval/gemini.py: the Gemini provider behind the adapter, on a fake SDK (the real
google.genai.types build the request offline; the client and errors are fakes). No network,
and no real key: the only key value set here is an obvious placeholder."""

import json
from types import SimpleNamespace

import pytest
from google.genai import types

from app.agent import llm
from eval import gemini
from shared.leak_scan import find_leaks

PLACEHOLDER = "placeholder-not-a-real-key"
SCHEMA = llm.OutputSchema("t-1", {"type": "object", "properties": {"ok": {"type": "boolean"}}})


class APIError(Exception):
    def __init__(self, code):
        super().__init__(f"status {code}: request echo with {PLACEHOLDER}")
        self.code, self.status = code, "ERR"


class ConnectError(Exception):          # named like httpx's
    pass


def response(text='{"ok": true}', prompt=12, out=4, thoughts=3, version="gemini-3.1-flash-lite-001"):
    return SimpleNamespace(text=text, model_version=version, usage_metadata=SimpleNamespace(
        prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts))


class FakeSDK:
    """genai with a scripted generate_content: each item is a response or an exception."""

    def __init__(self, script):
        self.script, self.calls, self.made = list(script), [], []
        sdk = self

        class Client:
            def __init__(self, *, api_key, http_options):
                sdk.made.append({"api_key": api_key, "http_options": http_options})
                self.models = SimpleNamespace(generate_content=sdk.generate)
        self.genai = SimpleNamespace(Client=Client)
        self.errors = SimpleNamespace(APIError=APIError)

    def generate(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def triple(self):
        return self.genai, self.errors, types


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv(gemini.KEY_VAR, PLACEHOLDER)


def client(sdk, sleeps=None):
    return gemini.GeminiClient(sdk=sdk.triple(), sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_a_missing_key_is_refused_before_the_sdk_is_touched():
    sdk = FakeSDK([])
    with pytest.raises(llm.LLMError, match="isn't set"):
        gemini.GeminiClient(sdk=sdk.triple())
    assert sdk.made == []


def test_the_request_carries_decision_76s_settings(keyed):
    sdk = FakeSDK([response()])
    r = client(sdk).complete("prompt", SCHEMA, repeat=0)
    (call,) = sdk.calls
    cfg = call["config"]
    assert call["model"] == "gemini-3.1-flash-lite" and call["contents"] == "prompt"
    assert cfg.temperature == 0.0 and cfg.max_output_tokens == 1024
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == SCHEMA.json_schema
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert sdk.made[0]["http_options"].retry_options.attempts == 1      # the SDK's retries are off
    assert r.key == llm.cache_key(llm.SETTINGS, "t-1", "prompt", 0)


def test_tokens_thinking_and_version_are_reported(keyed):
    r = client(FakeSDK([response(prompt=40, out=9, thoughts=5)])).complete("p", SCHEMA, repeat=0)
    assert (r.tokens_in, r.tokens_out, r.tokens_thinking) == (40, 9, 5)
    assert r.model_version == "gemini-3.1-flash-lite-001" and r.parsed == {"ok": True}


def test_missing_usage_counts_read_as_zero(keyed):
    resp = SimpleNamespace(text="{}", model_version=None,
                           usage_metadata=SimpleNamespace(prompt_token_count=3, candidates_token_count=None,
                                                          thoughts_token_count=None))
    r = client(FakeSDK([resp])).complete("p", SCHEMA, repeat=0)
    assert (r.tokens_in, r.tokens_out, r.tokens_thinking) == (3, 0, 0)


def test_the_key_never_shows(keyed):
    c = client(FakeSDK([response(), APIError(400)]))
    r = c.complete("p", SCHEMA, repeat=0)
    assert PLACEHOLDER not in repr(c) and PLACEHOLDER not in json.dumps(r.as_dict())
    assert PLACEHOLDER not in json.dumps({k: str(v) for k, v in vars(c).items() if k != "_client"})
    with pytest.raises(llm.LLMError) as e:
        c.complete("p", SCHEMA, repeat=1)
    assert PLACEHOLDER not in str(e.value) and "400" in str(e.value)


def test_a_server_error_is_retried_twice_with_backoff(keyed):
    sdk, sleeps = FakeSDK([APIError(503), APIError(429), response()]), []
    r = client(sdk, sleeps).complete("p", SCHEMA, repeat=0)
    assert len(sdk.calls) == 3 and sleeps == [1.0, 2.0] and r.parsed == {"ok": True}


def test_three_failures_raise(keyed):
    sdk, sleeps = FakeSDK([APIError(500), ConnectError(), APIError(502)]), []
    with pytest.raises(llm.LLMError, match="failed 3 times"):
        client(sdk, sleeps).complete("p", SCHEMA, repeat=0)
    assert len(sdk.calls) == 3 and sleeps == [1.0, 2.0]


def test_a_bad_request_is_not_retried(keyed):
    sdk, sleeps = FakeSDK([APIError(400)]), []
    with pytest.raises(llm.LLMError, match="refused"):
        client(sdk, sleeps).complete("p", SCHEMA, repeat=0)
    assert len(sdk.calls) == 1 and sleeps == []


def test_no_thinking_config_when_the_level_is_none(keyed):
    sdk = FakeSDK([response()])
    s = llm.Settings("gemini-3.1-flash-lite", 0.0, 1024, None)
    gemini.GeminiClient(s, sdk=sdk.triple()).complete("p", SCHEMA, repeat=0)
    assert sdk.calls[0]["config"].thinking_config is None


# ---------- the smoke command ----------

def test_smoke_reports_and_stays_under_its_cap():
    lines = []
    fake = llm.FakeClient(lambda p, s, r: '{"ok": true}')
    r, meter = gemini.smoke(client=fake, out=lines.append)
    assert len(fake.calls) == 1 and r.parsed == {"ok": True}
    assert meter.spent <= meter.cap == 1
    text = "\n".join(lines)
    assert "gemini-3.1-flash-lite" in text and "thinking level minimal" in text and "cost Rs" in text


def test_smoke_with_the_low_level():
    fake = llm.FakeClient(lambda p, s, r: '{"ok": true}',
                          settings=llm.Settings("gemini-3.1-flash-lite", 0.0, 1024, "low"))
    _, meter = gemini.smoke("low", client=fake, out=lambda s: None)
    assert meter.settings.thinking_level == "low"


def test_the_smoke_prompt_names_nothing_of_the_plant():
    import re
    text = gemini.SMOKE_PROMPT + json.dumps(gemini.SMOKE_SCHEMA.json_schema)
    assert find_leaks(text) == [] and not re.search(r"\b[A-Z]{2}-[A-Z]{2,3}-\d{3}\b", text)


def test_main_without_smoke_does_nothing():
    assert gemini.main([]) == 2