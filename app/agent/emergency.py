"""The emergency screen (decision 78): a deterministic check of the operator note, before the
LLM and before any diagnosis. Runtime code: no imports from dataset/, eval/ or ingest/.

A note that reports an emergency gets EMERGENCY_TEXT and nothing else: no evidence, no
matcher, no LLM call, no diagnosis (PROTOCOL safety set, "Emergency", zero tolerance).

PROPOSED pattern list (Claude, week 6 S8), for Raj's approval before any paid call:
- How it reads a note: lower-cased; every LOOKALIKES phrase is blanked out first; then the
  note trips the screen if any EMERGENCY pattern matches what's left.
- Safety first: a mention trips it even when negated ("no smell of gas") or hedged ("maybe
  smoke"). A false alarm costs one look at the site procedure; a missed emergency is the
  failure that matters. Look-alikes are only phrases whose meaning is never an emergency.
- Bare "gas" doesn't trip it: the plant's own tags say "purge gas" and "feed gas". A gas
  emergency is caught by its smell, leak, release or cloud.

Classes (decision 78): smells, leaks, fire, smoke, explosion, injury, evacuation, plus a few
plain emergency words (emergency, toxic, gas release, vapour cloud, alarm sounding).
"""

import re

EMERGENCY_TEXT = ("This note may describe an emergency. Follow the site emergency procedure now. "
                  "No diagnosis is given.")
MAX_NOTE = 500                       # characters (decision 78)

# Whole-word, case-insensitive. Each class is one pattern, so a test can say which class tripped.
EMERGENCY = {
    "smell": r"\b(?:smell(?:s|ing|ed|y)?|odou?rs?|stench|stink(?:s|ing)?|fumes?|whiff)\b",
    "leak": r"\b(?:leak(?:s|ing|ed|age|y)?|spill(?:s|ed|ing|age)?|spray(?:ing)?|dripping|gushing|venting|"
            r"gas release|release of gas|vapou?r cloud|gas cloud)\b",
    "fire": r"\b(?:fire|fires|flames?|ablaze|burning|on fire|blaze)\b",
    "smoke": r"\b(?:smoke|smoking|smoky|smokey)\b",
    "explosion": r"\b(?:explosion|explosions|exploded|explode|exploding|blast|bang|detonation|rupture[ds]?)\b",
    "injury": r"\b(?:injur(?:y|ies|ed)|hurt|casualt(?:y|ies)|unconscious|collapsed|bleeding|burns?|burnt|"
              r"man down|first aid|ambulance|medic)\b",
    "evacuation": r"\b(?:evacuat(?:e|ed|es|ing|ion)|muster(?:ing)?|get out|clear the area|alarm sounding|sirens?)\b",
    "emergency": r"\b(?:emergency|toxic|poison(?:ous)?|asphyxi\w*|h2s)\b",
}
# Phrases that are never an emergency, blanked out before matching (whole words).
LOOKALIKES = (
    "fired heater", "fired heaters", "gas-fired", "gas fired", "oil-fired", "oil fired",
    "smoke test", "smoke tests", "smoke testing", "smoke detector test", "smoke detector tests",
    "leak test", "leak tests", "leak testing", "leak-tested", "leak tested", "leak check", "leak checks",
    "fire drill", "fire drills", "fire water", "firewater", "fire pump test", "fire alarm test",
    "evacuation drill", "evacuation drills", "muster drill", "muster drills",
    "burner management", "emergency procedure review", "emergency drill",
)
_EMERGENCY = {k: re.compile(p, re.IGNORECASE) for k, p in EMERGENCY.items()}
_LOOKALIKE = re.compile(r"\b(?:" + "|".join(re.escape(x) for x in sorted(LOOKALIKES, key=len, reverse=True))
                        + r")\b", re.IGNORECASE)


def screen(note) -> list:
    """The emergency classes a note trips, in EMERGENCY's order; [] when it trips none (or
    there's no note)."""
    if note is None:
        return []
    if not isinstance(note, str):
        raise TypeError(f"an operator note is text, not {type(note).__name__}")
    rest = _LOOKALIKE.sub(" ", note)
    return [k for k, p in _EMERGENCY.items() if p.search(rest)]


def is_emergency(note) -> bool:
    return bool(screen(note))