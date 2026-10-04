"""The Gemini provider behind the adapter (decision 76), and the smoke command.

    python -m eval.gemini --smoke [--thinking-level minimal|low]

Builder side: evaluation and the demo's precompute call the model; the deployed API never
does, so google-genai is in requirements.txt only (never requirements-app.txt), and
app/agent/llm.py holds everything provider-neutral.

GeminiClient:
- google-genai is imported when a GeminiClient is made, never at module import, so
  importing this module (as the tests do) needs no SDK and no key.
- The key comes from GEMINI_API_KEY in the environment. It's passed to the SDK and never
  stored, printed, logged or put in a result. A missing key is refused before anything
  else happens.
- Settings are decision 76's: temperature 0, max output tokens 1024, structured output
  (JSON against the schema), and the thinking level (minimal, accepted in the smoke call).
  Every request disables the SDK's automatic function calling and sends no tools.
- Errors: the SDK's own retries are off, so every attempt is ours to count. A rate limit
  (429), a server error (5xx) or a transport error is retried up to RETRIES = 2 times with
  backoff (1 s, then 2 s), then raised as LLMError. Any other client error (4xx, for example
  a refused thinking level) is raised at once: retrying a bad request can't help.
- Thinking tokens are reported separately and billed as output (app/agent/llm.cost_inr).

The smoke command reads .env (python-dotenv, without overriding the environment), makes one
call with a neutral prompt that names no plant, tag or entry, under a Rs 1 cap, and prints
the model version, token counts, cost and latency. It's the only thing here that spends
money, and Raj runs it.
"""

import argparse
import os
import sys
import time

from app.agent import llm

KEY_VAR = "GEMINI_API_KEY"
RETRIES = 2
BACKOFF_S = (1.0, 2.0)
RETRY_STATUS = {429} | set(range(500, 600))
SMOKE_CAP_INR = 1
SMOKE_SCHEMA = llm.OutputSchema("smoke-1", {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                            "required": ["ok"]})
SMOKE_PROMPT = 'Reply with the JSON object {"ok": true} and nothing else.'


class GeminiClient:
    def __init__(self, settings=llm.SETTINGS, *, sleep=time.sleep, sdk=None):
        key = os.environ.get(KEY_VAR)
        if not key:
            raise llm.LLMError(f"{KEY_VAR} isn't set; put it in the gitignored .env (never in the repo)")
        if sdk is None:
            from google import genai                    # only here: the deployed API never gets here
            from google.genai import errors, types
        else:
            genai, errors, types = sdk                  # tests pass fakes; nothing is imported
        self.settings, self._sleep, self._errors, self._types = settings, sleep, errors, types
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1)))     # our retries only

    def __repr__(self):
        return f"GeminiClient({self.settings.model_id})"           # never the key

    def _config(self, schema):
        t, s = self._types, self.settings
        thinking = (t.ThinkingConfig(thinking_level=s.thinking_level.upper())
                    if s.thinking_level else None)
        return t.GenerateContentConfig(
            temperature=s.temperature, max_output_tokens=s.max_output_tokens,
            response_mime_type="application/json", response_json_schema=schema.json_schema,
            thinking_config=thinking,
            # Decision 76: the SDK must never call a function on its own, and no tools are sent.
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True), tools=None)

    def _retryable(self, e):
        if isinstance(e, self._errors.APIError):
            return getattr(e, "code", None) in RETRY_STATUS
        return isinstance(e, (ConnectionError, TimeoutError, OSError)) or type(e).__name__ in (
            "ConnectError", "ReadTimeout", "ConnectTimeout", "RemoteProtocolError", "ReadError")

    def complete(self, prompt, schema, *, repeat):
        key = llm.cache_key(self.settings, schema.version, prompt, repeat)
        config = self._config(schema)
        for attempt in range(RETRIES + 1):
            try:
                response, ms = llm.timed(lambda: self._client.models.generate_content(
                    model=self.settings.model_id, contents=prompt, config=config))
                break
            except Exception as e:                      # noqa: BLE001 (classified just below)
                if not self._retryable(e):
                    raise llm.LLMError(f"the API refused the call: {_describe(e)}") from None
                if attempt == RETRIES:
                    raise llm.LLMError(f"the API failed {RETRIES + 1} times: {_describe(e)}") from None
                self._sleep(BACKOFF_S[attempt])
        usage = response.usage_metadata
        raw = response.text or ""
        return llm.Result(key=key, raw=raw, parsed=llm.parse(raw),
                          tokens_in=int(getattr(usage, "prompt_token_count", 0) or 0),
                          tokens_out=int(getattr(usage, "candidates_token_count", 0) or 0),
                          tokens_thinking=int(getattr(usage, "thoughts_token_count", 0) or 0),
                          latency_ms=ms, model_version=getattr(response, "model_version", None))


def _describe(e):
    """The error's class and status, never its full text (which could echo a request)."""
    code = getattr(e, "code", None)
    status = getattr(e, "status", None)
    return f"{type(e).__name__}" + (f" {code}" if code is not None else "") + (f" {status}" if status else "")


def smoke(thinking_level=None, *, client=None, out=print):
    settings = llm.SETTINGS if thinking_level is None else llm.Settings(
        llm.SETTINGS.model_id, llm.SETTINGS.temperature, llm.SETTINGS.max_output_tokens, thinking_level)
    meter = llm.BudgetMeter(SMOKE_CAP_INR, settings)
    c = llm.MeteredClient(client or GeminiClient(settings), meter)
    r = c.complete(SMOKE_PROMPT, SMOKE_SCHEMA, repeat=0)
    out(f"model {settings.model_id} (served: {r.model_version}); temperature {settings.temperature}; "
        f"thinking level {settings.thinking_level}; max output tokens {settings.max_output_tokens}")
    out(f"tokens: input {r.tokens_in}, output {r.tokens_out}, thinking {r.tokens_thinking}; "
        f"cost Rs {meter.spent:.5f} (prices read {llm.PRICES[settings.model_id].read_on}, "
        f"INR {llm.USD_INR} per USD on {llm.USD_INR_ON}); latency {r.latency_ms:.0f} ms")
    out(f"answer parsed as JSON: {r.parsed is not None}; ok = {(r.parsed or {}).get('ok')}")
    return r, meter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--smoke", action="store_true", help="one paid call (about Rs 0.01), Raj runs it")
    parser.add_argument("--thinking-level", choices=["minimal", "low"], default=None,
                        help="default: decision 76's setting (minimal)")
    args = parser.parse_args(argv)
    if not args.smoke:
        parser.print_help()
        return 2
    from dotenv import load_dotenv                       # only the command line reads .env
    load_dotenv(override=False)
    try:
        smoke(args.thinking_level)
    except llm.LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())