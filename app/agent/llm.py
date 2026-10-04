"""The provider adapter: one interface for every LLM call (decisions 75, 76).

Runtime code: no imports from dataset/, eval/ or ingest/, and no provider SDK. The real
provider (eval/gemini.py, google-genai) lives on the builder side, because the deployed
API makes no live LLM calls (decision 76) and so never installs an SDK. The demo uses
ReplayClient, which only reads answers precomputed into a cache.

A client has `settings` (Settings) and `complete(prompt, schema, *, repeat) -> Result`.
- schema is an OutputSchema: a version string and the JSON schema the answer must follow.
- repeat is the repeat index (0..R-1). It's part of the cache key, so each repeat is one
  real call and a rerun of the same repeat is free (decision 76).

Clients:
- FakeClient        scripted answers, for tests and CI; never touches the network
- CachedClient      wraps a client; answers from data/llm_cache/ when it can, otherwise
                    calls the client and stores the answer. Never overwrites an entry.
- ReplayClient      cache only; a miss raises CacheMiss (the demo: a changed prompt fails
                    loudly instead of calling anything)
- MeteredClient     wraps the real client with a BudgetMeter: the worst case is checked
                    before each call, and the actual cost is charged after it

The cache key is the SHA-256 of the model ID, the settings, the schema version, the prompt
text and the repeat index (decision 76), as canonical JSON.

Costs are in rupees, as Decimal, from token counts x the price table (decision 76: prices
read on 4 October 2026, INR 96.33 per USD). Thinking tokens are billed as output.
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = REPO_ROOT / "data" / "llm_cache"          # gitignored (data/)
KEY_VERSION = 1                                           # the layout of the key's JSON


class LLMError(RuntimeError):
    """A call that gave no answer (an API error after its retries, or a refusal)."""


class CacheMiss(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


# ---------- settings, prices, schema, result ----------

@dataclass(frozen=True)
class Settings:
    model_id: str
    temperature: float
    max_output_tokens: int
    thinking_level: str | None           # e.g. "minimal"; decision 76 records the accepted value

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Price:
    usd_per_m_input: Decimal
    usd_per_m_output: Decimal            # output includes thinking tokens
    read_on: str
    source: str


# Decision 76. The thinking level is the one the S3 smoke call tries first; decision 76
# records the value the API accepts before any evaluation call.
SETTINGS = Settings(model_id="gemini-3.1-flash-lite", temperature=0.0, max_output_tokens=1024,
                    thinking_level="minimal")
PRICES = {"gemini-3.1-flash-lite": Price(Decimal("0.25"), Decimal("1.50"), "2026-10-04",
                                         "ai.google.dev/gemini-api/docs/pricing")}
USD_INR = Decimal("96.33")
USD_INR_ON = "2026-10-04"


@dataclass(frozen=True)
class OutputSchema:
    version: str                         # bumped whenever json_schema changes
    json_schema: dict = field(hash=False, compare=False)


@dataclass(frozen=True)
class Result:
    key: str
    raw: str                             # the answer's text, as returned
    parsed: dict | None                  # raw as a JSON object, or None if it isn't one
    tokens_in: int
    tokens_out: int                      # visible output, without thinking
    tokens_thinking: int
    latency_ms: float
    model_version: str | None            # what the API reports serving
    cached: bool = False

    def as_dict(self):
        return asdict(self)


def parse(raw):
    """raw as a JSON object, or None. Checking it against the schema is the caller's job."""
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def cache_key(settings, schema_version, prompt, repeat) -> str:
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 0:
        raise ValueError(f"repeat must be a non-negative integer, got {repeat!r}")
    doc = {"key_version": KEY_VERSION, "model_id": settings.model_id, "settings": settings.as_dict(),
           "schema_version": schema_version, "prompt": prompt, "repeat": repeat}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def cost_inr(settings, tokens_in, tokens_out, tokens_thinking, prices=PRICES, usd_inr=USD_INR) -> Decimal:
    try:
        p = prices[settings.model_id]
    except KeyError:
        raise LLMError(f"no price for {settings.model_id}; add it with its date first") from None
    usd = (Decimal(tokens_in) * p.usd_per_m_input
           + Decimal(tokens_out + tokens_thinking) * p.usd_per_m_output) / Decimal(1_000_000)
    return usd * usd_inr


# ---------- the budget ----------

def input_bound(prompt, schema) -> int:
    """An upper bound on the call's input tokens, known before the call: the UTF-8 bytes of
    the prompt and the schema. A token is at least one byte of text, so this never
    undercounts; it overcounts several times, which only matters for the last call before
    the cap."""
    return len(prompt.encode()) + len(json.dumps(schema.json_schema, sort_keys=True).encode())


