import os
import json
import requests
from datetime import date

# ---- Tool 1: External Tool (OpenEphemeris) ----

OPENEPHEMERIS_API_KEY = os.environ.get("OPENEPHEMERIS_API_KEY")

if not OPENEPHEMERIS_API_KEY:
    raise RuntimeError(
        "Missing OPENEPHEMERIS_API_KEY. Set it in a .env file or your "
        "environment before starting the server."
    )

OPENEPHEMERIS_URL = "https://api.openephemeris.com/ephemeris/natal-chart"


def get_current_transits(target_date: str = None) -> dict:
    """Calls the OpenEphemeris API for current planetary positions.

    We reuse the natal-chart endpoint by treating "today" (or the given
    date) as the subject's birth moment — the sign/degree/retrograde status
    of each planet at that instant is exactly what a transit snapshot is.
    Location doesn't affect a planet's zodiac sign or degree, so a fixed
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
        print("RAW API RESPONSE:", json.dumps(data, indent=2))
    except requests.exceptions.Timeout:
        return {"error": "The astrology data provider timed out. Try again in a moment."}
    except requests.exceptions.HTTPError as e:
        body_preview = ""
        try:
            body_preview = e.response.text[:300]
        except Exception:
            pass
        return {"error": f"OpenEphemeris rejected the request ({e.response.status_code}). "
                          f"Check that target_date is formatted YYYY-MM-DD and the API key "
                          f"is valid. Response: {body_preview}"}
    except requests.exceptions.RequestException:
        return {"error": "Could not reach OpenEphemeris. Check network/API key config."}

    # TODO: adjust this once you see the real shape of `data` printed above.
    # This is a best-guess parse based on common astrology-API conventions
    # (a "planets" list with name/sign/degree/retrograde-ish fields).
    try:
        planets = data["planets"]
        transits = [
            {
                "planet": p["name"],
                "sign": p["sign"],
                "degree": round(p.get("longitude", {}).get("decimal", p.get("degree", 0)), 1),
                "retrograde": p.get("retrograde", False),
            }
            for p in planets
        ]
    except (KeyError, TypeError) as e:
        return {"error": f"Got a response from OpenEphemeris but couldn't parse it as expected "
                          f"(missing field: {e}). Check the RAW API RESPONSE printed in the "
                          f"server logs and adjust the parsing in get_current_transits."}

    return {"date": target_date, "transits": transits}


if __name__ == "__main__":
    print(json.dumps(get_current_transits(), indent=2))


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


# What the model sees: the "set notes" in the screenplay.
TOOLS = [
    {
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
    },
    COMPATIBILITY_SCHEMA,
]

# What the harness runs: tool name -> Python function.
TOOL_MAP = {
    "get_current_transits": get_current_transits,
    "compatibility_score": compatibility_score,
}


def run_tool(name: str, args: dict) -> str:
    """Run one tool call. Models invent tool names and arguments; never let that crash the loop."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(TOOL_MAP)}"})
    try:
        result = TOOL_MAP[name](**args)
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})
    return json.dumps(result)