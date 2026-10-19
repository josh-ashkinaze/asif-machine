"""
Author: Joshua Ashkinaze
Date: 2023-12-26

Description: This file contains the main Flask app that handles the autocomplete requests. A user writes in a text editor, and
the app autocompletes the user's response as if this specific user experienced a specific event.
"""

import datetime
import json
import random
import re
import string
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime as dt
from zoneinfo import ZoneInfo

import litellm
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from litellm import completion
from litellm.exceptions import RateLimitError, APIConnectionError, APIError

litellm.drop_params = True
from alert import send_error_alert


def _classify_error(e):
    if isinstance(e, RateLimitError):
        return "RATE_LIMITED"
    if isinstance(e, APIConnectionError):
        return "CONNECTION_ERROR"
    if isinstance(e, APIError):
        return "API_ERROR"
    return type(e).__name__.upper()

import mongo_util
from config import AppConfig
from forms import BaseCharacterForm, EventForm, create_character_form

app = Flask(__name__)
app_config = AppConfig()
app.config["SECRET_KEY"] = app_config.flask_secret_key
prompts = app_config.prompts


PROMPT_WORDS = [
    "INSTRUCTIONS",
    "CONTEXT",
    "INCOMPLETE SENTENCE",
    "CHARACTER DESCRIPTION",
    "EVENT",
    "EVENT EFFECTS",
]
PROMPT_WORDS_PATTERN = re.compile(
    r"\b(" + "|".join(map(re.escape, PROMPT_WORDS)) + r")\b:?\s*"
)
SENTENCE_PATTERN = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")


@app.route("/")
def initial():
    """
    Initialize application. Route to user_setting in no experimenting mode with hardcode
    persona turned off. Route directly to index with hardcode turned on and all effects
    applied as specified in yaml.
    """
    session["uuid"] = str(uuid.uuid4())
    if app_config.is_offline and app_config.is_prod:
        return render_template("offline.html"), 503  # HTTP 503 Service Unavailable
    if app_config.experiment_enabled and not app_config.hardcoded:
        return redirect(
            url_for(
                "user_settings_experiment",
                experiment_key=app_config.default_experiment_event,
            )
        )
    if not app_config.hardcoded:  # Ask user to create character and event
        return redirect(url_for("user_settings"))
    else:  # Use hardcoded character and event
        session["character_description"] = app_config.character_description
        session["event_name"] = app_config.event["name"]
        session["event_config"] = {
            k: v for k, v in app_config.event.items() if k != "additional_fields"
        }

        session["event_effects"] = app_config.event_effects
        session["start_of_event"] = app_config.start_of_event
        session["event_plot"] = app_config.event_plot
        session["event_plot_from_effects"] = app_config.event_plot_from_effects
        session["autocomplete_context"] = session[
            app_config.autocomplete_variable_map[app_config.autocomplete_context]
        ]
        session["shown_to_user"] = session[
            app_config.autocomplete_variable_map[app_config.shown_to_user]
        ]
        # Now, iterate over the session variables and print their sizes
        # print("Session variables and their sizes:")
        # total_session_size = 0
        # for key in session:
        #     value = session[key]
        #     size = get_size(value)
        #     total_session_size += size
        #     print(f"Session key '{key}' size: {size} bytes")
        # print(f"Total session size: {total_session_size} bytes")
        # print(f"session userinfo: {session['shown_to_user']}")
        session["user_info"] = {}
        session["user_info"]["uuid"] = session.get("uuid")
        return redirect(url_for("index"))


@app.route("/index")
def index():
    # print(session.get("start_of_event", None))
    start_of_event = session.get("start_of_event", None)
    if start_of_event is None:
        return redirect(url_for("user_settings"))

    preface, shown_text = get_shown_to_user_preface()
    editor_placeholder = get_editor_placeholder()
    # print("EDITOR PLACEHOLDER", editor_placeholder)

    """Returns rendered template"""
    # print("TIMER MINUTES", app_config.timer_minutes)
    # print("EXPERIMENT ENABLED", app_config.experiment_enabled)
    return render_template(
        "index.html",
        debounce_time=app_config.debounce_time,
        min_sentences=app_config.min_sentences,
        stuck_prompts=app_config.stuck_prompts,
        timer_minutes=app_config.timer_minutes,
        message=app_config.message_to_display_when_time_is_up,
        message_under_min_words=app_config.message_when_under_min_words,
        experiment_enabled=app_config.experiment_enabled,
        shown_to_user_text=shown_text,
        shown_to_user_preface=preface,
        editor_placeholder=editor_placeholder,
        min_words=app_config.min_words,
        lab_mode=app_config.lab_mode,
    )