class BudgetMeter:
    """A hard cap in rupees for one run (decision 76). check() before each real call with its
    worst case (the input bound plus max_output_tokens, all at the output price for thinking
    and output); charge() after it with the actual tokens. The ledger is keyed by call (the
    cache key), so charging the same call twice counts once."""

    def __init__(self, cap_inr, settings, prices=PRICES, usd_inr=USD_INR):
        self.cap = Decimal(str(cap_inr))
        if self.cap <= 0:
            raise ValueError("the budget cap must be > 0 rupees")
        self.settings, self.prices, self.usd_inr = settings, prices, usd_inr
        self.ledger = {}                                  # {key: {"tokens_in", ..., "cost_inr"}}

    @property
    def spent(self) -> Decimal:
        return sum((Decimal(e["cost_inr"]) for e in self.ledger.values()), Decimal(0))

    def worst_case(self, prompt, schema) -> Decimal:
        return cost_inr(self.settings, input_bound(prompt, schema), self.settings.max_output_tokens, 0,
                        self.prices, self.usd_inr)

    def check(self, prompt, schema):
        worst = self.worst_case(prompt, schema)
        if self.spent + worst > self.cap:
            raise BudgetExceeded(f"the next call could cost up to Rs {worst:.4f}; Rs {self.spent:.4f} of "
                                 f"Rs {self.cap} is spent, so the run stops here")
        return worst

    def charge(self, result) -> Decimal:
        if result.key in self.ledger:
            return Decimal(0)                             # already counted
        c = cost_inr(self.settings, result.tokens_in, result.tokens_out, result.tokens_thinking,
                     self.prices, self.usd_inr)
        self.ledger[result.key] = {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                                   "tokens_thinking": result.tokens_thinking, "cost_inr": str(c)}
        return c


class MeteredClient:
    """The real client behind a BudgetMeter: check, call, charge."""

    def __init__(self, inner, meter):
        if inner.settings != meter.settings:
            raise ValueError("the meter prices other settings than the client uses")
        self.inner, self.meter, self.settings = inner, meter, inner.settings

    def complete(self, prompt, schema, *, repeat):
        self.meter.check(prompt, schema)
        result = self.inner.complete(prompt, schema, repeat=repeat)
        self.meter.charge(result)
        return result


# ---------- clients ----------

class FakeClient:
    """Scripted answers for tests. answer is a function (prompt, schema, repeat) -> raw text
    or an Exception to raise; tokens are made up from the text's length. Records each call."""

    def __init__(self, answer, settings=SETTINGS, *, thinking=0):
        self.answer, self.settings, self.thinking = answer, settings, thinking
        self.calls = []

    def complete(self, prompt, schema, *, repeat):
        key = cache_key(self.settings, schema.version, prompt, repeat)
        self.calls.append({"prompt": prompt, "schema_version": schema.version, "repeat": repeat, "key": key})
        raw = self.answer(prompt, schema, repeat)
        if isinstance(raw, Exception):
            raise raw
        return Result(key=key, raw=raw, parsed=parse(raw), tokens_in=max(1, len(prompt) // 4),
                      tokens_out=max(1, len(raw) // 4), tokens_thinking=self.thinking, latency_ms=0.0,
                      model_version="fake")


class _Store:
    """data/llm_cache/<key[:2]>/<key>.json, one answer per file, never overwritten."""

    def __init__(self, root):
        self.root = Path(root)

    def path(self, key):
        return self.root / key[:2] / f"{key}.json"

    def get(self, key, settings, schema_version, repeat):
        p = self.path(key)
        if not p.is_file():
            return None
        doc = json.loads(p.read_text())
        if (doc.get("key"), doc.get("settings"), doc.get("schema_version"), doc.get("repeat")) != \
                (key, settings.as_dict(), schema_version, repeat):
            raise LLMError(f"cache entry {p} doesn't match its key; it was edited or misplaced")
        return Result(**{**doc["result"], "cached": True})

    def put(self, result, settings, schema_version, prompt, repeat):
        p = self.path(result.key)
        p.parent.mkdir(parents=True, exist_ok=True)
        doc = {"key": result.key, "settings": settings.as_dict(), "schema_version": schema_version,
               "repeat": repeat, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
               "stored_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "result": {**result.as_dict(), "cached": False}}
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        try:
            tmp.rename(p) if not p.exists() else None     # never overwrite an answer
        finally:
            tmp.unlink(missing_ok=True)


class CachedClient:
    """Answers from the cache when it can; otherwise calls inner and stores the answer."""

    def __init__(self, inner, root=DEFAULT_CACHE):
        self.inner, self.settings, self.store = inner, inner.settings, _Store(root)

    def complete(self, prompt, schema, *, repeat):
        key = cache_key(self.settings, schema.version, prompt, repeat)
        hit = self.store.get(key, self.settings, schema.version, repeat)
        if hit is not None:
            return hit
        result = self.inner.complete(prompt, schema, repeat=repeat)
        if result.key != key:
            raise LLMError("the client computed another cache key; its settings differ")
        self.store.put(result, self.settings, schema.version, prompt, repeat)
        return result


class ReplayClient:
    """Cache only: the demo's client. A miss raises CacheMiss; nothing is ever called."""

    def __init__(self, root, settings=SETTINGS):
        self.settings, self.store = settings, _Store(root)

    def complete(self, prompt, schema, *, repeat):
        key = cache_key(self.settings, schema.version, prompt, repeat)
        hit = self.store.get(key, self.settings, schema.version, repeat)
        if hit is None:
            raise CacheMiss(f"no precomputed answer for this prompt (key {key[:12]}…); the demo never "
                            "calls the model, so the prompt must match a precomputed one")
        return hit


def timed(fn):
    """(value, milliseconds) for fn()."""
    t0 = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - t0) * 1000.0