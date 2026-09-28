import os
import json
import requests
from datetime import date
from dotenv import load_dotenv
load_dotenv()

# ---- Tool 1: External Tool (OpenEphemeris) ----

OPENEPHEMERIS_API_KEY = os.environ.get("OPENEPHEMERIS_API_KEY")

if not OPENEPHEMERIS_API_KEY:
    raise RuntimeError(
        "Missing OPENEPHEMERIS_API_KEY. Set it in a .env file or your "
        "environment before starting the server."
    )

OPENEPHEMERIS_URL = "https://api.openephemeris.com/ephemeris/natal-chart"

# The API returns dozens of asteroids; only pass along the bodies astrology
# advice actually uses so the model gets a compact, relevant result.
MAIN_BODIES = [
    "Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
    "Uranus", "Neptune", "Pluto", "Chiron", "North Node (True)",
]


def get_current_transits(target_date: str = None) -> dict:
    """Calls the OpenEphemeris API for current planetary positions.

    We reuse the natal-chart endpoint by treating the target date (default:
    today) as the subject's birth moment. A planet's zodiac sign, degree, and
    retrograde status don't depend on observer location, so a fixed
    placeholder location (0,0 / UTC) is used.

    Returns a dict with either 'transits' (on success) or 'error' (on
    failure), the latter containing an actionable message the model can
    relay to the user or use to retry/adjust.
    """
    target_date = target_date or date.today().isoformat()

    payload = {
        "subject": {
            "name": "current-transits-snapshot",
            "birth_datetime": {"iso": f"{target_date}T12:00:00"},
            "birth_location": {
                "latitude": {"decimal": 0.0},
                "longitude": {"decimal": 0.0},
                "timezone": {"iana_name": "UTC"},
            },
        }
    }

    try:
        resp = requests.post(
            OPENEPHEMERIS_URL,
            headers={
                "X-OpenEphemeris-API-Key": OPENEPHEMERIS_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return {"error": "The astrology data provider timed out. Try again in a moment."}
    except requests.exceptions.HTTPError as e:
        body_preview = ""
        try:
            body_preview = e.response.text[:300]
        except Exception:
            pass
        return {"error": f"OpenEphemeris rejected the request ({e.response.status_code}). "
                          f"Check that target_date is a real date formatted YYYY-MM-DD "
                          f"and the API key is valid. Response: {body_preview}"}
    except requests.exceptions.RequestException:
        return {"error": "Could not reach OpenEphemeris. Check network/API key config."}
    except ValueError:
        return {"error": "OpenEphemeris returned a response that wasn't valid JSON. Try again."}

    # `planets` is a dict keyed by planet name, not a list.
    planets = data.get("planets")
    if not isinstance(planets, dict) or not planets:
        return {"error": "OpenEphemeris responded but contained no planet data. "
                          "Try again, or try a different target_date."}

    transits = []
    for name in MAIN_BODIES:
        p = planets.get(name)
        if p is None:
            continue
        transits.append({
            "planet": p.get("name", name),
            "sign": p.get("sign_name"),
            "degree": round(p.get("sign_longitude", 0), 1),  # degrees within the sign (0-30)
            "retrograde": bool(p.get("is_retrograde", False)),
        })

    return {"date": target_date, "transits": transits}


if __name__ == "__main__":
    print(json.dumps(get_current_transits(), indent=2))

TRANSITS_SCHEMA =     {
        "type": "function",
        "function": {
            "name": "get_current_transits",
            "description": (
                "Fetches the real current positions of the Sun, Moon, and planets "
                "(zodiac sign, degree, and whether retrograde) for a given date. "
                "Use this whenever the user asks what's happening in the sky right now, "
                "whether a planet is retrograde, or as grounding data before giving "
                "horoscope-style or decision-timing advice. Never guess planetary "
                "positions yourself — always call this tool first to get real data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_date": {
                        "type": "string",
                        "description": (
                            "Date to check, in YYYY-MM-DD format. Defaults to today "
                            "if not provided."
                        ),
                    },
                },
                "required": [],
            },
        },
    }

# Tool 2: Original Tool 1
COMPATIBILITY_SCHEMA = {
    "name": "compatibility_score",
    "description": (
        "Scores compatibility between two zodiac signs using elemental "
        "(fire/earth/air/water) and modality (cardinal/fixed/mutable) "
        "relationships — not a vague LLM opinion, an actual weighted rubric. "
        "Use this when the user asks how compatible they are with someone, "
        "specifying context (romantic, friendship, roommates, coworkers) since "
        "scoring weights differ by context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sign_a": {"type": "string", "description": "First zodiac sign, e.g. 'Leo'."},
            "sign_b": {"type": "string", "description": "Second zodiac sign, e.g. 'Aquarius'."},
            "context": {
                "type": "string",
                "enum": ["romantic", "friendship", "roommates", "coworkers"],
                "description": "The relationship context, which changes scoring weights.",
            },
        },
        "required": ["sign_a", "sign_b", "context"],
    },
}

