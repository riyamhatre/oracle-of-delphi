# oracle-of-delphi
# Pythia: The Oracle of Delphi

The motivation behind this project was to create an agent that specializes in zodiac-related topics and can help a user make decisions based on the celestial bodies. We named our agent "Pythia" after the prominent high priestess at Apollo's temple at Delphi, known "professionally" as the Oracle of Delphi.

## How It Works

Based on the question provided by the user, the model determines whether it should answer directly or use one of the three tools we created. If a tool is called, the code looks up the function in the `TOOL_MAP` and runs it with `run_tool()`. The result is put into the message history, which is seen by Gemini, who either answers the user at that point or requests another tool. This loop repeats up to 5 times to prevent infinite loops.

To make sure the model remembers past content, each message is appended to the same list for that `session_id`, and the whole list is sent to Gemini on every call, since Gemini doesn't have memory between calls.

### How Gemini decides which tool to use, if any

Each tool's schema has a `description` field written specifically to instruct Gemini. Gemini reads these descriptions and decides whether a tool applies. When you ask something unrelated, none of the tools are called because the question doesn't match any of the predetermined descriptions.

## Workflow Diagram

![Workflow Diagram](diagram.png)

## Tools

### Tool 1: `get_current_transits`

This tool pulls data from an external API called OpenEphemeris, which uses NASA's JPL DE440 data to calculate planetary positions and generate the math for various astrological pursuits (natal charts, Vedic astrology, etc.). The model answers questions based on whatever date the user wants information for.

After sending a POST request, we get a large JSON response filled with information on various celestial bodies. This is filtered down to the 12 that matter (the solar system bodies plus a few extras like Chiron). For each one, we get its zodiac sign, its degree within that sign, and whether it's retrograde.

### Tool 2: `compatibility_score`

Unlike Tool 1, there is no API call here. This tool takes the context from the user's message and the two zodiac signs they mention (for example: "Okay so I'm a Gemini and my crush is a Taurus, are we compatible?").

Each sign has a classical element and a modality, and a lookup table determines how well elements get along and how modalities interact. The weights change based on the context: modality matters more for roommates than element, while for romance it's the reverse. The tool multiplies the weights through and returns a score along with a breakdown so the user can see why it scored the way it did.

### Tool 3: `decision_timing_advisor`

This tool ties the first two together. It takes the decision type (send a text, ask for a raise, etc.) and the user's sign, and cross-references live retrogrades. A rules table maps each type of decision to the planets that usually influence it, and the tool checks whether any of those planets are currently in retrograde. If the user's ruling planet is the one in retrograde, we treat that as extra significant to them specifically.

Everything adds up to a risk score:

| Score | Recommendation |
|-------|----------------|
| 0 | Go ahead |
| 1 | Proceed with caution |
| 2+ | Wait |

## Running Locally

**Requirements:** Python 3.10+, [uv](https://docs.astral.sh/uv/getting-started/installation/), an OpenEphemeris API key, and Google Cloud credentials for Vertex AI.

1. Clone the repo and enter it:
   ```bash
   git clone https://github.com/riyamhatre/oracle-of-delphi.git
   cd oracle-of-delphi
   ```

2. Set up a GCP project with billing and the Agent Platform API enabled (older docs and the endpoint itself still call it Vertex AI).

3. Authenticate with Google Cloud:
   ```bash
   gcloud auth application-default login
   ```
   The app uses your gcloud default project, so make sure it's set to the project from step 2:
   ```bash
   gcloud config set project YOUR_PROJECT_ID
   ```

4. Get an OpenEphemeris API key (used by `get_current_transits`) and create a `.env` file in the project root:
   ```
   OPENEPHEMERIS_API_KEY=your_key_here
   ```

5. Start the app:
   ```bash
   uv run app.py
   ```
   Then open http://localhost:8000.

Try: *"I'm a Capricorn, should I ask for a raise this week?"*

> Planetary positions come from OpenEphemeris and require the API key above. Compatibility scoring is pure logic and needs no external service.

## Sample Questions

- Okay so I'm a Gemini and my crush is a Taurus, are we compatible? Should I ask them out? When should I ask them?
- Now I want to know whether it's a good time for me to ask for a raise.
- What's my day looking like today?
- Is anything in retrograde right now?

## Repo Contents

| File | Description |
|------|-------------|
| `index.html` | Holds all the styling and webpage information |
| `app.py` | Defines the agent and tool loop, and calls the tools from `tools.py` |
| `tools.py` | Defines each of the three tools |
| `pyproject.toml` | Lists all package requirements for the repo |
| `sample_convo.pdf` | A sample conversation with the model |
| `diagram.png` | The workflow diagram shown above |