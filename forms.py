import wtforms
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, TextAreaField, SelectField
from wtforms.validators import DataRequired, NumberRange, Length


class NoneSelectField(SelectField):
    """Custom SelectField that converts 'None' strings to None during processing"""
    def process_formdata(self, valuelist):
        if valuelist and valuelist[0] == 'None':
            self.data = None
        else:
            super().process_formdata(valuelist)


class BaseCharacterForm(FlaskForm):
    prolific_id = StringField(
        "Uniqname",
        validators=[DataRequired(), Length(max=500)],
        render_kw={"placeholder": "Enter your Uniqname (if UM student) or Prolific ID (if on Prolific)"},
    )

    age = IntegerField(
        "Age",
        validators=[DataRequired(), NumberRange(min=0, max=120)],
        render_kw={"placeholder": "What is your age?"},
    )
    gender = NoneSelectField(
        "Gender",
        choices=[
            (None, "Select an option..."),
            ("woman", "Woman"),
            ("man", "Man"),
            ("non-binary", "Non-binary"),
            ("prefer not to disclose", "Prefer not to disclose"),
            ("other", "Other"),

        ],
        validators=[DataRequired()],
        render_kw={"placeholder": "What gender do you identify as?"},
        default=None
    )
    occupation = StringField(
        "Occupation",
        validators=[DataRequired(), Length(max=100)],
        render_kw={
            "placeholder": "What do you do for work? Ex: full-time student, work at library, tutor"
        },
    )
    location = StringField(
        "Location",
        validators=[DataRequired()],
        render_kw={
            "placeholder": "What (city, state) or (town, state) do you live in or near? Ex: Ann Arbor, Michigan"
        },
    )

    # personality = TextAreaField(
    #     "Personality",
    #     validators=[DataRequired(), Length(min=10)],
    #     render_kw={
    #         "placeholder": "What are you like as a person? Think of how your friends would describe you or some "
    #         "adjectives you identify with. Ex: introverted/extroverted, organized/disorganized, "
    #         "anxious/calm, open-minded/closed-minded, agreeable/disagreeable"
    #     },
    # )


def create_character_form(config, experiment_key=None):
    """
    This function dynamically creates a form class based on a base character form and additional fields specified in a configuration.

    Args:
        config (dict): The configuration dictionary that contains the additional fields for the form.
        experiment_key (str): The key of the experiment in the configuration dictionary.

    Returns:
        CharacterForm: A new form class that inherits from BaseCharacterForm and contains the additional fields specified in the configuration
    """

    # Create a new form class that inherits from BaseCharacterForm
    class CharacterForm(BaseCharacterForm):
        pass

    # Checks if experiment_key is in the event configuration, which
    # is a dictionary that contains the additional fields for each keyed event (e.g: event_1 etc)
    if experiment_key and experiment_key in config:
        event_config = config[experiment_key]
        # Check if there are additional fields for this experiment since sometimes there arent
        if "additional_fields" in event_config:
            # Iterate through each additional field
            for field_name, field_config in event_config["additional_fields"].items():
                if "hidden_value" in field_config:
                    setattr(
                        CharacterForm,
                        field_name,
                        wtforms.HiddenField(default=field_config["hidden_value"]),
                    )
                    continue

                if "override_placeholder" in field_config or "override_label" in field_config:
                    existing = getattr(CharacterForm, field_name, None)
                    if existing:
                        original_counter = existing.creation_counter
                        rk = dict(existing.kwargs.get("render_kw", {}) or {})
                        if "override_placeholder" in field_config:
                            rk["placeholder"] = field_config["override_placeholder"]
                        new_args = list(existing.args)
                        if "override_label" in field_config and new_args:
                            new_args[0] = field_config["override_label"]
                        new_field = existing.field_class(
                            *new_args,
                            **{**existing.kwargs, "render_kw": rk},
                        )
                        new_field.creation_counter = original_counter
                        setattr(CharacterForm, field_name, new_field)
                    continue

                # Get the WTForms field type (e.g., StringField, IntegerField)
                field_type = getattr(wtforms, field_config["type"])

                # Creates validator objects based on the configuration---handles both simple and complex validators
                # Simple validators are specified as strings, complex validators are specified as dictionaries with arguments
                # For example, {"Length": {"min": 5}} would create a Length validator with a minimum length of 5
                validators = []
                for v in field_config.get("validators", []):
                    if isinstance(v, str):
                        # If the validator is a string, get the corresponding WTForms validator
                        validators.append(getattr(wtforms.validators, v)())
                    elif isinstance(v, dict):
                        # If the validator is a dict, it includes arguments
                        validator_name = list(v.keys())[0]
                        validator_args = v[validator_name]
                        # Create the validator with its arguments
                        validators.append(
                            getattr(wtforms.validators, validator_name)(
                                **validator_args
                            )
                        )

                # This dynamically adds new fields to the CharacterForm class.
                # Handle SelectField differently as it requires choices to be specified
                if field_config["type"] == "SelectField":
                    # Create choices list with empty first choice
                    choices_list = [(None, "Select an option...")] + [
                        (choice, choice) for choice in field_config["choices"]
                    ]

                    setattr(
                        CharacterForm,
                        field_name,
                        NoneSelectField(  # Use custom SelectField
                            field_config["label"],
                            choices=choices_list,
                            validators=validators,
                            default=None,
                        ),
                    )
                else:
                    # For other field types, create the field with label and validators
                    setattr(
                        CharacterForm,
                        field_name,
                        field_type(field_config["label"], validators=validators),
                    )

    # Return an instance of the created form
    return CharacterForm()


class EventForm(FlaskForm):
    event = TextAreaField(
        "Event",
        validators=[DataRequired(), Length(min=5)],
        render_kw={
            "placeholder": "What is the event that should happen? Ex: winning the lottery, crippling medical debt"
        },
    )