@app.route("/autocomplete", methods=["GET", "POST"])
def autocomplete():
    """Handle the autocomplete request."""
    text = request.json.get("text")

    # Errors if text is None or session data is missing
    if text is None:
        return jsonify(error="Invalid input"), 400
    if not all(
        key in session for key in ["character_description", "event_name", "event_plot"]
    ):
        return jsonify(error="Session data is missing"), 400

    text = normalize_spacing(text)

    context, incomplete_sentence = get_context_and_incomplete_sentence(
        normalize_spacing(text)
    )
    context, incomplete_sentence = normalize_spacing(context), normalize_spacing(
        incomplete_sentence
    )
    include_event = random.random() <= app_config.event_relevant
    # print("INCLUDE EVENT", include_event)
    temperature = random.uniform(*app_config.temperature_range)
    completion = normalize_spacing(
        get_chat_completion(
            character_description=session["character_description"],
            event=session["event_name"],
            event_effects=session["autocomplete_context"],
            include_event=include_event,
            model=app_config.model,
            context=context,
            incomplete_sentence=incomplete_sentence,
            temperature=temperature,
            frequency_penalty=app_config.frequency_penalty,
            presence_penalty=app_config.presence_penalty,
            max_tokens=random.randint(*app_config.token_range),
            uuid=session.get("uuid"),
        )
    )
    completion_no_prompt = remove_prompt_words(completion)
    full_word_completion = normalize_spacing(
        extract_complete_words(completion_no_prompt)
    )
    de_duped_completion = normalize_spacing(
        remove_duplicated_completion(incomplete_sentence, full_word_completion)
    )
    d = {
        "text": text,
        "context": context,
        "incomplete_sentence": incomplete_sentence,
        "completion": completion,
        "full_word_completion": full_word_completion,
        "de_duped_completion": de_duped_completion,
        "completion_no_prompt": completion_no_prompt,
    }
    # print(d)
    return jsonify(completion=de_duped_completion)


############################################################
# HANDLE CHARACTER AND EVENT CREATION
############################################################
@app.route("/user_settings", methods=["GET", "POST"])
def user_settings():
    """
    This route is used when the user is required to create a character AND an event. In contras to user_settings_experiment,
    where in that route event is hardcoded.
    """
    character_form = BaseCharacterForm()
    event_form = EventForm()

    if request.method == "POST":
        if character_form.validate_on_submit() and event_form.validate_on_submit():
            save_form_data(character_form, event_form)
            flash("Character and event created successfully!", "success")
            character_description = construct_character_description(character_form)
            event_name = event_form.event.data

            session["character_description"] = character_description
            session["event_name"] = event_name

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_dynamic_effects = executor.submit(
                    get_dynamic_effects, character_description, event_name
                )
                future_start_of_event = executor.submit(
                    get_start_of_event, character_description, event_name
                )

                event_effects = future_dynamic_effects.result()
                start_of_event = future_start_of_event.result()

            session["event_effects"] = event_effects
            session["start_of_event"] = start_of_event
            session["event_plot"] = get_event_plot(
                character_description=character_description,
                event_name=event_name,
                event_start=start_of_event,
            )
            session["event_plot_from_effects"] = get_event_plot_from_effects(
                character_description=character_description,
                event_name=event_name,
                event_effects=event_effects,
                event_start=start_of_event,
            )
            session["autocomplete_context"] = session[
                app_config.autocomplete_variable_map[app_config.autocomplete_context]
            ]
            session["shown_to_user"] = (
                session[app_config.autocomplete_variable_map[app_config.shown_to_user]]
                if app_config.shown_to_user != "none"
                else None
            )

            return redirect(url_for("index"))
        else:
            flash("Please correct the errors in the form.", "error")

    return render_template(
        "user_settings.html", character_form=character_form, event_form=event_form
    )


