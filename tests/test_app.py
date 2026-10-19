import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app import (
    save_form_data,
)
from forms import EventForm, create_character_form, BaseCharacterForm
from wtforms import StringField, SelectField

import unittest
from unittest.mock import patch
from app import (
    get_chat_completion,
    remove_duplicated_completion,
    normalize_spacing,
    get_context_and_incomplete_sentence,
    remove_prompt_words,
    extract_complete_words,
)

import os
import sys
from flask import session

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app import app, app_config, get_shown_to_user_preface, get_editor_placeholder


class TestPageLoads(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

    def test_user_setting_get(self):
        response = self.app.get("/user_settings")
        self.assertEqual(response.status_code, 200)

    def test_user_setting_experiment_get(self):
        response = self.app.get("/user_settings_experiment/example_1_minimal")
        self.assertEqual(response.status_code, 200)

    def test_user_setting_post_valid_data(self):
        """
        Test if the user_settings form is submitted with valid data. If this succeeds, we should not see 'text-danger' in the response.
        """
        data = {
            "age": 45,
            "gender": "man",
            "occupation": "mafia boss",
            "location": "Chicago",
            "event": "won the lottery",
            "prolific_id": "000000",
            "uuid": "test",
        }
        response = self.app.post("/user_settings", data=data, follow_redirects=True)
        self.assertNotIn(b"text-danger", response.data)
        self.assertEqual(response.status_code, 200)

    def test_user_setting_post_invalid_data(self):
        """
        Test if the user_settings form is re-rendered with invalid data. Desired behavior is:
        1. We should see 'text-danger' in the response.
        2. The status code should be 200 since template is re-rendered.
        """
        data = {
            "age": 45,
            "gender": "man",
            "occupation": "mafia boss",
            # Missing required location field
            "event": "won the lottery",
            "prolific_id": "000000",
        }
        response = self.app.post("/user_settings", data=data, follow_redirects=True)
        self.assertIn(b"This field is required.", response.data)
        self.assertIn(b"text-danger", response.data)
        self.assertEqual(response.status_code, 200)

    def test_user_setting_experiment_post_valid_data(self):
        """
        Test if the user_settings_experiment form is submitted with valid data. If this succeeds, we should not see 'text-danger' in the response.
        """
        data = {
            "age": 45,
            "gender": "man",
            "occupation": "mafia boss",
            "location": "Chicago",
            "event": "won the lottery",
            "political_ideology": "liberal",
            "prolific_id": "000000",
        }
        response = self.app.post(
            "/user_settings_experiment/example_1_minimal", data=data, follow_redirects=True
        )
        self.assertNotIn(b"text-danger", response.data)
        self.assertEqual(response.status_code, 200)

    def test_user_setting_experiment_post_invalid_data(self):
        """
        Test if the user_settings_experiment form is re-rendered with invalid data. Desired behavior is:
        1. We should see 'text-danger' in the response.
        2. The status code should be 200 since template is re-rendered.
        """
        data = {
            "age": 45,
            "gender": "man",
            "occupation": "mafia boss",
            "location": "Chicago",
            "personality": "2short",
            "event": "won the lottery",
            "prolific_id": "000000",
        }
        response = self.app.post(
            "/user_settings_experiment/example_5_split_context_and_date",
            data=data,
            follow_redirects=True,
        )
        self.assertIn(b"This field is required.", response.data)
        self.assertIn(b"text-danger", response.data)
        self.assertEqual(response.status_code, 200)

    def test_user_setting_experiment_auto_pid_from_query_param(self):
        """Visiting the experiment URL with ?pid=... should log auto_pid, even though
        the form's action URL (and thus the POST) doesn't carry the query string."""
        get_response = self.app.get(
            "/user_settings_experiment/example_1_minimal?pid=prolificd12i8484"
        )
        self.assertEqual(get_response.status_code, 200)

        with self.app.session_transaction() as sess:
            self.assertEqual(sess.get("auto_pid"), "prolificd12i8484")

        data = {
            "age": 45,
            "gender": "man",
            "occupation": "software developer",
            "location": "Chicago",
            "event": "won the lottery",
            "prolific_id": "000000",
            "political_ideology": "liberal",
        }
        response = self.app.post(
            "/user_settings_experiment/example_1_minimal", data=data, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)

        with self.app.session_transaction() as sess:
            self.assertEqual(
                sess.get("user_info")["auto_pid"], "prolificd12i8484"
            )

    def test_user_setting_experiment_uuid_persistence(self):
        """Test that uuid persists in session for user_settings_experiment"""
        # Mock session with uuid
        with self.app.session_transaction() as sess:
            sess["uuid"] = "test_uuid_123"

        # Now make a request
        data = {
            "age": 45,
            "gender": "man",
            "occupation": "software developer",
            "location": "Chicago",
            "event": "won the lottery",
            "prolific_id": "000000",
            "political_ideology": "liberal",
        }

        response = self.app.post(
            "/user_settings_experiment/example_1_minimal", data=data, follow_redirects=True
        )

        # Check the session after the request
        with self.app.session_transaction() as sess:
            self.assertEqual(sess.get("uuid"), "test_uuid_123")

            # Make sure the uuid in user info
            self.assertIn("user_info", sess)
            self.assertEqual(sess.get("user_info")["uuid"], "test_uuid_123")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"text-danger", response.data)

    def test_index_without_input(self):
        response = self.app.get("/index", follow_redirects=True)
        self.assertEqual(response.status_code, 200)


