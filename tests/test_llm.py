"""app/agent/llm.py: the provider adapter, cache, replay and budget (decision 76).
Fakes only: no network, no key (tests/test_guard.py)."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.agent import llm

SCHEMA = llm.OutputSchema("t-1", {"type": "object", "properties": {"x": {"type": "integer"}}})


def answer(prompt, schema, repeat):
    return json.dumps({"x": repeat})


@pytest.fixture
def fake():
    return llm.FakeClient(answer)


# ---------- decision 76's values ----------

def test_settings_and_prices_are_decision_76s():
    s = llm.SETTINGS
    assert (s.model_id, s.temperature, s.max_output_tokens, s.thinking_level) == \
        ("gemini-3.1-flash-lite", 0.0, 1024, "minimal")
    p = llm.PRICES["gemini-3.1-flash-lite"]
    assert (p.usd_per_m_input, p.usd_per_m_output, p.read_on) == (Decimal("0.25"), Decimal("1.50"), "2026-10-04")
    assert (llm.USD_INR, llm.USD_INR_ON) == (Decimal("96.33"), "2026-10-04")


def test_the_cache_is_under_gitignored_data():
    assert llm.DEFAULT_CACHE.parts[-2:] == ("data", "llm_cache")


def test_the_adapter_imports_no_provider_sdk():
    import sys
    from tests.test_walls import imported_top_modules
    mods = imported_top_modules(Path(llm.__file__).read_text())
    assert mods <= set(sys.stdlib_module_names), mods


# ---------- the cache key ----------

def test_cache_key_is_the_sha256_of_the_five_parts():
    doc = {"key_version": 1, "model_id": "gemini-3.1-flash-lite", "settings": llm.SETTINGS.as_dict(),
           "schema_version": "t-1", "prompt": "p", "repeat": 2}
    want = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert llm.cache_key(llm.SETTINGS, "t-1", "p", 2) == want


@pytest.mark.parametrize("change", [
    {"settings": llm.Settings("other-model", 0.0, 1024, "minimal")},
    {"settings": llm.Settings("gemini-3.1-flash-lite", 0.5, 1024, "minimal")},
    {"settings": llm.Settings("gemini-3.1-flash-lite", 0.0, 512, "minimal")},
    {"settings": llm.Settings("gemini-3.1-flash-lite", 0.0, 1024, "low")},
    {"schema_version": "t-2"}, {"prompt": "p "}, {"repeat": 1},
])
def test_each_part_changes_the_key(change):
    base = {"settings": llm.SETTINGS, "schema_version": "t-1", "prompt": "p", "repeat": 0}
    assert llm.cache_key(**{**base, **change}) != llm.cache_key(**base)


@pytest.mark.parametrize("repeat", [-1, 1.0, True, "0"])
def test_cache_key_refuses_a_bad_repeat(repeat):
    with pytest.raises(ValueError):
        llm.cache_key(llm.SETTINGS, "t-1", "p", repeat)


# ---------- cost ----------

def test_cost_from_tokens_and_the_dated_prices():
    s = llm.SETTINGS
    assert llm.cost_inr(s, 1_000_000, 0, 0) == Decimal("0.25") * Decimal("96.33")
    assert llm.cost_inr(s, 0, 1_000_000, 0) == Decimal("1.50") * Decimal("96.33")
    assert llm.cost_inr(s, 0, 0, 1_000_000) == llm.cost_inr(s, 0, 1_000_000, 0)     # thinking is output


def test_cost_refuses_an_unpriced_model():
    with pytest.raises(llm.LLMError, match="no price"):
        llm.cost_inr(llm.Settings("unpriced", 0.0, 1024, None), 1, 1, 0)


def test_input_bound_never_undercounts():
    p = "évidence: RX-PI-202 low"
    assert llm.input_bound(p, SCHEMA) >= len(p.encode()) > len(p)


# ---------- the budget ----------

def test_the_meter_stops_before_a_call_that_could_cross_the_cap(fake):
    meter = llm.BudgetMeter(Decimal("0.001"), llm.SETTINGS)          # less than one worst case
    with pytest.raises(llm.BudgetExceeded, match="stops here"):
        llm.MeteredClient(fake, meter).complete("p", SCHEMA, repeat=0)
    assert fake.calls == [] and meter.spent == 0                     # refused before calling


def test_the_meter_charges_actual_tokens_once_per_call(fake):
    meter = llm.BudgetMeter(1, llm.SETTINGS)
    c = llm.MeteredClient(fake, meter)
    r = c.complete("a prompt", SCHEMA, repeat=0)
    once = meter.spent
    assert once == llm.cost_inr(llm.SETTINGS, r.tokens_in, r.tokens_out, r.tokens_thinking) > 0
    assert meter.charge(r) == 0 and meter.spent == once              # the same call again: no charge
    assert list(meter.ledger) == [r.key] and meter.ledger[r.key]["cost_inr"] == str(once)


def test_the_meter_runs_until_the_next_worst_case_would_cross(fake):
    worst = llm.BudgetMeter(1, llm.SETTINGS).worst_case("p", SCHEMA)
    meter = llm.BudgetMeter(worst * 3, llm.SETTINGS)
    c = llm.MeteredClient(fake, meter)
    done = 0
    with pytest.raises(llm.BudgetExceeded):
        for i in range(1000):
            c.complete("p", SCHEMA, repeat=i)
            done += 1
    assert done >= 3 and meter.spent <= meter.cap                    # never over the cap


def test_meter_refusals(fake):
    with pytest.raises(ValueError):
        llm.BudgetMeter(0, llm.SETTINGS)
    with pytest.raises(ValueError, match="other settings"):
        llm.MeteredClient(fake, llm.BudgetMeter(1, llm.Settings("gemini-3.1-flash-lite", 0.0, 1024, "low")))


def test_thinking_tokens_are_charged_as_output():
    meter = llm.BudgetMeter(10, llm.SETTINGS)
    r = llm.MeteredClient(llm.FakeClient(answer, thinking=500), meter).complete("p", SCHEMA, repeat=0)
    assert meter.spent == llm.cost_inr(llm.SETTINGS, r.tokens_in, r.tokens_out + 500, 0)


# ---------- the fake ----------

def test_fake_records_calls_and_raises_scripted_errors():
    f = llm.FakeClient(lambda p, s, r: llm.LLMError("boom") if r else "not json")
    r = f.complete("p", SCHEMA, repeat=0)
    assert r.parsed is None and r.raw == "not json"
    with pytest.raises(llm.LLMError, match="boom"):
        f.complete("p", SCHEMA, repeat=1)
    assert [c["repeat"] for c in f.calls] == [0, 1]


def test_parse_takes_only_a_json_object():
    assert llm.parse('{"a": 1}') == {"a": 1}
    assert llm.parse("[1]") is None and llm.parse("") is None and llm.parse(None) is None


# ---------- the cache ----------

def test_a_rerun_is_free_and_identical(fake, tmp_path):
    c = llm.CachedClient(fake, tmp_path)
    first = c.complete("p", SCHEMA, repeat=0)
    again = c.complete("p", SCHEMA, repeat=0)
    assert len(fake.calls) == 1
    assert not first.cached and again.cached
    assert {**again.as_dict(), "cached": False} == first.as_dict()
    assert (tmp_path / first.key[:2] / f"{first.key}.json").is_file()


def test_each_repeat_is_its_own_call(fake, tmp_path):
    c = llm.CachedClient(fake, tmp_path)
    rs = [c.complete("p", SCHEMA, repeat=i) for i in range(3)]
    assert len(fake.calls) == 3 and len({r.key for r in rs}) == 3
    assert [r.parsed["x"] for r in rs] == [0, 1, 2]


def test_a_cache_hit_costs_nothing_even_with_the_budget_spent(fake, tmp_path):
    meter = llm.BudgetMeter(1, llm.SETTINGS)
    c = llm.CachedClient(llm.MeteredClient(fake, meter), tmp_path)
    c.complete("p", SCHEMA, repeat=0)
    spent = meter.spent
    meter.cap = spent                                                # nothing left
    assert c.complete("p", SCHEMA, repeat=0).cached and meter.spent == spent
    with pytest.raises(llm.BudgetExceeded):
        c.complete("p", SCHEMA, repeat=1)                            # a new call is refused


def test_the_entry_names_no_prompt_text(fake, tmp_path):
    r = llm.CachedClient(fake, tmp_path).complete("secret prompt text", SCHEMA, repeat=0)
    doc = json.loads((tmp_path / r.key[:2] / f"{r.key}.json").read_text())
    assert "secret prompt text" not in json.dumps(doc)
    assert doc["prompt_sha256"] == hashlib.sha256(b"secret prompt text").hexdigest()


def test_an_edited_entry_is_refused(fake, tmp_path):
    c = llm.CachedClient(fake, tmp_path)
    r = c.complete("p", SCHEMA, repeat=0)
    path = tmp_path / r.key[:2] / f"{r.key}.json"
    doc = json.loads(path.read_text())
    doc["repeat"] = 7
    path.write_text(json.dumps(doc))
    with pytest.raises(llm.LLMError, match="doesn't match its key"):
        c.complete("p", SCHEMA, repeat=0)


def test_an_entry_is_never_overwritten(fake, tmp_path):
    store = llm._Store(tmp_path)
    r = fake.complete("p", SCHEMA, repeat=0)
    store.put(r, llm.SETTINGS, SCHEMA.version, "p", 0)
    other = llm.Result(**{**r.as_dict(), "raw": "changed"})
    store.put(other, llm.SETTINGS, SCHEMA.version, "p", 0)
    assert store.get(r.key, llm.SETTINGS, SCHEMA.version, 0).raw == r.raw
    assert not list(tmp_path.rglob("*.tmp"))


def test_a_client_with_other_settings_is_refused(tmp_path):
    class Odd(llm.FakeClient):
        def complete(self, prompt, schema, *, repeat):
            r = super().complete(prompt, schema, repeat=repeat)
            return llm.Result(**{**r.as_dict(), "key": "0" * 64})
    with pytest.raises(llm.LLMError, match="another cache key"):
        llm.CachedClient(Odd(answer), tmp_path).complete("p", SCHEMA, repeat=0)


# ---------- the replay client ----------

def test_replay_serves_precomputed_answers_and_refuses_a_miss(fake, tmp_path):
    llm.CachedClient(fake, tmp_path).complete("p", SCHEMA, repeat=0)
    replay = llm.ReplayClient(tmp_path)
    assert replay.complete("p", SCHEMA, repeat=0).cached
    with pytest.raises(llm.CacheMiss, match="never calls the model"):
        replay.complete("p changed", SCHEMA, repeat=0)
    with pytest.raises(llm.CacheMiss):
        replay.complete("p", llm.OutputSchema("t-2", SCHEMA.json_schema), repeat=0)
    assert len(fake.calls) == 1                                      # the replay called nothing

# ---------- pacing (week 6, after the tuning run's 429s) ----------

class FakeClock:
    """time.monotonic and time.sleep on a counter: sleep advances it, and calls can take time."""

    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def timed_fake(clock, takes=0.5):
    """A FakeClient whose every call takes `takes` seconds on the fake clock, recording its start."""
    starts = []

    def answer(p, s, r):
        starts.append(clock.t)
        clock.t += takes
        return json.dumps({"x": r})
    return llm.FakeClient(answer), starts


def test_paced_calls_start_at_least_min_interval_apart():
    clock = FakeClock()
    fake, starts = timed_fake(clock, takes=0.5)
    c = llm.PacedClient(fake, 2.0, clock=clock.now, sleep=clock.sleep)
    for r in range(3):
        c.complete("p", SCHEMA, repeat=r)
    assert starts == [0.0, 2.0, 4.0]
    assert clock.sleeps == [1.5, 1.5]                       # the call's own 0.5 s counts toward the gap


def test_no_wait_when_calls_are_already_far_enough_apart():
    clock = FakeClock()
    fake, starts = timed_fake(clock, takes=3.0)            # slower than the interval
    c = llm.PacedClient(fake, 2.0, clock=clock.now, sleep=clock.sleep)
    c.complete("p", SCHEMA, repeat=0)
    c.complete("p", SCHEMA, repeat=1)
    assert starts == [0.0, 3.0] and clock.sleeps == []


def test_zero_interval_never_waits():
    clock = FakeClock()
    fake, starts = timed_fake(clock, takes=0.0)
    c = llm.PacedClient(fake, 0, clock=clock.now, sleep=clock.sleep)
    for r in range(3):
        c.complete("p", SCHEMA, repeat=r)
    assert clock.sleeps == [] and starts == [0.0, 0.0, 0.0]


def test_cache_hits_are_not_paced(tmp_path):
    clock = FakeClock()
    fake, starts = timed_fake(clock, takes=0.0)
    c = llm.CachedClient(llm.PacedClient(fake, 5.0, clock=clock.now, sleep=clock.sleep), tmp_path)
    c.complete("p", SCHEMA, repeat=0)
    for _ in range(3):
        assert c.complete("p", SCHEMA, repeat=0).cached      # hits: no wait, no call
    assert clock.sleeps == [] and len(fake.calls) == 1
    c.complete("p", SCHEMA, repeat=1)                         # a real call: paced
    assert clock.sleeps == [5.0] and starts == [0.0, 5.0]


@pytest.mark.parametrize("bad", [-1, "2", True, None])
def test_min_interval_must_be_non_negative_seconds(bad):
    with pytest.raises(ValueError):
        llm.PacedClient(llm.FakeClient(lambda p, s, r: "{}"), bad)