@app.route("/user_settings_experiment/<string:experiment_key>", methods=["GET", "POST"])
def user_settings_experiment(experiment_key):
    """
    This route takes as input an 'experiment_key' which is a string that identifies an experiment event in the
    YAML. So for example `user_settings_experiment/event_1` will take the name of event1 from the YAML.
    """
    # In case if route is accessed directly instead of redirection from index
    if not session.get("uuid"):
        session["uuid"] = str(uuid.uuid4())

    # Capture Prolific ID from the URL (e.g. ?pid=...) so it's logged even if
    # the participant doesn't type it into the form correctly. Only overwrite
    # what's in the session if the query param is actually present.
    auto_pid = request.args.get("pid")
    if auto_pid:
        session["auto_pid"] = auto_pid

    # get event config info to use later
    if experiment_key not in app_config.event_list or not isinstance(
        app_config.event_list[experiment_key], dict
    ):
        return (
            f"Unknown event '{experiment_key}'. Add it under `event:` in config.yaml.",
            404,
        )
    event_config = app_config.config["event"][experiment_key]

    # NOTE: need to delete additional_fields and name since they cause cookie size errors.
    # name is safe to drop here since the same text is separately stored as
    # session["event_name"] (set below), which is what actually feeds prompt generation.
    event_config = {
        k: v for k, v in event_config.items() if k not in ("additional_fields", "name")
    }

    session["event_config"] = event_config
    session["event_name"] = app_config.config["event"][experiment_key]["name"]
    session["event_id"] = experiment_key
    character_form = create_character_form(app_config.event_list, experiment_key)

    if request.method == "POST":
        if character_form.validate_on_submit():
            save_form_data(character_form, hardcoded_event=session["event_name"], event_id=experiment_key)
            flash("Character created successfully!", "success")

            # Events tied to a real date (e.g. voting on election day) set
            # add_current_date in config.yaml so today's date is appended to
            # the character description.
            add_dt = bool(event_config.get("add_current_date", False))

            character_description = construct_character_description(
                character_form, add_dt=add_dt
            )
            session["character_description"] = character_description

            event_name = session["event_name"]

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_dynamic_effects = executor.submit(
                    get_dynamic_effects, character_description, event_name
                )
                future_start_of_event = executor.submit(
                    get_start_of_event, character_description, event_name
                )

                event_effects = future_dynamic_effects.result()
                start_of_event = future_start_of_event.result()

            session["event_effects"] = event_effects
            session["start_of_event"] = start_of_event
            session["event_plot_from_effects"] = get_event_plot_from_effects(
                character_description, event_name, event_effects, start_of_event
            )
            session["event_plot"] = get_event_plot(
                character_description, event_name, event_effects
            )

            # Setting what is given to LLM and shown to user, use event
            # specific settings if exist.
            event_autocomplete_context = event_config.get(
                "autocomplete_context",
                app_config.config["autocomplete"]["autocomplete_context"],
            )
            event_shown_to_user = event_config.get(
                "shown_to_user", app_config.config["autocomplete"]["shown_to_user"]
            )

            # print("SHOWN", event_shown_to_user, event_autocomplete_context)

            session["autocomplete_context"] = session[
                app_config.autocomplete_variable_map[event_autocomplete_context]
            ]

            session["shown_to_user"] = (
                session[app_config.autocomplete_variable_map[event_shown_to_user]]
                if event_shown_to_user != "none"
                else None
            )

            # print(f"session userinfo: {session['shown_to_user']}")
            # print(f"session userinfo: {session['user_info']}")
            data = json.loads(json.dumps(session["user_info"]))
            mongo_util.insert_user_data_to_database("user", app_config.MONGO_URL, data)
            return redirect(url_for("index"))
        else:
            flash("Please correct the errors in the form.", "error")

    return render_template(
        "user_settings_experiment.html",
        character_form=character_form,
        experiment_key=experiment_key,
    )


def get_start_of_event(character_description, event_name):
    client = app_config.client
    response = completion(
        model=app_config.effects_generator_model,
        messages=[
            {"role": "system", "content": prompts["start_of_event"]["system"]},
            {
                "role": "user",
                "content": prompts["start_of_event"]["user"].format(
                    event_name=event_name, character_description=character_description
                ),
            },
        ],
        temperature=0.6,
        max_tokens=1000,
    )
    finish_reason = response.choices[0].finish_reason
    print(f"START_OF_EVENT finish_reason: {finish_reason}")
    return json.loads(response.choices[0].model_dump_json())["message"]["content"]


def get_event_plot_from_effects(
    character_description, event_name, event_effects, event_start
):
    response = completion(
        model=app_config.effects_generator_model,
        messages=[
            {
                "role": "system",
                "content": prompts["event_plot_from_effects"]["system"],
            },
            {
                "role": "user",
                "content": prompts["event_plot_from_effects"]["user"].format(
                    character_description=character_description,
                    event_name=event_name,
                    event_effects=event_effects,
                    event_start=event_start,
                ),
            },
        ],
    )
    return json.loads(response.choices[0].model_dump_json())["message"]["content"]


