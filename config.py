import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime as dt, timedelta
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv
from litellm import completion
from openai import OpenAI


class AppConfig:
    def __init__(self):
        load_dotenv()
        self.config = self.load_yaml_config("config.yaml")
        # print(self.config)
        self.hardcoded = self.config["hardcode_character_and_event"]
        self.hardcoded_character = self.config["hardcoded_character"]
        self.hardcoded_event = self.config["hardcoded_event"]
        self.experiment_enabled = self.config["enable_experiment"]
        self.default_experiment_event = self.config.get(
            "default_experiment_event", self.hardcoded_event
        )
        self.lab_mode = self.config.get("lab_mode", False)
        self.prompts = self.load_yaml_config("prompts.yaml")
        self.editor_defaults = self.config["editor_defaults"]

        # ################################
        # LLM settings
        # ################################

        # Default settings are for gpt models
        self.effects_generator_model = self.config["event"]["effects_generator_model"]
        self.model = self.config["llm"]["model"]
        self.temperature_range = (
            self.config["llm"]["temperature_min"],
            self.config["llm"]["temperature_max"],
        )
        self.token_range = (
            self.config["llm"]["max_tokens_min"],
            self.config["llm"]["max_tokens_max"],
        )
        self.frequency_penalty = self.config["llm"]["frequency_penalty"]
        self.presence_penalty = self.config["llm"]["presence_penalty"]
        self.max_attempts = self.config["llm"]["max_attempts"]
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")

        # Change settings for Anthropic
        # OPENAI temperature is in [0,2] and Anthropic is in [0,1]
        if "claude" in self.model.lower():
            self.frequency_penalty = None
            self.presence_penalty = None
            self.temperature_range = (
                min(self.config["llm"]["temperature_min"], 0),
                min(self.config["llm"]["temperature_max"], 1),
            )
            print(
                f"Anthropic model detected. Adjusting temperature range to {self.temperature_range}"
            )

        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            # if model has 'gpt' in it ensure openai key else if 'claude' enssure anthropic
            if "gpt" in self.model.lower() and not os.getenv("OPENAI_API_KEY"):
                raise ValueError(
                    f"{key} environment variable not set. "
                    f"To set it:\n"
                    f'- On macOS or Linux, use: export {key}="key"\n'
                    f'- On Windows (PowerShell), use: $env:{key}="key"'
                    f"\nReplace 'key' with your actual API key."
                )
            elif "claude" in self.model.lower() and not os.getenv("ANTHROPIC_API_KEY"):
                raise ValueError(
                    f"{key} environment variable not set. "
                    f"To set it:\n"
                    f'- On macOS or Linux, use: export {key}="key"\n'
                    f'- On Windows (PowerShell), use: $env:{key}="key"'
                    f"\nReplace 'key' with your actual API key."
                )

        # ################################
        # Character and event settings
        # ################################
        self.event_list = self.config["event"]
        if self.hardcoded:
            self.event = self.config["event"][self.hardcoded_event]
            self.character = self.config["characters"][self.hardcoded_character]

            # Use the hardcoded event's settings if they exist, otherwise use the default settings
            self.config["autocomplete"]["autocomplete_context"] = self.event_list[
                self.hardcoded_event
            ].get(
                "autocomplete_context",
                self.config["autocomplete"]["autocomplete_context"],
            )

            self.config["autocomplete"]["shown_to_user"] = self.event_list[
                self.hardcoded_event
            ].get("shown_to_user", self.config["autocomplete"]["shown_to_user"])

            add_dt = bool(self.event.get("add_current_date", False))

            self.character_description = self.construct_character_description(
                add_dt=add_dt
            )

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_dynamic_effects = executor.submit(self.get_dynamic_effects)
                future_start_of_event = executor.submit(self.get_start_of_event)
                event_effects = future_dynamic_effects.result()
                start_of_event = future_start_of_event.result()

            self.event_effects = event_effects
            self.start_of_event = start_of_event
            self.event_plot_from_effects = self.get_event_plot_from_effects(
                self.character_description,
                self.event,
                self.event_effects,
                self.start_of_event,
            )
            self.event_plot = self.get_event_plot(
                self.character_description,
                self.event,
                self.start_of_event,
            )

            # print(self.event_effects)
            # print(self.start_of_event)
            # print(self.event_plot)
            # print(self.event_plot_from_effects)

        elif self.experiment_enabled:
            self.event = None
            self.event_effects = None

        else:
            # raise NotImplementedError("Dynamic character and event creation is WIP")
            pass

        # ################################
        # Environment settings
        # ################################
        self.is_offline = self.config["app_is_offline"]
        self.port = int(os.environ.get("PORT", 5001))
        self.is_prod = os.environ.get("RAILWAY_ENVIRONMENT_NAME") is not None
        self.flask_secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(16)

        # ################################
        # Autocomplete behavior settings
        # ################################
        self.debounce_time = self.config["autocomplete"]["debounce_time"]
        self.alert_throttle_minutes = self.config["autocomplete"]["alert_throttle_minutes"]
        self.min_words = self.config["autocomplete"]["min_words"]
        self.min_sentences = self.config["autocomplete"]["min_sentences"]
        self.event_relevant = self.config["autocomplete"]["event_relevant"]
        self.stuck_prompts = self.config["stuck_prompts"]
        self.context_sentences = self.config["autocomplete"]["context_sentences"]
        self.autocomplete_context = self.config["autocomplete"]["autocomplete_context"]
        self.shown_to_user = self.config["autocomplete"]["shown_to_user"]
        assert self.min_sentences >= 1, "min_sentences must be at least 1"
        assert (
            self.event_relevant > 0 and self.event_relevant <= 1
        ), "min_sentences must be in (0, 1]"
        assert self.autocomplete_context in [
            "plot",
            "effects",
            "start",
            "plot_from_effects",
        ]
        assert self.shown_to_user in [
            "plot",
            "plot_from_effects",
            "effects",
            "start",
            "none",
        ]

        self.autocomplete_variable_map = {
            "plot": "event_plot",
            "effects": "event_effects",
            "start": "start_of_event",
            "plot_from_effects": "event_plot_from_effects",
            "none": "none",
        }
        self.client = OpenAI(api_key=self.openai_key)
        list2bullet = lambda x: (
            "\n- " + "\n- ".join(item.strip() for item in x)
        ).strip()
        self.event_constraints = list2bullet(self.prompts["constraints"])
        self.non_event_constraints = list2bullet(
            x for x in self.prompts["constraints"] if "{event}" not in x
        )

        # ################################
        # DB SETTING
        # ################################
        # If running app in deployed railway instance, get the corresponding mongodb endpoint
        # for staging or production.
        # Else direct to working stage endpoint.
        if os.environ.get("RAILWAY_ENVIRONMENT_NAME") is not None:
            self.MONGO_URL = os.environ.get("MONGO_URL")
        else:
            load_dotenv()
            self.MONGO_URL = os.environ.get("MONGO_WORKING_STAGE_URL")

        # ################################
        # Timer Setting
        # ################################
        self.timer_minutes = self.config["timer"]["minutes"]
        self.message_to_display_when_time_is_up = self.config["timer"][
            "message_to_display_when_time_is_up"
        ]
        self.message_when_under_min_words = self.config["timer"].get(
            "message_when_under_min_words",
            self.config["timer"]["message_to_display_when_time_is_up"],
        )

    def load_yaml_config(self, filepath):
        """Load configuration from a YAML file."""
        with open(filepath, "r") as ymlfile:
            return yaml.safe_load(ymlfile)

    def construct_character_description(self, add_dt=False):
        char_info = self.character
        base_fields = [
            "age",
            "gender",
            "occupation",
            "location",
        ]
        base_description = f"I am {char_info['age']} years old from {char_info['location']}, working as a {char_info['occupation']}. "

        additional_fields = [x for x in char_info.keys() if x not in base_fields]
        additional_info = ". ".join(
            f"My {k.replace('_', ' ')} is {v}"
            for k, v in char_info.items()
            if k in additional_fields
        )

        if add_dt:
            est_time = dt.now(ZoneInfo("America/New_York"))
            additional_info += (
                f"Context: It is currently {est_time.strftime('%A %Y-%m-%d')}"
            )

        if additional_info:
            return f"{base_description} {additional_info}."
        else:
            return base_description

    def get_dynamic_effects(self, attempt_no=0, max_attempts=2):
        if attempt_no > max_attempts:
            return None
        else:
            try:
                response = completion(
                    model=self.effects_generator_model,
                    messages=[
                        {
                            "role": "system",
                            "content": self.prompts["dynamic_effects"]["system"],
                        },
                        {
                            "role": "user",
                            "content": self.prompts["dynamic_effects"]["user"].format(
                                event_name=self.event["name"],
                                character_description=self.character_description,
                            ),
                        },
                    ],
                    temperature=0.6,
                    max_tokens=1000,
                    top_p=1,
                )
                answer = json.loads(response.choices[0].json())["message"]["content"]
                return answer
            except Exception as e:
                print(e)
                return self.get_dynamic_effects(attempt_no + 1, max_attempts)

    def get_start_of_event(self):
        response = completion(
            model=self.effects_generator_model,
            messages=[
                {
                    "role": "system",
                    "content": self.prompts["start_of_event"]["system"],
                },
                {
                    "role": "user",
                    "content": self.prompts["start_of_event"]["user"].format(
                        event_name=self.event["name"],
                        character_description=self.character_description,
                    ),
                },
            ],
            temperature=0.6,
            max_tokens=1000,
        )
        return json.loads(response.choices[0].json())["message"]["content"]

    def get_event_plot(self, character_description, event_name, event_start):
        response = completion(
            model=self.effects_generator_model,
            messages=[
                {
                    "role": "system",
                    "content": self.prompts["event_plot"]["system"],
                },
                {
                    "role": "user",
                    "content": self.prompts["event_plot"]["user"].format(
                        character_description=character_description,
                        event_name=event_name,
                        event_start=event_start,
                    ),
                },
            ],
        )
        return json.loads(response.choices[0].json())["message"]["content"]

    def get_event_plot_from_effects(
        self, character_description, event_name, event_effects, event_start
    ):
        response = completion(
            model=self.effects_generator_model,
            messages=[
                {
                    "role": "system",
                    "content": self.prompts["event_plot_from_effects"]["system"],
                },
                {
                    "role": "user",
                    "content": self.prompts["event_plot_from_effects"]["user"].format(
                        character_description=character_description,
                        event_name=event_name,
                        event_effects=event_effects,
                        event_start=event_start,
                    ),
                },
            ],
        )
        return json.loads(response.choices[0].json())["message"]["content"]