ELEMENTS = {
    "Aries": "fire", "Leo": "fire", "Sagittarius": "fire",
    "Taurus": "earth", "Virgo": "earth", "Capricorn": "earth",
    "Gemini": "air", "Libra": "air", "Aquarius": "air",
    "Cancer": "water", "Scorpio": "water", "Pisces": "water",
}
MODALITIES = {
    "Aries": "cardinal", "Cancer": "cardinal", "Libra": "cardinal", "Capricorn": "cardinal",
    "Taurus": "fixed", "Leo": "fixed", "Scorpio": "fixed", "Aquarius": "fixed",
    "Gemini": "mutable", "Virgo": "mutable", "Sagittarius": "mutable", "Pisces": "mutable",
}
ELEMENT_AFFINITY = {  # symmetric compatibility scores 0-10 between elements
    ("fire", "fire"): 7, ("fire", "air"): 9, ("fire", "earth"): 4, ("fire", "water"): 3,
    ("earth", "earth"): 7, ("earth", "water"): 9, ("earth", "air"): 4,
    ("air", "air"): 7, ("air", "water"): 4,
    ("water", "water"): 8,
}
# context-specific weighting: (element_weight, modality_weight)
CONTEXT_WEIGHTS = {
    "romantic": (0.7, 0.3),
    "friendship": (0.5, 0.5),
    "roommates": (0.3, 0.7),   # modality (routine/stability) matters more for living together
    "coworkers": (0.4, 0.6),
}

def _affinity(e1, e2):
    return ELEMENT_AFFINITY.get((e1, e2)) or ELEMENT_AFFINITY.get((e2, e1))

def _modality_score(m1, m2):
    if m1 == m2:
        return 6  # two of the same modality can clash (stubborn/stubborn) or reinforce
    if {m1, m2} == {"cardinal", "mutable"}:
        return 8  # leader + adapter tends to work well
    if {m1, m2} == {"cardinal", "fixed"}:
        return 5  # both want control
    if {m1, m2} == {"fixed", "mutable"}:
        return 7
    return 6

def compatibility_score(sign_a: str, sign_b: str, context: str) -> dict:
    sign_a, sign_b = sign_a.strip().title(), sign_b.strip().title()

    if sign_a not in ELEMENTS or sign_b not in ELEMENTS:
        bad = sign_a if sign_a not in ELEMENTS else sign_b
        return {"error": f"'{bad}' isn't a recognized zodiac sign. "
                          f"Expected one of: {', '.join(sorted(ELEMENTS))}."}
    if context not in CONTEXT_WEIGHTS:
        return {"error": f"Unknown context '{context}'. Use one of: "
                          f"{', '.join(CONTEXT_WEIGHTS)}."}

    e1, e2 = ELEMENTS[sign_a], ELEMENTS[sign_b]
    m1, m2 = MODALITIES[sign_a], MODALITIES[sign_b]
    elem_w, mod_w = CONTEXT_WEIGHTS[context]

    elem_score = _affinity(e1, e2)
    mod_score = _modality_score(m1, m2)
    final = round((elem_score * elem_w + mod_score * mod_w) * 10, 1)  # scale to 0-100

    return {
        "sign_a": sign_a, "sign_b": sign_b, "context": context,
        "score": final,
        "breakdown": {
            "element_pairing": f"{e1} + {e2}", "element_score": elem_score,
            "modality_pairing": f"{m1} + {m2}", "modality_score": mod_score,
        },
    }