def get_event_plot(character_description, event_name, event_start):
    response = completion(
        model=app_config.effects_generator_model,
        messages=[
            {
                "role": "system",
                "content": prompts["event_plot"]["system"],
            },
            {
                "role": "user",
                "content": prompts["event_plot"]["user"].format(
                    character_description=character_description,
                    event_name=event_name,
                    event_start=event_start,
                ),
            },
        ],
    )
    return json.loads(response.choices[0].model_dump_json())["message"]["content"]


def get_dynamic_effects(
    character_description, event_name, attempt_no=0, max_attempts=2
):
    if attempt_no > max_attempts:
        return None
    else:
        try:
            response = completion(
                model=app_config.effects_generator_model,
                messages=[
                    {"role": "system", "content": prompts["dynamic_effects"]["system"]},
                    {
                        "role": "user",
                        "content": prompts["dynamic_effects"]["user"].format(
                            event_name=event_name,
                            character_description=character_description,
                        ),
                    },
                ],
                temperature=0.6,
                max_tokens=1000,
            )
            answer = json.loads(response.choices[0].model_dump_json())["message"][
                "content"
            ]
            return answer
        except Exception as e:
            print(e)
            return get_dynamic_effects(
                character_description, event_name, attempt_no + 1, max_attempts
            )


def construct_character_description(form, add_dt=False):
    base_fields = ["age", "gender", "occupation", "location"]
    excluded_fields = base_fields + ["csrf_token", "prolific_id", "verify_info"]

    base_description = f"I am {form.age.data} years old from {form.location.data}, working as a {form.occupation.data}. My gender is {form.gender.data}. "

    additional_info = ". ".join(
        f"My {field.name.lower().replace('_', ' ')} is {field.data}"
        for field in form
        if field.name not in excluded_fields
    )
    if add_dt:
        est_time = dt.now(ZoneInfo("America/New_York"))
        additional_info += (
            f".Context: It is currently {est_time.strftime('%A %Y-%m-%d')}"
        )

    return (
        f"{base_description} {additional_info}."
        if additional_info
        else base_description
    )


def save_form_data(character_form, event_form=None, hardcoded_event=None, event_id=None):
    """
    Save original form data to session. Used later on for inserting user data to DB.
    event_form defaults to None for experiment mode.
    hardcoded_event is used when in experiment mode or when events are predefined.
    event_id is the experiment key (e.g. 'event_placebo_synesthesia') for DB filtering.
    """
    user_info = {}

    # Add all fields from character_form
    for field in character_form:
        if field.name != "csrf_token":
            user_info[field.name] = field.data

    if event_form is not None and event_form.event.data:
        # If event_form is provided and has data, use it
        user_info["event"] = event_form.event.data

    elif hardcoded_event is not None:
        # If a hardcoded event is provided (e.g., in experiment mode), use it
        user_info["event"] = hardcoded_event
    else:
        # If no event is provided, set it to None or a default value
        raise ValueError("No event provided")

    if event_id is not None:
        user_info["event_id"] = event_id

    if session.get("auto_pid"):
        user_info["auto_pid"] = session["auto_pid"]

    if not session.get("uuid"):
        session["uuid"] = str(uuid.uuid4())
    session["user_info"] = user_info
    session["user_info"]["uuid"] = session.get("uuid")