class TestDBConnection(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

    def test_db_insertion_experiment(self):
        """Test if data is correctly inserted into the database during an experiment."""
        form_data = {
            "age": 1,
            "gender": "woman",
            "occupation": "TEST",
            "location": "TEST",
            "prolific_id": "000000",
            "political_ideology": "liberal",
        }
        response = self.app.post(
            "/user_settings_experiment/example_1_minimal", data=form_data, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)


class TestAutocompleteFunctionality(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        app.config["TESTING"] = True

    def test_autocomplete_endpoint(self):
        with self.app.session_transaction() as sess:
            sess["character_description"] = "Test character"
            sess["event_name"] = "Test event"
            sess["event_plot"] = "Test story"
            sess["autocomplete_context"] = "context"

        response = self.app.post(
            "/autocomplete", json={"text": "This is a test sentence"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("completion", response.json)

    @patch("app.completion")
    def test_get_chat_completion(self, mock_completion):
        mock_completion.return_value.choices[0].model_dump_json.return_value = (
            '{"message": {"content": "Test completion"}}'
        )
        completion = get_chat_completion(
            character_description="Test character",
            event="Test event",
            event_effects="Test effects",
            context="Test context",
            incomplete_sentence="This is an incomplete",
            model="gpt-3.5-turbo",
            temperature=0.7,
            max_tokens=50,
            include_event=True,
        )
        self.assertIsInstance(completion, str)
        self.assertTrue(len(completion) > 0)


class TestTextProcessingFunctions(unittest.TestCase):
    def setUp(self):
        self.original_context_sentences = app_config.context_sentences

    def tearDown(self):
        app_config.context_sentences = self.original_context_sentences

    def test_context_handling(self):
        text = "This is sentence 1. This is sentence 2. This is sentence 3. This is sentence 4. This is sentence 5. This is an unfinished"

        test_cases = [
            (1, "This is sentence 5.", "This is an unfinished"),
            (2, "This is sentence 4. This is sentence 5.", "This is an unfinished"),
            (
                3,
                "This is sentence 3. This is sentence 4. This is sentence 5.",
                "This is an unfinished",
            ),
            (
                4,
                "This is sentence 2. This is sentence 3. This is sentence 4. This is sentence 5.",
                "This is an unfinished",
            ),
            (
                5,
                "This is sentence 1. This is sentence 2. This is sentence 3. This is sentence 4. This is sentence 5.",
                "This is an unfinished",
            ),
            (
                6,
                "This is sentence 1. This is sentence 2. This is sentence 3. This is sentence 4. This is sentence 5.",
                "This is an unfinished",
            ),
            (
                7,
                "This is sentence 1. This is sentence 2. This is sentence 3. This is sentence 4. This is sentence 5.",
                "This is an unfinished",
            ),
        ]

        for context_sentences, expected_context, expected_incomplete in test_cases:
            app_config.context_sentences = context_sentences
            context, incomplete = get_context_and_incomplete_sentence(text)
            context, incomplete = normalize_spacing(context), normalize_spacing(
                incomplete
            )

            self.assertEqual(
                expected_context,
                context,
                f"Failed for context_sentences={context_sentences}",
            )
            self.assertEqual(
                expected_incomplete,
                incomplete,
                f"Failed for context_sentences={context_sentences}",
            )

        # Test with no incomplete sentence
        text_complete = "This is sentence 1. This is sentence 2. This is sentence 3. This is sentence 4. This is sentence 5."
        app_config.context_sentences = 3
        context, incomplete = get_context_and_incomplete_sentence(text_complete)
        self.assertEqual(
            "This is sentence 3. This is sentence 4. This is sentence 5.", context
        )
        self.assertEqual("", incomplete)

    def test_exact_context_sentences(self):
        app_config.context_sentences = 3
        text = "Sentence 1. Sentence 2. Sentence 3. Incomplete"
        context, incomplete = get_context_and_incomplete_sentence(text)
        self.assertEqual(
            ("Sentence 1. Sentence 2. Sentence 3.", "Incomplete"), (context, incomplete)
        )

    def test_fewer_sentences_than_context(self):
        app_config.context_sentences = 5
        text = "Sentence 1. Sentence 2. Incomplete"
        context, incomplete = get_context_and_incomplete_sentence(text)
        self.assertEqual(
            ("Sentence 1. Sentence 2.", "Incomplete"), (context, incomplete)
        )

    def test_edge_cases(self):
        test_cases = [
            ("", ("", "")),
            (None, ("", "")),
            ("   ", ("", "")),
            (
                "This is a long sentence without any proper termination",
                ("", "This is a long sentence without any proper termination"),
            ),
            (
                "First sentence... Second sentence!!! Third sentence???",
                ("First sentence... Second sentence!!! Third sentence???", ""),
            ),
        ]
        for input_text, expected_output in test_cases:
            print("expected", input_text, expected_output)
            self.assertEqual(
                expected_output, get_context_and_incomplete_sentence(input_text)
            )

    def test_mixed_terminators(self):
        test_cases = [
            (
                "Statement. Question? Exclamation! Incomplete",
                ("Statement. Question? Exclamation!", "Incomplete"),
            ),
            ("First! Second? Third. Fourth", ("First! Second? Third.", "Fourth")),
        ]
        for input_text, expected_output in test_cases:
            self.assertEqual(
                expected_output, get_context_and_incomplete_sentence(input_text)
            )

    def test_normalize_spacing(self):
        test_cases = [
            ("Too   many    spaces", "Too many spaces"),
            ("Tabs\tand\tspaces", "Tabs and spaces"),
            ("New\nlines\nand\nspaces", "New lines and spaces"),
            ("  Mixture \t of\nspaces  ", "Mixture of spaces"),
            ("", ""),
            (None, None),
        ]
        for input_text, expected_output in test_cases:
            self.assertEqual(expected_output, normalize_spacing(input_text))

    def test_remove_prompt_words(self):
        test_cases = [
            (
                "INSTRUCTIONS: This is a test. CONTEXT: More text.",
                "This is a test. More text.",
            ),
            ("This is a normal sentence.", "This is a normal sentence."),
            (
                "INSTRUCTIONS CONTEXT CHARACTER DESCRIPTION EVENT EVENT EFFECTS",
                "EFFECTS",
            ),
            ("", ""),
            ("INSTRUCTIONS at the start", "at the start"),
            ("At the end CONTEXT", "At the end"),
            ("Mixed INSTRUCTIONS case CONTEXT words", "Mixed case words"),
            ("  INSTRUCTIONS:    with   extra   spaces  ", "with extra spaces"),
            ("INSTRUCTIONS:Test CONTEXT:Test", "Test Test"),
            ("No colon INSTRUCTIONS here", "No colon here"),
        ]
        for input_text, expected_output in test_cases:
            self.assertEqual(expected_output, remove_prompt_words(input_text))

    def test_extract_complete_words(self):
        test_cases = [
            ("These are complete words", "These are complete"),
            ("This is an incomple", "This is an"),
            ("This is a sentence.", "This is a sentence."),
            ("Word", ""),
            ("", ""),
            ("   ", ""),
            ("This is a sentence. Incomple", "This is a sentence."),
        ]
        for input_text, expected_output in test_cases:
            self.assertEqual(expected_output, extract_complete_words(input_text))

    def test_remove_duplicated_completion(self):
        test_cases = [
            # Direct overlap (same case)
            ("This is", "This is a test", "a test"),
            # Direct overlap (different case)
            ("this is", "This is a test", "a test"),
            # Completion is a subset of incomplete
            ("This is a test", "is a", "is a"),
            # Non-direct overlap
            ("This is a", "is a test", "test"),
            # Non-direct overlap last letter of incomplete is the same as first letter of completion
            ("There is a test", "tomorrow", "tomorrow"),
            # No overlap
            ("This is", "a test", "a test"),
            # Empty incomplete sentence
            ("", "This is a test", "This is a test"),
            # Empty completion
            ("This is", "", ""),
            # Both empty
            ("", "", ""),
            # Whitespace handling
            ("This is ", "is a test", "a test"),
            ("This is", " is a test", "a test"),
            # Punctuation
            ("This is a test", "test.", "."),
        ]

        for incomplete_sentence, completion, expected in test_cases:
            result = remove_duplicated_completion(incomplete_sentence, completion)
            self.assertEqual(
                expected,
                result,
                f"Failed for incomplete_sentence='{incomplete_sentence}', completion='{completion}'",
            )


class TestConfiguration(unittest.TestCase):
    def test_app_config(self):
        self.assertIsInstance(app_config.debounce_time, int)
        self.assertIsInstance(app_config.min_sentences, int)
        self.assertIsInstance(app_config.event_relevant, float)
        self.assertTrue(0 < app_config.event_relevant <= 1)


class TestErrorHandling(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        app.config["TESTING"] = True

    def test_invalid_autocomplete_request(self):
        response = self.app.post("/autocomplete", json={})
        self.assertEqual(response.status_code, 400)

    def test_nonexistent_route(self):
        response = self.app.get("/nonexistent_route")
        self.assertEqual(response.status_code, 404)


class TestSaveFormData(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.app.config["SECRET_KEY"] = "test_secret_key"
        self.client = self.app.test_client()

    def test_save_form_data_with_hardcoded_event(self):
        with self.app.test_request_context():
            form_data = {
                "age": 30,
                "gender": "man",
                "occupation": "teacher",
                "location": "New York",
            }
            character_form = BaseCharacterForm(data=form_data)
            hardcoded_event = "Hardcoded Test Event"

            save_form_data(character_form, hardcoded_event=hardcoded_event)

            self.assertIn("user_info", session)
            user_info = session["user_info"]

            for key, value in form_data.items():
                self.assertEqual(user_info[key], value)
            self.assertEqual(user_info["event"], "Hardcoded Test Event")

    def test_save_form_data_with_event_form(self):
        with self.app.test_request_context():
            character_data = {
                "age": 25,
                "gender": "woman",
                "occupation": "engineer",
                "location": "San Francisco",
            }
            character_form = BaseCharacterForm(data=character_data)
            event_form = EventForm(data={"event": "Test Event"})

            save_form_data(character_form, event_form)

            self.assertIn("user_info", session)
            user_info = session["user_info"]

            for key, value in character_data.items():
                self.assertEqual(user_info[key], value)
            self.assertEqual(user_info["event"], "Test Event")

    def test_save_form_data_one_char_field_null(self):
        with self.app.test_request_context():
            character_data = {
                "age": 25,
                "gender": "woman",
                "occupation": "engineer",
                "location": "San Francisco",
            }
            character_form = BaseCharacterForm(data=character_data)
            event_form = EventForm(data={"event": "Test Event"})

            save_form_data(character_form, event_form)

            self.assertIn("user_info", session)
            user_info = session["user_info"]

            for key, value in character_data.items():
                self.assertEqual(user_info[key], value)
            self.assertEqual(user_info["event"], "Test Event")

    def test_save_form_data_no_event(self):
        with self.app.test_request_context():
            form_data = {
                "age": 35,
                "gender": "non-binary",
                "occupation": "artist",
                "location": "London",
            }
            character_form = BaseCharacterForm(data=form_data)

            with self.assertRaises(ValueError):
                save_form_data(character_form)


class TestDynamicFormGeneration(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.app_context = self.app.app_context()
        self.app_context.push()

        self.mock_config = {
            "event_1": {
                "additional_fields": {
                    "political_ideology": {
                        "type": "SelectField",
                        "label": "What is your political ideology?",
                        "choices": ["liberal", "conservative"],
                        "validators": ["DataRequired"],
                    },
                    "favorite_color": {
                        "type": "StringField",
                        "label": "What is your favorite color?",
                        "validators": ["DataRequired"],
                    },
                }
            },
            "event_2": {},  # No additional fields
        }

    def tearDown(self):
        self.app_context.pop()

    def test_base_character_form_fields(self):
        """Verifies that the BaseCharacterForm has all the expected fields."""
        with self.app.test_request_context():
            form = BaseCharacterForm()
            expected_fields = [
                "prolific_id",
                "age",
                "gender",
                "occupation",
                "location",
            ]
            for field in expected_fields:
                self.assertTrue(
                    hasattr(form, field),
                    f"BaseCharacterForm is missing the {field} field",
                )

    def test_gender_field_is_select_field(self):
        """Ensures that the gender field is a SelectField with correct choices including default option."""
        with self.app.test_request_context():
            form = BaseCharacterForm()
            self.assertIsInstance(form.gender, SelectField)
            expected_choices = [
                (None, "Select an option..."),
                ("woman", "Woman"),
                ("man", "Man"),
                ("non-binary", "Non-binary"),
                ('prefer not to disclose', 'Prefer not to disclose'),
                ("other", "Other"),
            ]
            self.assertEqual(form.gender.choices, expected_choices)

    def test_create_character_form_with_additional_fields(self):
        """Verifies that a form is created with the correct additional fields for a specific event."""
        with self.app.test_request_context():
            form = create_character_form(self.mock_config, "event_1")
            self.assertIsInstance(form, BaseCharacterForm)
            self.assertTrue(hasattr(form, "political_ideology"))
            self.assertTrue(hasattr(form, "favorite_color"))
            self.assertIsInstance(form.political_ideology, SelectField)
            self.assertIsInstance(form.favorite_color, StringField)

    def test_create_character_form_without_additional_fields(self):
        """Ensures that a form is created without additional fields when none are specified for an event."""
        with self.app.test_request_context():
            form = create_character_form(self.mock_config, "event_2")
            self.assertIsInstance(form, BaseCharacterForm)
            self.assertFalse(hasattr(form, "political_ideology"))
            self.assertFalse(hasattr(form, "favorite_color"))

    def test_form_validation_with_additional_fields(self):
        """Checks that form validation passes when all required fields, including additional ones, are provided."""
        with self.app.test_request_context():
            form = create_character_form(self.mock_config, "event_1")
            form.process(
                data={
                    "prolific_id": "TEST123",
                    "age": 30,
                    "gender": "woman",
                    "occupation": "engineer",
                    "location": "New York",
                    "political_ideology": "liberal",
                    "favorite_color": "blue",
                }
            )
            self.assertTrue(form.validate())

    def test_form_validation_with_missing_additional_fields(self):
        """Verifies that form validation fails when required additional fields are missing."""
        with self.app.test_request_context():
            form = create_character_form(self.mock_config, "event_1")
            form.process(
                data={
                    "prolific_id": "TEST123",
                    "age": 30,
                    "gender": "woman",
                    "occupation": "engineer",
                    "location": "New York",
                    # Missing political_ideology and favorite_color
                }
            )
            self.assertFalse(form.validate())

    def test_select_field_additional_fields_choices(self):
        """Verifies that the SelectField for political ideology has the correct choices including default option."""
        with self.app.test_request_context():
            form = create_character_form(self.mock_config, "event_1")
            expected_choices = [
                (None, "Select an option..."),
                ("liberal", "liberal"),
                ("conservative", "conservative")
            ]
            self.assertEqual(form.political_ideology.choices, expected_choices)

    def test_select_field_default_value(self):
        """Verifies that SelectFields start with None as their default value."""
        with self.app.test_request_context():
            form = create_character_form(self.mock_config, "event_1")
            self.assertIsNone(form.political_ideology.data)
            form = BaseCharacterForm()
            self.assertIsNone(form.gender.data)

    def test_select_field_default_option_validation(self):
        """Verifies that the default 'Select an option...' cannot be submitted as a valid choice."""
        with self.app.test_request_context():
            form = create_character_form(self.mock_config, "event_1")

            # Test with default option
            form.process(data={
                "prolific_id": "TEST123",
                "age": 30,
                "gender": "woman",
                "occupation": "engineer",
                "location": "New York",
                "political_ideology": None,  # Default "Select an option..."
                "favorite_color": "blue"
            })
            self.assertFalse(form.validate())
            self.assertIn("political_ideology", form.errors)

            # Test with valid option
            form.process(data={
                "prolific_id": "TEST123",
                "age": 30,
                "gender": "woman",
                "occupation": "engineer",
                "location": "New York",
                "political_ideology": "liberal",  # Valid choice
                "favorite_color": "blue"
            })
            self.assertTrue(form.validate())
            self.assertNotIn("political_ideology", form.errors)

    def test_validation_with_default_option(self):
        """Verifies that validation fails when the default 'Select an option...' is submitted."""
        with self.app.test_request_context():
            form = create_character_form(self.mock_config, "event_1")
            form.process(
                data={
                    "prolific_id": "TEST123",
                    "age": 30,
                    "gender": None,  # Default option
                    "occupation": "engineer",
                    "location": "New York",
                    "political_ideology": None,  # Default option
                    "favorite_color": "blue",
                }
            )
            self.assertFalse(form.validate())

class TestPrefacesAndPlaceholders(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.ctx = app.test_request_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    # Tests for prefixes
    def test_custom_prefix(self):
        """Event-specific prefix should be used if present"""
        session["event_config"] = {
            "shown_to_user_prefix": "Consider this voting plan",
        }
        session["shown_to_user"] = "Test text"

        preface, text = get_shown_to_user_preface()
        self.assertEqual(preface, "Consider this voting plan")
        self.assertEqual(text, "Test text")

    def test_start_prefix(self):
        """'start' should translate to 'Imagine this is how it all starts'"""
        session["event_config"] = {"shown_to_user": "start"}
        session["shown_to_user"] = "Test text"
        app_config.shown_to_user = "start"

        preface, text = get_shown_to_user_preface()
        self.assertEqual(preface, "Imagine this is how it all starts")
        self.assertEqual(text, "Test text")

    def test_plot_prefix(self):
        """'plot' should translate to 'Imagine this is what happens'"""
        session["event_config"] = {"shown_to_user": "plot"}
        session["shown_to_user"] = "Test text"
        app_config.shown_to_user = "plot"

        preface, text = get_shown_to_user_preface()
        self.assertEqual(preface, "Imagine this is what happens")
        self.assertEqual(text, "Test text")

    def test_effects_prefix(self):
        """'effects' should translate to 'Imagine this is what happens'"""
        session["event_config"] = {"shown_to_user": "effects"}
        session["shown_to_user"] = "Test text"
        app_config.shown_to_user = "effects"

        preface, text = get_shown_to_user_preface()
        self.assertEqual(preface, "Imagine this is what happens")
        self.assertEqual(text, "Test text")

    def test_plot_from_effects_prefix(self):
        """'plot_from_effects' should translate to 'Imagine this is what happens'"""
        session["event_config"] = {"shown_to_user": "plot_from_effects"}
        session["shown_to_user"] = "Test text"
        app_config.shown_to_user = "plot_from_effects"

        preface, text = get_shown_to_user_preface()
        self.assertEqual(preface, "Imagine this is what happens")
        self.assertEqual(text, "Test text")

    def test_none_prefix(self):
        """'none' should return none values"""
        session["event_config"] = {"shown_to_user": "none"}
        app_config.shown_to_user = "none"

        preface, text = get_shown_to_user_preface()
        self.assertEqual(preface, "none")
        self.assertEqual(text, "none")

    def test_no_event_config_prefix(self):
        """Missing event config should return none values"""
        if "event_config" in session:
            del session["event_config"]

        preface, text = get_shown_to_user_preface()
        self.assertEqual(preface, "none")
        self.assertEqual(text, "none")

    # Tests for placeholders
    def test_custom_placeholder(self):
        """Custom placeholder from event config should be used if present"""
        session["event_config"] = {"editor_placeholder": "Custom placeholder text"}

        placeholder = get_editor_placeholder()
        self.assertEqual(placeholder, "Custom placeholder text")

    def test_default_placeholder(self):
        """Default placeholder should be used when no custom one in event config"""
        session["event_config"] = {}  # Empty config

        expected_default = app_config.editor_defaults["editor_placeholder"]
        placeholder = get_editor_placeholder()
        self.assertEqual(placeholder, expected_default)

    def test_no_event_config_placeholder(self):
        """Default placeholder should be used when no event config exists"""
        if "event_config" in session:
            del session["event_config"]

        expected_default = app_config.editor_defaults["editor_placeholder"]
        placeholder = get_editor_placeholder()
        self.assertEqual(placeholder, expected_default)

    # Test combinations
    def test_custom_prefix_and_placeholder(self):
        """Both custom prefix and placeholder should work together"""
        session["event_config"] = {
            "shown_to_user_prefix": "Consider this voting plan",
            "editor_placeholder": "Custom placeholder text",
        }
        session["shown_to_user"] = "Test text"

        preface, text = get_shown_to_user_preface()
        placeholder = get_editor_placeholder()

        self.assertEqual(preface, "Consider this voting plan")
        self.assertEqual(text, "Test text")
        self.assertEqual(placeholder, "Custom placeholder text")


class TestAutocompleteTracking(unittest.TestCase):
    def setUp(self):
        """Set up test client and configure test environment"""
        self.app = app.test_client()
        app.config["TESTING"] = True
        self.test_uuid = "test-uuid-123"

        # Sample journal data with complete tracking
        self.test_journal_data = {
            "content": "I went to the store. Then I walked home.",
            "timestamp": "2024-10-30T10:00:00Z",
            "autocomplete_stats": {
                "received": 2,
                "accepted": 1,
                "rejected": 1,
                "acceptance_rate": 50.00,
            },
            "autocomplete_history": [
                {
                    "timestamp": "2024-10-30T09:59:00Z",
                    "suggestion_text": "to the store",
                    "status": "accepted",
                    "position_in_text": 6,
                }
            ],
        }

    def test_save_complete_journal(self):
        """Test saving journal with all tracking data"""
        with self.app.session_transaction() as sess:
            sess["uuid"] = self.test_uuid
            sess["shown_to_user"] = "test shown"
            sess["autocomplete_context"] = "test context"

        with patch("mongo_util.insert_journal_data_to_database") as mock_db:
            response = self.app.post(
                "/save_completed_journal", json=self.test_journal_data
            )

            self.assertEqual(response.status_code, 200)
            saved_data = mock_db.call_args[0][2]

            # Verify core data
            self.assertEqual(saved_data["uuid"], self.test_uuid)
            self.assertEqual(saved_data["content"], self.test_journal_data["content"])
            self.assertEqual(saved_data["shown_to_user"], "test shown")
            self.assertEqual(saved_data["autocomplete_context"], "test context")

            # Verify stats
            self.assertDictEqual(
                saved_data["autocomplete_stats"],
                self.test_journal_data["autocomplete_stats"],
            )

            # Verify history
            self.assertEqual(
                saved_data["autocomplete_history"],
                self.test_journal_data["autocomplete_history"],
            )

    def test_save_journal_with_invalid_stats(self):
        """Test saving journal with invalid stats format"""
        invalid_data = {
            "content": "Test content",
            "autocomplete_stats": "invalid",  # Not a dict
            "autocomplete_history": [],
        }

        with self.app.session_transaction() as sess:
            sess["uuid"] = self.test_uuid

        response = self.app.post("/save_completed_journal", json=invalid_data)

        self.assertEqual(response.status_code, 500)
        self.assertIn("Invalid data format", response.get_json()["error"])

    def test_save_journal_with_invalid_history(self):
        """Test saving journal with invalid history format"""
        invalid_data = {
            "content": "Test content",
            "autocomplete_stats": {"received": 1},
            "autocomplete_history": "invalid",  # Not a list
        }

        with self.app.session_transaction() as sess:
            sess["uuid"] = self.test_uuid

        response = self.app.post("/save_completed_journal", json=invalid_data)

        self.assertEqual(response.status_code, 500)
        self.assertIn("Invalid data format", response.get_json()["error"])

    def test_save_journal_with_partial_stats(self):
        """Test saving journal with incomplete stats"""
        partial_data = {
            "content": "Test content",
            "autocomplete_stats": {
                "received": 1
                # Missing other stats
            },
            "autocomplete_history": [],
        }

        with self.app.session_transaction() as sess:
            sess["uuid"] = self.test_uuid

        with patch("mongo_util.insert_journal_data_to_database") as mock_db:
            response = self.app.post("/save_completed_journal", json=partial_data)

            self.assertEqual(response.status_code, 200)
            saved_data = mock_db.call_args[0][2]

            # Verify stats were completed with defaults
            stats = saved_data["autocomplete_stats"]
            self.assertEqual(stats["received"], 1)  # Original value preserved
            self.assertEqual(stats["accepted"], 0)  # Default
            self.assertEqual(stats["rejected"], 0)  # Default
            self.assertEqual(stats["acceptance_rate"], 0)  # Default

    def test_save_string_content(self):
        """Test saving when only string content is provided"""
        with self.app.session_transaction() as sess:
            sess["uuid"] = self.test_uuid

        with patch("mongo_util.insert_journal_data_to_database") as mock_db:
            response = self.app.post(
                "/save_completed_journal", json="Simple text content"
            )

            self.assertEqual(response.status_code, 200)
            saved_data = mock_db.call_args[0][2]

            # Verify basic structure
            self.assertEqual(saved_data["content"], "Simple text content")
            self.assertIn("autocomplete_stats", saved_data)
            self.assertIn("autocomplete_history", saved_data)

            # Verify default stats
            stats = saved_data["autocomplete_stats"]
            for key in ["received", "accepted", "rejected", "acceptance_rate"]:
                self.assertEqual(stats[key], 0)

            # Verify empty history
            self.assertEqual(saved_data["autocomplete_history"], [])


class TestErrorAlert(unittest.TestCase):
    def setUp(self):
        import alert
        alert._last_alert_sent = None
        os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/test"

    def tearDown(self):
        import alert
        alert._last_alert_sent = None
        os.environ.pop("SLACK_WEBHOOK_URL", None)

    @patch("alert.requests.post")
    def test_posts_to_slack_with_error_type_and_message(self, mock_post):
        from alert import send_error_alert
        self.assertTrue(send_error_alert(error_type="RATE_LIMITED", error_message="quota exceeded"))
        mock_post.assert_called_once_with(
            "https://hooks.slack.com/test",
            json={"text": "RATE_LIMITED error in autocomplete.\nquota exceeded"},
        )

    @patch("alert.requests.post")
    def test_posts_without_message(self, mock_post):
        from alert import send_error_alert
        self.assertTrue(send_error_alert(error_type="RATE_LIMITED"))
        mock_post.assert_called_once_with(
            "https://hooks.slack.com/test",
            json={"text": "RATE_LIMITED error in autocomplete."},
        )

    @patch("alert.requests.post")
    def test_throttle_suppresses_repeat(self, mock_post):
        from alert import send_error_alert
        self.assertTrue(send_error_alert())
        self.assertFalse(send_error_alert())
        self.assertEqual(mock_post.call_count, 1)

    @patch("alert.requests.post")
    def test_fires_after_throttle_expires(self, mock_post):
        import alert, time as _time
        from alert import send_error_alert
        alert._last_alert_sent = _time.time() - 16 * 60
        self.assertTrue(send_error_alert())

    def test_missing_webhook_returns_false(self):
        from alert import send_error_alert
        os.environ.pop("SLACK_WEBHOOK_URL", None)
        self.assertFalse(send_error_alert())

    def test_real_slack_alert(self):
        """Sends a real Slack message using SLACK_WEBHOOK_URL from .env. Skips if not set."""
        from dotenv import load_dotenv
        load_dotenv(override=True)
        import alert
        alert._last_alert_sent = None
        url = os.getenv("SLACK_WEBHOOK_URL")
        if not url or "hooks.slack.com/test" in url:
            self.skipTest("Real SLACK_WEBHOOK_URL not set in .env")
        from alert import send_error_alert
        self.assertTrue(send_error_alert(error_type="TEST", throttle_minutes=0))


class TestErrorClassification(unittest.TestCase):
    def test_rate_limit_classified(self):
        import httpx
        from litellm.exceptions import RateLimitError
        from app import _classify_error
        e = RateLimitError(
            "limit", llm_provider="openai", model="gpt-4o",
            response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
        )
        self.assertEqual(_classify_error(e), "RATE_LIMITED")

    def test_generic_error_uppercased(self):
        from app import _classify_error
        self.assertEqual(_classify_error(ValueError("oops")), "VALUEERROR")


class TestAutocompleteAlerting(unittest.TestCase):
    def _make_rate_limit_error(self):
        import httpx
        from litellm.exceptions import RateLimitError
        return RateLimitError(
            "Rate limit exceeded", llm_provider="openai", model="gpt-4o",
            response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
        )

    def _call(self, **kwargs):
        defaults = dict(
            character_description="char", event="event", event_effects="effects",
            context="ctx", incomplete_sentence="incomplete",
            model="gpt-4o", temperature=0.7, max_tokens=50, include_event=True,
        )
        defaults.update(kwargs)
        return get_chat_completion(**defaults)

    @patch("app.send_error_alert")
    @patch("app.completion")
    def test_any_error_triggers_alert(self, mock_completion, mock_alert):
        mock_completion.side_effect = ValueError("some error")
        self._call()
        mock_alert.assert_called()

    @patch("app.send_error_alert")
    @patch("app.completion")
    def test_rate_limit_passes_correct_type(self, mock_completion, mock_alert):
        mock_completion.side_effect = self._make_rate_limit_error()
        self._call()
        call_kwargs = mock_alert.call_args
        self.assertEqual(call_kwargs.kwargs["error_type"], "RATE_LIMITED")


if __name__ == "__main__":
    unittest.main()