# Tool 3: Unique Tool 2
DECISION_SCHEMA = {
    "name": "decision_timing_advisor",
    "description": (
        "Given a type of decision the user is considering and their zodiac sign, "
        "checks the CURRENT planetary retrogrades against a rules table and "
        "recommends 'proceed', 'proceed_with_caution', or 'wait'. Each relevant "
        "retrograde adds 1 to a risk score, or 2 if it's the planet that rules "
        "the user's sign (score 0 = proceed, 1 = caution, 2+ = wait). "
        "Ask for the user's sign if you don't know it. "
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "decision_type": {
                "type": "string",
                "enum": ["send_message", "ask_for_raise", "start_new_project",
                         "have_hard_conversation", "make_purchase", "sign_contract"],
                "description": "The kind of decision the user is weighing. Pick the closest match.",
            },
            "sign": {"type": "string", "description": "The user's zodiac sign, e.g. 'Gemini'."},
            "current_transits": {
                "type": "array",
                "description": (
                    "Optional. The 'transits' list from get_current_transits, if you "
                    "already have it. Omit this and the tool will fetch fresh data."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["decision_type", "sign"],
    },
}

# Rules: which planets' retrogrades matter for which decision type, and why.
# Most decisions have two relevant planets so that "wait" (2+ flags) can actually happen.
RETROGRADE_FLAGS = {
    "send_message": {
        "Mercury": "Mercury retrograde is linked to miscommunication — messages can land wrong or get misread.",
        "Venus": "Venus retrograde can make messages to loved ones or exes emotionally loaded.",
    },
    "have_hard_conversation": {
        "Mercury": "Conversations risk being misunderstood during Mercury retrograde.",
        "Mars": "Mars retrograde is associated with suppressed anger that flares up unexpectedly.",
    },
    "sign_contract": {
        "Mercury": "Mercury retrograde is traditionally considered risky for contracts — reread the fine print.",
        "Saturn": "Saturn retrograde invites a second look at long-term commitments and obligations.",
    },
    "start_new_project": {
        "Mars": "Mars retrograde can drain momentum on new initiatives — energy may fizzle.",
        "Jupiter": "Jupiter retrograde can slow growth and luck around new ventures.",
    },
    "ask_for_raise": {
        "Venus": "Venus retrograde can complicate negotiations around value and money.",
        "Saturn": "Saturn retrograde is linked to friction with authority figures and delayed recognition.",
    },
    "make_purchase": {
        "Venus": "Venus retrograde is associated with buyer's remorse — reconsider big purchases.",
        "Mercury": "Mercury retrograde is linked to faulty products and overlooked details.",
    },
}
# Traditional ruling planets. A retrograde of your own ruler hits harder.
SIGN_RULERS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
    "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
    "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
    "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
}


def decision_timing_advisor(decision_type: str, sign: str, current_transits: list = None) -> dict:
    if decision_type not in RETROGRADE_FLAGS:
        return {"error": f"Unknown decision_type '{decision_type}'. "
                          f"Use one of: {', '.join(RETROGRADE_FLAGS)}."}

    sign = (sign or "").strip().title()
    if sign not in SIGN_RULERS:
        return {"error": f"'{sign}' isn't a recognized zodiac sign. "
                          f"Expected one of: {', '.join(SIGN_RULERS)}."}

    # If the model didn't pass transits (or passed junk), fetch them ourselves.
    if not current_transits or not isinstance(current_transits, list):
        fetched = get_current_transits()
        if "error" in fetched:
            return {"error": f"Couldn't fetch current transits to evaluate this decision: "
                              f"{fetched['error']}"}
        current_transits = fetched["transits"]

    ruler = SIGN_RULERS[sign]
    relevant_flags = RETROGRADE_FLAGS[decision_type]
    triggered = []
    checked = []
    score = 0

    for t in current_transits:
        planet = t.get("planet")
        if planet in relevant_flags:
            is_retro = bool(t.get("retrograde", False))
            checked.append({"planet": planet, "retrograde": is_retro})
            if is_retro:
                is_ruler = planet == ruler
                weight = 2 if is_ruler else 1
                score += weight
                reason = relevant_flags[planet]
                if is_ruler:
                    reason += f" As a {sign}, {planet} is your ruling planet, so this hits you harder."
                triggered.append({"planet": planet, "weight": weight, "reason": reason})

    if score >= 2:
        verdict = "wait"
    elif score == 1:
        verdict = "proceed_with_caution"
    else:
        verdict = "proceed"

    return {
        "decision_type": decision_type,
        "sign": sign,
        "ruling_planet": ruler,
        "verdict": verdict,
        "risk_score": score,
        "flags_triggered": triggered,
        "planets_checked": checked,
        "note": ("No retrograde flags relevant to this decision right now."
                  if not triggered else None),
    }
# What the model sees: the "set notes" in the screenplay

TOOLS = [
    TRANSITS_SCHEMA,
    {"type": "function", "function": COMPATIBILITY_SCHEMA},
    {"type": "function", "function": DECISION_SCHEMA},
]

# What the harness runs: tool name -> Python function.
TOOL_MAP = {
    "get_current_transits": get_current_transits,
    "compatibility_score": compatibility_score,
    "decision_timing_advisor": decision_timing_advisor
}


def run_tool(name: str, args: dict) -> str:
    """Run one tool call. Models invent tool names and arguments; never let that crash the loop."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(TOOL_MAP)}"})
    try:
        result = TOOL_MAP[name](**args)
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})
    except Exception as e:
        return json.dumps({"error": f"{name} failed unexpectedly: {type(e).__name__}: {e}"})
    return json.dumps(result)