############################################################
# FUNCTIONS FOR PROCESSING TEXT
############################################################
def get_chat_completion(
    character_description,
    event,
    event_effects,
    context,
    incomplete_sentence,
    model,
    temperature,
    max_tokens,
    include_event,
    frequency_penalty=0,
    presence_penalty=0,
    attempt_no=0,
    max_attempts=1,
    uuid=None,
):
    if attempt_no > max_attempts:
        return None
    else:
        try:
            if include_event:
                system_instructions = prompts["chat_completion"]["event"][
                    "system"
                ].format(
                    event=event,
                    character_description=character_description,
                    event_effects=event_effects,
                    event_constraints=app_config.event_constraints,
                )
            else:
                system_instructions = prompts["chat_completion"]["non_event"][
                    "system"
                ].format(
                    character_description=character_description,
                    non_event_constraints=app_config.non_event_constraints,
                )
            completion_kwargs = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system_instructions},
                    {
                        "role": "user",
                        "content": prompts["chat_completion"]["event"]["user"].format(
                            context=context, incomplete_sentence=incomplete_sentence
                        ),
                    },
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if frequency_penalty:
                completion_kwargs["frequency_penalty"] = frequency_penalty
            if presence_penalty:
                completion_kwargs["presence_penalty"] = presence_penalty
            response = completion(**completion_kwargs)
            answer = json.loads(response.choices[0].model_dump_json())["message"][
                "content"
            ]
            # print(f"--- AUTOCOMPLETE DEBUG ---")
            # print(f"SYSTEM INSTRUCTIONS (full):\n{system_instructions}")
            # print(f"USER MESSAGE (full):\n{completion_kwargs['messages'][1]['content']}")
            # print(f"COMPLETION: {answer}")
            # print(f"--------------------------")
            return answer
        except Exception as e:
            error_type = _classify_error(e)
            send_error_alert(error_type=error_type, error_message=str(e), throttle_minutes=app_config.alert_throttle_minutes)
            if attempt_no == 0:
                mongo_util.insert_error_log(
                    "user", app_config.MONGO_URL,
                    {"error": error_type, "error_message": str(e), "uuid": uuid},
                )
            return get_chat_completion(
                character_description=character_description,
                event=event,
                event_effects=event_effects,
                context=context,
                incomplete_sentence=incomplete_sentence,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                frequency_penalty=frequency_penalty,
                include_event=include_event,
                attempt_no=attempt_no + 1,
                max_attempts=2,
                uuid=uuid,
            )


def remove_duplicated_completion(incomplete_sentence, completion):
    if not incomplete_sentence or not completion:
        return completion

    incomplete_sentence = incomplete_sentence.strip()
    completion = completion.strip()

    # Direct overlap
    if completion.lower().startswith(incomplete_sentence.lower()):
        overlapping_text = completion[len(incomplete_sentence) :]
        if overlapping_text and overlapping_text[0] in string.punctuation:
            return overlapping_text  # Keep punctuation as is
        return (
            overlapping_text.lstrip()
        )  # Strip leading spaces if not starting with punctuation

    # Completion is a subset of incomplete
    elif incomplete_sentence.endswith(completion):
        return ""

    # Non-direct overlap
    else:
        # Iterate from the longest possible overlap to overlaps of length 2
        for i in range(len(completion), 1, -1):
            if incomplete_sentence.endswith(completion[:i]):
                remaining_text = completion[i:]
                return remaining_text.lstrip()
        # No meaningful overlap found
        return completion


def normalize_spacing(text):
    if text is None:
        return None
    return " ".join(text.replace("\xa0", " ").replace("\t", " ").split())


def remove_prompt_words(text):
    if text is None:
        return None
    text = PROMPT_WORDS_PATTERN.sub("", text)
    return normalize_spacing(text)


def get_context_and_incomplete_sentence(text):
    """
    We feed into the model both the prior context for what was written and the current
    sentence to complete. This function splits those things.
    """
    if text is None or not isinstance(text, str):
        return "", ""

    sentences = SENTENCE_PATTERN.findall(text)

    # Strip whitespace from sentences
    sentences = [s.strip() for s in sentences if s.strip() != ""]

    if not sentences:
        return "", ""

    if len(sentences) == 1:
        if text.strip().endswith((".", "!", "?")):
            return sentences[0], ""
        else:
            return "", sentences[0]
    else:
        if text.strip().endswith((".", "!", "?")):
            context = " ".join(sentences[-app_config.context_sentences :])
            incomplete_sentence = ""
        else:
            context = " ".join(sentences[-app_config.context_sentences - 1 : -1])
            incomplete_sentence = sentences[-1]

    return normalize_spacing(context), normalize_spacing(incomplete_sentence)


def extract_complete_words(text):
    """
    Extracts complete words from the given text since sometimes the LLM returns
    incomplete words depending on tokens. But in practice, it is expensive to accurately check if a word is complete,
    so a simple heuristic is used:

    - If the immediate character before the last word is whitespace or punctuation, then the word is necessarily complete.
    - If the word is not necessarily complete, then it is assumed to be incomplete.
    - Note: This means in practice we often just delete the last word of the completion.

    EXAMPLES
    "I went to the store to buy some mil" -> "I went to the store to buy some"
    "I went to the store to buy some milk" -> "I went to the store to buy some"

    """
    if not text:
        return ""
    if text[-1] in string.whitespace + string.punctuation:
        return text.rstrip()
    return " ".join(text.split()[:-1])


