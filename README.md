# The As If Machine

A writing environment where an AI assistant autocompletes your sentences **as if** you had lived through a counterfactual event.

A participant answers a few intake questions. The app turns those answers into a first-person character description, pairs it with a scenario you wrote, and asks a language model to imagine how that scenario would unfold for that specific person. The participant then writes a short story in a plain text editor. Whenever they pause, the assistant suggests the rest of the sentence, in character and conditioned on the scenario. Press `Tab` to accept a suggestion; keep typing to reject it.

The app records every suggestion, every accept, every reject, and the finished story, which makes it usable as an experimental instrument: you can vary the scenario, vary how much of it the participant sees, and measure what they write.

---

## Contents

- [How it works](#how-it-works)
- [Quickstart](#quickstart)
- [Project layout](#project-layout)
- [Configuration](#configuration)
- [Writing your own scenario](#writing-your-own-scenario)
- [Testing prompts without the app](#testing-prompts-without-the-app)
- [Running a study](#running-a-study)
- [Saving data](#saving-data)
- [Deploying](#deploying)
- [Troubleshooting](#troubleshooting)
- [Costs](#costs)
- [License](#license)

---

## How it works

![The As If Machine: participant view and system view](docs/system_two_track.png)

**Panel a, participant view.** The participant completes an intake form, then continues a scenario prompt the system built from their answers (orange outlines). Whenever they pause, the system suggests a continuation, which they accept with `Tab`.

**Panel b, system view.** Four steps run once before writing begins. The system turns the intake answers into a text profile (1). The Initializer writes a personalized event onset, which becomes the visible prompt (2). The Predictor forecasts how the event would affect this participant (3). The Storyteller combines the onset and effects into a plot (4). During writing, the Autocompleter reads the profile, event, plot, and current text, and offers continuations (5).

The figure names the agents; the code names their outputs. They line up like this:

| Agent in the figure | Writes | Key in `config.yaml` | Prompt in `prompts.yaml` |
|---|---|---|---|
| Initializer | Onset | `start` | `start_of_event` |
| Predictor | Effects | `effects` | `dynamic_effects` |
| Storyteller | Plot | `plot`, `plot_from_effects` | `event_plot`, `event_plot_from_effects` |
| Autocompleter | Suggestion | — | `chat_completion` |

The "Event" the agents read is the `name` you write under `event:` in `config.yaml`. The "Profile" is the character description built from the intake answers.

### 1. Intake

A participant lands on `/user_settings_experiment/<event_key>`, where `<event_key>` names an event in `config.yaml`. They answer the base questions (participant ID, age, gender, occupation, location) plus any extra questions that event defines.

Those answers become a first-person character description:

> I am 41 years old from Toledo, Ohio, working as a hospital nurse. My gender is Female. My daily dependency is paying with a card or getting cash from an ATM. My cash situation is almost none.

### 2. Scenario generation

The app sends the character description and your scenario text to the model (`event.effects_generator_model`) and generates four texts:

| Name | What it is |
|---|---|
| `start` | A realistic ~100-130 word scene that brings this event about for this person |
| `effects` | An enumerated list of concrete effects the event would have on this person |
| `plot` | A short plot built from the character and the `start` |
| `plot_from_effects` | A longer plot built from the character, the `start`, and the `effects` |

`start` and `effects` are generated in parallel, then the two plots. Expect a few seconds between form submission and the editor loading.

Two settings decide what happens to these four texts:

- **`autocomplete_context`** picks which one conditions the inline suggestions.
- **`shown_to_user`** picks which one the participant reads above the editor, or `none` to show nothing.

They are independent. Showing the participant a short `plot` while conditioning the model on `plot_from_effects` is a valid design, and so is showing them nothing at all, which confines the manipulation to the suggestions themselves.

### 3. Writing

The editor runs a countdown timer (`timer.minutes`). After the participant finishes `autocomplete.min_sentences` sentences, every pause longer than `autocomplete.debounce_time` milliseconds fires a request to `/autocomplete`, which sends the last `autocomplete.context_sentences` sentences plus the unfinished sentence to the model. The suggestion appears as grey text. `Tab`, `Enter`, or `→` accepts it; any other key rejects it.

Each request samples its own temperature and token budget from the ranges in `config.yaml`, so suggestions vary in length and tone. `autocomplete.event_relevant` sets the proportion of suggestions conditioned on the event: at `1.0` every suggestion is, at `0.7` roughly three in ten ignore the scenario and simply continue the sentence in character.

When the timer expires the editor locks and the story posts to `/save_completed_journal`.

---

## Quickstart

You need Python 3.11 or newer (tested on 3.12) and an OpenAI API key. Nothing else — no database, no accounts.

```bash
git clone https://github.com/josh-ashkinaze/asif-machine.git
cd asif-machine
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create your `.env` from the template and fill in your key:

```bash
cp .env.example .env
```

Open `.env` and replace `REPLACE_WITH_YOUR_OPENAI_API_KEY` with a real key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys). Every other variable is optional; leave the placeholders alone for now.

Start the app:

```bash
python app.py
```

Open **http://localhost:5001**. You land on the intake form for `default_experiment_event` in `config.yaml`, which ships as `example_1_minimal`. Fill it in, wait a few seconds for the scenario to generate, and start writing.

To try a different example scenario, go straight to its URL:

```
http://localhost:5001/user_settings_experiment/example_3_tokens_and_custom_intake
```

Without a MongoDB connection string the app prints `NO MONGO URL SET -- skipping save` and discards the data. Everything else works. See [Saving data](#saving-data) when you are ready to record.

---

## Project layout

```
app.py              Flask app: routes, the autocomplete endpoint, text processing
config.py           Loads config.yaml, prompts.yaml and .env into an AppConfig object
forms.py            Builds the intake form, including the per-event extra questions
mongo_util.py       Reads and writes MongoDB
alert.py            Posts a throttled Slack alert when model calls fail

config.yaml         Everything you tune: models, timing, scenarios, intake questions
prompts.yaml        The prompts behind scenario generation and autocompletion
.env.example        Template for secrets. Copy to .env

templates/
  index.html                    The editor, timer, and suggestion logic
  user_settings_experiment.html Intake form for a predefined event
  user_settings.html            Intake form where the participant invents the event
  offline.html                  Maintenance page
static/styles/                  CSS

tests/test_prompt.py            Interactive CLI for iterating on prompts

Dockerfile          Container build
Procfile            Process definition for Railway, Heroku, and similar hosts
requirements.txt    Direct dependencies
```

### Routes

| Route | Purpose |
|---|---|
| `/` | Redirects to the intake form for `default_experiment_event` |
| `/user_settings_experiment/<event_key>` | Intake form for one predefined event. **Send participants here.** |
| `/index` | The editor. Redirects back to intake if the session holds no scenario |
| `/autocomplete` | `POST`. Returns one suggestion for the text sent to it |
| `/save_completed_journal` | `POST`. Writes the finished story and the suggestion log |
| `/user_settings` | Intake form where the participant writes their own event. Useful for demos, unused in studies |

---

## Configuration

`config.yaml` is the only file most people need to edit. It is commented throughout. The sections:

**Meta settings** — `hardcode_character_and_event` skips the intake form entirely and builds the character from the `characters:` block, which is the fastest way to test a scenario on yourself. `default_experiment_event` sets where `/` sends people. `lab_mode` adds a live debounce slider to the editor for pilot sessions; keep it off for real participants. `app_is_offline` serves a maintenance page when deployed.

**`llm`** — the model that writes suggestions, plus the temperature and token ranges each request samples from. Any model [LiteLLM](https://docs.litellm.ai/docs/providers) supports works. Switching to a model with `claude` in its name drops the frequency and presence penalties and clamps the temperature range to Anthropic's `[0, 1]`.

**`autocomplete`** — timing and behavior: how long a pause triggers a suggestion, how much prior text the model sees, how many sentences the participant must write first, and the default `autocomplete_context` and `shown_to_user`.

**`characters`** — hardcoded characters, used only when `hardcode_character_and_event: true`.

**`event`** — your scenarios. One key per experimental condition. See below.

**`stuck_prompts`, `timer`, `editor_defaults`** — editor copy: the rotating hints, the time limit, the message shown when time runs out, and the default placeholder text.

`prompts.yaml` holds the prompts themselves: the four scenario generators, the two autocompletion prompts (one for event-conditioned suggestions, one for event-free), and the shared `constraints` list that forbids metaphor, sentimentality, and restating the context. Edit these to change the house style of the suggestions.

---

## Writing your own scenario

> **New to this?** Start with **[AIM_SCENARIO_GUIDE.pdf](docs/AIM_SCENARIO_GUIDE.pdf)** (8 pages). It walks through one scenario end to end — making it specific, choosing intake questions, and the complete YAML block — then hands you a set of scenario directions to borrow from.

An event is one key under `event:` in `config.yaml`, reachable at `/user_settings_experiment/<that key>`. `config.yaml` ships with five commented examples, labeled `THESE ARE EXAMPLES`, ordered simplest to most complex. Each demonstrates a different feature:

| Example | Demonstrates |
|---|---|
| `example_1_minimal` | The minimum: `name` and nothing else |
| `example_2_hidden_scenario` | `shown_to_user: none`, so the manipulation reaches the participant only through suggestions |
| `example_3_tokens_and_custom_intake` | Custom intake questions, bracket tokens, validators, a custom heading and placeholder |
| `example_4_freetext_and_onset` | Free-text intake questions, and conditioning suggestions on the opening scene alone |
| `example_5_split_context_and_date` | Showing the participant one scenario text while conditioning the model on another, and anchoring to today's date |

Delete them and write your own.

### The one required key

```yaml
event:
  my_event:
    name: >
      You win $50,000 in a state lottery drawing.
```

That alone works. Everything else inherits from the `autocomplete:` defaults.

### Every other key

| Key | Effect |
|---|---|
| `autocomplete_context` | Which generated text conditions suggestions: `start`, `effects`, `plot`, `plot_from_effects` |
| `shown_to_user` | Which generated text the participant reads, or `none` |
| `shown_to_user_prefix` | The heading above that text |
| `editor_placeholder` | Placeholder text in the editor |
| `add_current_date` | Appends today's date to the character description, for date-anchored scenarios |
| `additional_fields` | Extra intake questions |

### Bracket tokens

Scenario text often refers to an intake answer in square brackets:

```yaml
name: >
  You live in [metro_type] in [state]. [daily_dependency] stops working
  without warning.
```

**Nothing substitutes these strings.** They work because the matching answer already sits in the character description the model reads alongside the scenario ("My state is Ohio. My metro type is a suburb."), so the model resolves them itself. Name a token exactly as you named the field and it will resolve. Misname it and the model invents a value.

### Tip blocks

A `[Tip: ...]` block inside `name` is stage direction for the model, not text the participant sees. Use it to set the shape of the story: what to open on, what to reveal and when, what to state once and never repeat, how to end. The examples in `config.yaml` number their beats and close with explicit prohibitions. Those prohibitions matter more than the instructions — "never name emotions, reveal them through action" and "no metaphors" do most of the work of keeping output readable.

### Custom intake questions

```yaml
additional_fields:

  state:
    type: "StringField"
    label: "What U.S. state do you live in?"
    validators: [ "DataRequired" ]

  metro_type:
    type: "SelectField"
    label: "Where do you live?"
    choices: [ "a big city", "a suburb", "a small town", "a rural area" ]
    validators: [ "DataRequired" ]

  years_at_address:
    type: "IntegerField"
    label: "How many years have you lived at your current address?"
    validators:
      - "DataRequired"
      - NumberRange: { min: 0, max: 100 }
```

`type` is any [WTForms field class](https://wtforms.readthedocs.io/en/3.0.x/fields/); `StringField`, `TextAreaField`, `IntegerField`, and `SelectField` cover most needs. `SelectField` requires `choices`, a flat list of strings. `validators` takes either a bare name (`"DataRequired"`) or a single-key mapping carrying arguments (`Length: { max: 70 }`).

### Iterating

Edit `config.yaml`, restart the app, and resubmit the form. Flask's reloader picks up template and Python changes, but `AppConfig` reads `config.yaml` once at import, so a config change needs a restart. To read the generated scenario texts without clicking through the app, use the prompt testing CLI below.

---

## Testing prompts without the app

`tests/test_prompt.py` runs the scenario-generation pipeline from the command line against any event and character in `config.yaml`, prints the exact prompts it sent, and reloads both YAML files on command. Use it when you are drafting a `name` block and want to see what the model makes of it.

```bash
python tests/test_prompt.py
```

Type `help` for the commands, `reload` after editing a YAML file, and `quit` to exit.

---

## Running a study

**Link participants to one event.** Send them to `/user_settings_experiment/<event_key>`, not to `/`. One event key per condition, one link per condition.

**Pass through a participant ID.** Append `?pid=...` to the link and the app stores it as `auto_pid`, independent of whatever the participant types into the form. Use your survey platform's piped ID:

```
https://your-app.example.com/user_settings_experiment/my_event?pid=${e://Field/PROLIFIC_PID}
```

**Hand back a completion code.** `timer.message_to_display_when_time_is_up` appears when time runs out, and `timer.message_when_under_min_words` appears instead if the participant wrote fewer than `autocomplete.min_words` words. Both accept HTML. Put your codes there; the shipped config has `REPLACE_WITH_YOUR_COMPLETION_CODE` placeholders.

**Pilot before you launch.** Set `lab_mode: true` and run a few sessions yourself. The debounce slider lets you tune the pause threshold live, which is the single setting participants notice most. Turn it off before recruiting.

---

## Saving data

The app writes to MongoDB. Any connection string works, including a free [MongoDB Atlas](https://www.mongodb.com/atlas) cluster. Set `MONGO_WORKING_STAGE_URL` in `.env` for local runs and `MONGO_URL` in your host's environment variables when deployed.

Everything goes into a database named `user`, in three collections:

**`user-data`** — one document per intake submission: every form answer, the event key, the `auto_pid` if you passed one, and a session `uuid`.

**`journal-data`** — one document per finished story:

| Field | Contents |
|---|---|
| `uuid` | Links back to the `user-data` document |
| `content` | The finished story |
| `autocomplete_stats` | `received`, `accepted`, `rejected`, `acceptance_rate` |
| `autocomplete_history` | Every suggestion, with its accepted or rejected status |
| `shown_to_user` | The scenario text this participant read |
| `autocomplete_context` | The scenario text the model was conditioned on |
| `event_id` | The event key |

**`error-log`** — model API failures, with the session `uuid`.

To pull data back out, call `mongo_util.retrieve_database_data()`, which reads `MONGO_WORKING_STAGE_URL`, `MONGO_STAGING_URL`, or `MONGO_PRODUCTION_URL` depending on the branch name you pass, and filters by event key and date:

```python
from datetime import datetime
import mongo_util

docs = mongo_util.retrieve_database_data(
    "production",
    "journal-data",
    event_id="my_event",
    start_date=datetime(2026, 1, 1),
)
```

---

## Deploying

The app ships a `Procfile` and a `Dockerfile`. It reads `PORT` from the environment, falling back to 5001, and switches to production mode (debug off) when `RAILWAY_ENVIRONMENT_NAME` is set.

### Railway

1. Push this repository to GitHub.
2. Create a project at [railway.app](https://railway.app) and point it at the repository. Railway detects the `Procfile`.
3. Add the environment variables: `OPENAI_API_KEY`, `FLASK_SECRET_KEY`, and `MONGO_URL`. Give staging and production separate `MONGO_URL` values so pilot data never lands in your real dataset.
4. Generate a public domain under Settings → Networking.

Set `FLASK_SECRET_KEY` to a fixed value in production. Without it the app generates a random key at startup, which invalidates every live session whenever the server restarts.

### Docker

```bash
docker build -t asifmachine .
docker run -p 5001:5001 \
  -e OPENAI_API_KEY=your_key_here \
  -e FLASK_SECRET_KEY=your_secret_here \
  asifmachine
```

The app is then at http://localhost:5001.

### Any other host

```bash
gunicorn -w 2 --timeout 120 -b 0.0.0.0:$PORT app:app
```

Keep the timeout generous. Scenario generation makes several model calls before the editor loads, and a short timeout cuts participants off mid-intake.

---

## Troubleshooting

**`OPENAI_API_KEY environment variable not set`** — `.env` is missing, sits outside the project root, or still holds the placeholder. The app only demands the key matching the model in `config.yaml`: a `gpt-` model needs `OPENAI_API_KEY`, a `claude` model needs `ANTHROPIC_API_KEY`.

**`Unknown event '...'`** — the event key in the URL has no match under `event:` in `config.yaml`. Check the spelling, and remember that renaming an event breaks any link already sent to participants.

**The intake form redirects back to itself** — a validator rejected an answer. The errors render under the offending fields.

**`/index` bounces to the intake form** — the session holds no scenario. Submit the intake form rather than visiting `/index` directly; this also happens after a restart that rotated a random `FLASK_SECRET_KEY`.

**No suggestions appear** — the participant has not yet finished `autocomplete.min_sentences` sentences, or has not paused for `autocomplete.debounce_time` milliseconds. Check the browser console and the server log for model API errors.

**Suggestions repeat the sentence already written** — raise `llm.frequency_penalty` and `llm.presence_penalty`, or strengthen the last entry in the `constraints` list in `prompts.yaml`.

**`NO MONGO URL SET -- skipping save`** — expected without a database. Set `MONGO_WORKING_STAGE_URL` (local) or `MONGO_URL` (deployed) to record data.

**Changes to `config.yaml` do nothing** — restart the app. The config loads once at import.

---

## Costs

Each participant triggers four scenario-generation calls at intake, then one small call per pause while writing. A six-minute session runs to a few dozen short completions. Scenario generation dominates the bill, so `event.effects_generator_model` drives your cost far more than `llm.model` does. Price a pilot session before recruiting at scale.

---

## License

MIT. See [LICENSE](LICENSE).
