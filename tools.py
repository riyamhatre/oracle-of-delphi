"""The tools the harness can run, and the JSON that describes them to the model."""

import json

import requests

from datetime import date
import os
from dotenv import load_dotenv

load_dotenv()  # reads .env into environment variables

# Open-Meteo is free and needs no API key.
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


ASTROLOGY_API_USER_ID = os.environ.get("ASTROLOGY_API_USER_ID")
ASTROLOGY_API_KEY = os.environ.get("ASTROLOGY_API_KEY")

if not ASTROLOGY_API_USER_ID or not ASTROLOGY_API_KEY:
    raise RuntimeError(
        "Missing ASTROLOGY_API_USER_ID or ASTROLOGY_API_KEY. "
        "Set them in a .env file or your environment before starting the server."
    )


def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    try:
        places = requests.get(GEOCODE_URL, params={"name": location, "count": 1}, timeout=10).json()
        if not places.get("results"):
            return json.dumps({"error": f"City '{location}' was not found."})
        place = places["results"][0]

        current = requests.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
            },
            timeout=10,
        ).json()["current"]
    except requests.RequestException as e:
        # The model cannot see an exception. Return something it can reason about.
        return json.dumps({"error": f"Weather service failed: {e}"})

    return json.dumps({
        "location": place["name"],
        "temp_f": current["temperature_2m"],
        "humidity": current["relative_humidity_2m"],
        "wind_mph": current["wind_speed_10m"],
    })

# Tool 1: External Tool 
def get_current_transits(target_date: str = None) -> dict:
    """Calls the astrology API for current planetary positions.

    Returns a dict with either 'transits' (on success) or 'error' (on failure),
    the latter containing an actionable message the model can relay to the user
    or use to retry/adjust.
    """
    target_date = target_date or date.today().isoformat()

    try:
        resp = requests.get(
            "https://json.astrologyapi.com/v1/planets",
            auth=(ASTROLOGY_API_USER_ID, ASTROLOGY_API_KEY),
            params={"date": target_date},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        print("RAW API RESPONSE:", data)
    except requests.exceptions.Timeout:
        return {"error": "The astrology data provider timed out. Try again in a moment."}
    except requests.exceptions.HTTPError as e:
        return {"error": f"Astrology API rejected the request ({e.response.status_code}). "
                          f"Check that the date is valid and formatted YYYY-MM-DD."}
    except requests.exceptions.RequestException:
        return {"error": "Could not reach the astrology data provider. Check network/API key config."}

    # Normalize into a compact, model-friendly shape
    transits = [
        {
            "planet": p["name"],
            "sign": p["sign"],
            "degree": round(p["normDegree"], 1),
            "retrograde": p.get("isRetro", False),
        }
        for p in data
    ]
    return {"date": target_date, "transits": transits}


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
            "name": "get_weather",
            "description": "Get the current weather (temperature, humidity, wind) for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name, e.g. 'New York'"},
                },
                "required": ["location"],
            },
        },
    },
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
    "get_weather": get_weather,
    "get_current_transits": get_current_transits,
    "compatibility_score": compatibility_score,
}


def run_tool(name: str, args: dict) -> str:
    """Run one tool call. Models invent tool names and arguments; never let that crash the loop."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(TOOL_MAP)}"})
    try:
        return TOOL_MAP[name](**args)
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})