@app.route("/save_completed_journal", methods=["POST"])
def save_completed_journal():
    """Handles saving the journal content and autocomplete statistics"""
    try:
        # Get journal data from request
        journal_data = request.get_json()
        if isinstance(journal_data, str):
            journal_data = {"content": journal_data}

        # Get stats with defaults
        stats = journal_data.get("autocomplete_stats", {})
        if not isinstance(stats, dict):
            raise ValueError("Invalid autocomplete_stats format")

        # Create complete stats dict with defaults
        complete_stats = {
            "received": stats.get("received", 0),
            "accepted": stats.get("accepted", 0),
            "rejected": stats.get("rejected", 0),
            "acceptance_rate": stats.get("acceptance_rate", 0),
        }

        # Get history with validation
        history = journal_data.get("autocomplete_history", [])
        if not isinstance(history, list):
            raise ValueError("Invalid autocomplete_history format")

        # Prefer event_id from the request body (baked in at page render time) to avoid
        # a race condition where a concurrent session overwrites session["event_id"]
        # before this journal is submitted.
        event_id = journal_data.get("event_id") if journal_data.get("event_id") else session.get("event_id")

        # Construct the data object
        data = {
            "uuid": session.get("uuid"),
            "timestamp": datetime.datetime.now(ZoneInfo("America/New_York")).isoformat(),
            "content": journal_data.get("content"),
            "autocomplete_stats": complete_stats,
            "autocomplete_history": history,
            "shown_to_user": session.get("shown_to_user"),
            "autocomplete_context": session.get("autocomplete_context"),
            "event_id": event_id,
        }

        print("Saving journal data:", data)

        # Save to database
        mongo_util.insert_journal_data_to_database("user", app_config.MONGO_URL, data)

        return (
            jsonify(
                {
                    "message": "Journal and statistics saved successfully",
                    "uuid": session.get("uuid"),
                }
            ),
            200,
        )

    except ValueError as e:
        print(f"Error saving journal: {str(e)}")
        return jsonify({"error": "Invalid data format", "details": str(e)}), 500
    except Exception as e:
        print(f"Error saving journal: {str(e)}")
        return jsonify({"error": "Failed to save journal", "details": str(e)}), 500


def get_shown_to_user_preface():
    """
    Determines the preface text to show to the user based on the following logic:
    1. If event-specific shown_to_user_prefix exists, use that
    2. If no event-specific prefix:
        - If shown_to_user_preface == "start", use "Imagine this is how it all starts:"
        - If shown_to_user_preface in ["plot", "effects", "plot_from_effects"], use "Imagine this is what happens:"
        - If shown_to_user_preface == "none", return "none" to skip display

    Returns:
        tuple: (preface_text, shown_to_user_text)
    """
    event_config = session.get("event_config")

    # If no event config, return defaults
    if not event_config:
        return ("none", "none")

    # Check if event-specific preface exists
    if "shown_to_user_prefix" in event_config:
        return (event_config["shown_to_user_prefix"], session.get("shown_to_user", ""))

    # Handle based on shown_to_user_preface setting
    shown_to_user = event_config.get(
        "shown_to_user", app_config.config["autocomplete"]["shown_to_user"]
    )

    if shown_to_user == "none":
        return ("none", "none")
    elif shown_to_user == "start":
        return ("Imagine this is how it all starts", session.get("shown_to_user", ""))
    elif shown_to_user in ["plot", "effects", "plot_from_effects"]:
        return ("Imagine this is what happens", session.get("shown_to_user", ""))
    else:
        return ("none", "none")


def get_editor_placeholder():
    """
    Get the editor placeholder text, either from event config or defaults.

    Args:
        event_config (dict): Event configuration dictionary

    Returns:
        str: The placeholder text to use
    """
    event_config = session.get("event_config")
    # print("EVENT CONFIG", event_config)
    if event_config and "editor_placeholder" in event_config:
        return event_config["editor_placeholder"]
    else:
        return app_config.editor_defaults["editor_placeholder"]


def delete_unused_generations():
    for var in [
        "event_effects",
        "start_of_event",
        "event_plot",
        "event_plot_from_effects",
    ]:
        if var in session:
            del session[var]


import sys


def get_size(obj, seen=None):
    """Recursively find the size of objects including nested objects."""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0  # Avoid double-counting the same object
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum((get_size(v, seen) for v in obj.values()))
        size += sum((get_size(k, seen) for k in obj.keys()))
    elif hasattr(obj, "__dict__"):
        size += get_size(vars(obj), seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        size += sum((get_size(i, seen) for i in obj))
    return size


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app_config.port, debug=not app_config.is_prod)
