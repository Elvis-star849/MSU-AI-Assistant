"""Optional second model (GROQ_MODEL_2): configuration, explicit selection, errors and unchanged RAG (offline, no Groq).

Run from the project root: python -m unittest tests.test_model_selection -v
"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.assistant import ACCEPTED_GENERATION, ACCEPTED_MODEL, Assistant, generation_settings, selected_model_env
from src.llm import LLMConfig, ModelSelectionError, load_config
from src.llm.base import GenerationSettings

FAKE_KEY = "gsk_FAKEFAKEFAKEFAKEFAKE0123456789"
SECOND = "second-model-for-tests"          # any identifier: the selection logic must not depend on model names
ENV = {"GROQ_API_KEY": FAKE_KEY, "GROQ_MODEL": "openai/gpt-oss-20b", "GROQ_MODEL_2": SECOND}


class ConfigTests(unittest.TestCase):
    def test_second_model_is_read(self):
        c = load_config(ENV, dotenv_path=None, model_env="GROQ_MODEL_2")
        self.assertEqual((c.settings.model, c.model_env), (SECOND, "GROQ_MODEL_2"))

    def test_default_is_unchanged(self):
        c = load_config(ENV, dotenv_path=None)
        self.assertEqual((c.settings.model, c.model_env), ("openai/gpt-oss-20b", "GROQ_MODEL"))
        self.assertEqual(load_config({}, dotenv_path=None).settings.model, "openai/gpt-oss-20b")

    def test_explicit_selection_switches_only_the_model(self):
        a = load_config({**ENV, "LLM_TEMPERATURE": "0.2"}, dotenv_path=None)
        b = load_config({**ENV, "LLM_TEMPERATURE": "0.2"}, dotenv_path=None, model_env="GROQ_MODEL_2")
        self.assertEqual(b.settings, a.settings.with_changes(model=SECOND))

    def test_missing_optional_variable_does_not_affect_default(self):
        env = {k: v for k, v in ENV.items() if k != "GROQ_MODEL_2"}
        self.assertEqual(load_config(env, dotenv_path=None).settings.model, "openai/gpt-oss-20b")

    def test_explicit_selection_of_missing_variable_is_an_error(self):
        env = {k: v for k, v in ENV.items() if k != "GROQ_MODEL_2"}
        for value in (None, "", "   "):
            e = env if value is None else {**env, "GROQ_MODEL_2": value}
            with self.assertRaises(ModelSelectionError) as ctx:
                load_config(e, dotenv_path=None, model_env="GROQ_MODEL_2")
            self.assertIn("GROQ_MODEL_2", str(ctx.exception))

    def test_invalid_variable_name_is_an_error(self):
        for name in ("GROQ_API_KEY", "groq_model_2", "GROQ_MODEL_X", "PATH"):
            with self.assertRaises(ModelSelectionError) as ctx:
                load_config(ENV, dotenv_path=None, model_env=name)
            self.assertIn("unknown model variable", str(ctx.exception))
        self.assertTrue(issubclass(ModelSelectionError, ValueError))

    def test_dotenv_file_is_read_for_the_second_model(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"GROQ_API_KEY={FAKE_KEY}\nGROQ_MODEL_2={SECOND}\n")
            self.assertEqual(load_config({}, dotenv_path=path, model_env="GROQ_MODEL_2").settings.model, SECOND)
            self.assertEqual(load_config({}, dotenv_path=path).settings.model, "openai/gpt-oss-20b")

    def test_credentials_are_not_exposed(self):
        c = load_config(ENV, dotenv_path=None, model_env="GROQ_MODEL_2")
        self.assertNotIn(FAKE_KEY, repr(c))
        self.assertNotIn(FAKE_KEY, str(c.settings.to_record()))
        with self.assertRaises(ModelSelectionError) as ctx:
            load_config({"GROQ_API_KEY": FAKE_KEY}, dotenv_path=None, model_env="GROQ_MODEL_2")
        self.assertNotIn(FAKE_KEY, str(ctx.exception))


class StubRetriever:
    def __init__(self, configuration):
        self.configuration = configuration
        self._store = SimpleNamespace(records=[])

    def _load(self):
        pass

    def retrieve(self, question):
        return []


class AssistantSelectionTests(unittest.TestCase):
    shared = StubRetriever("profile")        # the profile retriever both models must share

    def create(self, model_env=None, env=ENV, profile="c3_public_0005"):
        loader = lambda model_env=None: load_config(env, dotenv_path=None, model_env=model_env)
        shared = self.shared
        with patch("src.evidence.Stage6Retriever", StubRetriever), \
                patch("src.assistant.open_profile_retriever", lambda profile, models: shared), \
                patch("src.ambiguity.code_titles", lambda records: {}), \
                patch("src.ambiguity.ambiguous_codes", lambda titles: {}), \
                patch.dict(os.environ, {"MSU_ASSISTANT_MODEL_ENV": ""}):
            return Assistant.create(config_loader=loader, profile=profile, model_env=model_env)

    def test_default_app_model_is_the_accepted_model(self):
        a = self.create()
        self.assertEqual(a.settings.model, ACCEPTED_MODEL)
        self.assertEqual({k: getattr(a.settings, k) for k in ACCEPTED_GENERATION}, ACCEPTED_GENERATION)

    def test_second_model_uses_the_same_rag_configuration(self):
        a, b = self.create(), self.create(model_env="GROQ_MODEL_2")
        self.assertEqual(b.settings.model, SECOND)
        self.assertEqual(b.settings, a.settings.with_changes(model=SECOND))   # temperature, reasoning, tokens, ...
        self.assertIs(a.retriever, b.retriever)                                # same profile retriever
        self.assertIs(a.message_builder, b.message_builder)                    # same C3 prompt builder
        self.assertEqual((a.prompt_version, a.profile), (b.prompt_version, b.profile))

    def test_missing_second_model_fails_clearly_before_loading(self):
        env = {k: v for k, v in ENV.items() if k != "GROQ_MODEL_2"}
        with patch("src.evidence.Stage6Retriever", side_effect=AssertionError("must not load the indexes")):
            with self.assertRaises(ModelSelectionError):
                Assistant.create(config_loader=lambda model_env=None: load_config(env, dotenv_path=None,
                                                                                  model_env=model_env),
                                 profile="c3_public_0005", model_env="GROQ_MODEL_2")
        self.assertEqual(self.create(env=env).settings.model, ACCEPTED_MODEL)   # default still works

    def test_environment_selection(self):
        self.assertIsNone(selected_model_env({}))
        self.assertIsNone(selected_model_env({"MSU_ASSISTANT_MODEL_ENV": "  "}))
        self.assertEqual(selected_model_env({"MSU_ASSISTANT_MODEL_ENV": "GROQ_MODEL_2"}), "GROQ_MODEL_2")
        with patch.dict(os.environ, {"MSU_ASSISTANT_MODEL_ENV": "GROQ_MODEL_2"}), \
                patch("src.evidence.Stage6Retriever", StubRetriever), \
                patch("src.assistant.open_profile_retriever", lambda profile, models: StubRetriever("p")), \
                patch("src.ambiguity.code_titles", lambda records: {}), \
                patch("src.ambiguity.ambiguous_codes", lambda titles: {}):
            a = Assistant.create(config_loader=lambda model_env=None: load_config(ENV, dotenv_path=None,
                                                                                  model_env=model_env),
                                 profile="c3_public_0005")
        self.assertEqual(a.settings.model, SECOND)

    def test_generation_settings_helper(self):
        cfg = LLMConfig("groq", GenerationSettings(model=SECOND, temperature=0.9, max_completion_tokens=10))
        default, second = generation_settings(cfg), generation_settings(cfg, "GROQ_MODEL_2")
        self.assertEqual(default.model, ACCEPTED_MODEL)
        self.assertEqual(second, default.with_changes(model=SECOND))

    def test_comparison_runner_uses_the_app_settings(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation/gpt_oss_comparison"))
        source = (Path(__file__).resolve().parents[1] / "evaluation/gpt_oss_comparison/run_comparison.py").read_text(
            encoding="utf-8")
        self.assertIn("generation_settings(config, a.model_env)", source)
        self.assertNotIn("gpt-oss-120b\"", source.split("PRICES")[0])   # no model identifier in the selection logic


class AppSelectionTests(unittest.TestCase):
    def test_invalid_selection_stops_the_app_with_a_clear_message(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_resource.clear()
        app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with patch.dict(os.environ, {"MSU_ASSISTANT_MODEL_ENV": "GROQ_MODEL_9", "MSU_ASSISTANT_OFFLINE": ""}), \
                patch.object(Assistant, "create", classmethod(lambda cls, **k: self.fail("must not load"))):
            at = AppTest.from_file(app, default_timeout=60)
            at.run()
        self.assertFalse(at.exception)
        self.assertTrue(any("GROQ_MODEL_9" in e.value and "could not start" in e.value for e in at.error))
        self.assertNotIn(FAKE_KEY, str(at))


if __name__ == "__main__":
    unittest.main()
