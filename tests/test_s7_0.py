"""S7-0 non-live tests: configuration, context construction, interfaces and error handling. No call reaches Groq.

Isolation: configuration is always loaded from an explicit dict with dotenv_path=None, so the real .env and the
real GROQ_API_KEY are never read. Run from the project root: python -m unittest discover -s tests -t .
"""
import os
import unittest
from types import SimpleNamespace

import groq
import httpx

from src.answer import answer_question
from src.context import PROMPT_VERSION, SYSTEM_PROMPT, build_context, build_messages, prompt_sha256
from src.evidence import CONFIGURATIONS, Stage6Retriever, to_evidence
from src.llm import LLMError, Message, create_client, load_config
from src.llm.base import GenerationSettings, LLMClient, LLMResponse
from src.llm.groq_client import SUPPORTED_MODELS, GroqClient, map_groq_error

FAKE_KEY = "fake-test-key-not-real"
URL = "https://api.groq.com/openai/v1/chat/completions"


def settings(**changes):
    return GenerationSettings(model="openai/gpt-oss-20b", retry_backoff_s=0.0).with_changes(**changes)


def evidence_item(rank, heading="Section: Part > Council", score=0.5, rerank=7.25):
    return {"rank": rank, "chunk_id": 100 + rank, "source": "MSU Humanities Yearbook", "page": 10 + rank,
            "heading": heading, "text": f"[MSU Humanities Yearbook, p. {10 + rank}]\nBody text {rank}.",
            "retrieval_rank": rank, "retrieval_score": score, "rerank_score": rerank, "route": "vector",
            "configuration": "main"}


class FakeUsage:
    def model_dump(self, exclude_none=True):
        return {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def completion(content="Final answer.", reasoning=None, finish_reason="stop", model="openai/gpt-oss-20b"):
    message = SimpleNamespace(content=content, reasoning=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)], model=model,
                           usage=FakeUsage(), x_groq=SimpleNamespace(id="req_test"), id="chatcmpl-test")


def fake_groq(*outcomes):
    completions = FakeCompletions(outcomes)
    return GroqClient(None, sdk_client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
                      sleep=lambda s: None), completions


def status_error(cls, status, message="server said: secret-detail"):
    response = httpx.Response(status, request=httpx.Request("POST", URL), headers={"x-request-id": "req-err"})
    return cls(message, response=response, body=None)


class ConfigTests(unittest.TestCase):
    def test_defaults_and_overrides(self):
        c = load_config({}, dotenv_path=None)
        self.assertEqual((c.provider, c.settings.model, c.key_configured), ("groq", "openai/gpt-oss-20b", False))
        c = load_config({"GROQ_API_KEY": FAKE_KEY, "GROQ_MODEL": "openai/gpt-oss-120b", "LLM_TEMPERATURE": "0.3",
                         "LLM_REASONING_EFFORT": "low", "LLM_MAX_COMPLETION_TOKENS": "1000",
                         "LLM_MAX_RETRIES": "0"}, dotenv_path=None)
        s = c.settings
        self.assertTrue(c.key_configured)
        self.assertEqual((s.model, s.temperature, s.reasoning_effort, s.max_completion_tokens, s.max_retries),
                         ("openai/gpt-oss-120b", 0.3, "low", 1000, 0))

    def test_dotenv_file_is_read_and_environment_wins(self):
        path = os.path.join(os.path.dirname(__file__), "_tmp_test.env")
        with open(path, "w") as f:
            f.write(f"GROQ_API_KEY={FAKE_KEY}\nGROQ_MODEL=openai/gpt-oss-120b\n")
        try:
            c = load_config({"GROQ_MODEL": "openai/gpt-oss-20b"}, dotenv_path=path)
            self.assertTrue(c.key_configured)
            self.assertEqual(c.settings.model, "openai/gpt-oss-20b")
        finally:
            os.remove(path)

    def test_key_never_in_repr_or_records(self):
        c = load_config({"GROQ_API_KEY": FAKE_KEY}, dotenv_path=None)
        self.assertNotIn(FAKE_KEY, repr(c))
        self.assertNotIn(FAKE_KEY, str(c.settings.to_record()))

    def test_invalid_settings_rejected(self):
        for bad in ({"temperature": 3.0}, {"reasoning_effort": "max"}, {"max_completion_tokens": 0},
                    {"max_retries": -1}, {"model": ""}):
            with self.assertRaises(ValueError):
                settings(**bad)

    def test_env_example_has_placeholders_only(self):
        with open(".env.example", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("GROQ_API_KEY=your_groq_api_key_here", text)
        self.assertIn("GROQ_MODEL=openai/gpt-oss-20b", text)
        self.assertNotIn("gsk_", text)

    def test_factory(self):
        with self.assertRaises(LLMError) as e:
            create_client(load_config({}, dotenv_path=None))  # no key
        self.assertEqual(e.exception.kind, "configuration")
        with self.assertRaises(LLMError):
            create_client(load_config({"LLM_PROVIDER": "nope", "GROQ_API_KEY": FAKE_KEY}, dotenv_path=None))
        client = create_client(load_config({"GROQ_API_KEY": FAKE_KEY}, dotenv_path=None))
        self.assertIsInstance(client, LLMClient)
        self.assertEqual(client._client.max_retries, 0)  # SDK retries disabled


class ContextTests(unittest.TestCase):
    def test_context_has_source_page_heading_text_in_rank_order(self):
        ctx = build_context([evidence_item(1), evidence_item(2, heading=None)])
        self.assertLess(ctx.index("[Evidence 1]"), ctx.index("[Evidence 2]"))
        for part in ("Source: MSU Humanities Yearbook", "Page: 11", "Heading: Section: Part > Council",
                     "Body text 1.", "Page: 12", "Body text 2."):
            self.assertIn(part, ctx)
        self.assertEqual(ctx.count("Heading:"), 1)  # omitted when the index has no heading

    def test_scores_and_ranks_not_shown_to_llm(self):
        messages = build_messages("Q?", [evidence_item(1, score=0.123456, rerank=9.87654)])
        content = " ".join(m.content for m in messages)
        for hidden in ("0.123456", "9.87654", "rerank", "retrieval_rank", "score", "chunk_id", "101"):
            self.assertNotIn(hidden, content)

    def test_messages_and_prompt_hash(self):
        ev = [evidence_item(1)]
        m = build_messages("Who chairs Council?", ev)
        self.assertEqual([x.role for x in m], ["system", "user"])
        self.assertEqual(m[0].content, SYSTEM_PROMPT)
        self.assertTrue(m[1].content.endswith("Question: Who chairs Council?"))
        self.assertEqual(prompt_sha256(m), prompt_sha256(build_messages("Who chairs Council?", ev)))
        self.assertNotEqual(prompt_sha256(m), prompt_sha256(build_messages("Other?", ev)))

    def test_no_evidence(self):
        self.assertIn("No evidence passages were retrieved.", build_messages("Q?", [])[1].content)

    def test_baseline_prompt_rules(self):
        for rule in ("only from the supplied MSU evidence", "Do not invent", "insufficient", "conflict",
                     "pretrained knowledge"):
            self.assertIn(rule, SYSTEM_PROMPT)


class GroqAdapterTests(unittest.TestCase):
    def test_request_parameters(self):
        client, calls = fake_groq(completion())
        client.generate([Message("user", "hi")], settings(temperature=0.2, reasoning_effort="low",
                                                           max_completion_tokens=321, timeout_s=9))
        sent = calls.calls[0]
        self.assertEqual(sent["include_reasoning"], False)
        self.assertNotIn("reasoning_format", sent)
        self.assertEqual((sent["model"], sent["temperature"], sent["reasoning_effort"],
                          sent["max_completion_tokens"], sent["timeout"]),
                         ("openai/gpt-oss-20b", 0.2, "low", 321, 9))
        self.assertEqual(sent["messages"], [{"role": "user", "content": "hi"}])

    def test_only_final_answer_returned(self):
        client, _ = fake_groq(completion(content="  The answer.  ", reasoning="hidden chain of thought"))
        r = client.generate([Message("user", "hi")], settings())
        self.assertEqual(r.text, "The answer.")
        self.assertTrue(r.provider_returned_reasoning)
        self.assertFalse(hasattr(r, "reasoning"))
        self.assertNotIn("hidden chain of thought", str(vars(r)))
        self.assertEqual((r.returned_model, r.request_id, r.attempts, r.usage["total_tokens"]),
                         ("openai/gpt-oss-20b", "req_test", 1, 15))
        self.assertEqual(r.settings["model"], "openai/gpt-oss-20b")
        self.assertIsNotNone(r.latency_ms)

    def test_unsupported_model_rejected_without_a_call(self):
        client, calls = fake_groq()
        with self.assertRaises(LLMError) as e:
            client.generate([Message("user", "hi")], settings(model="some/other-model"))
        self.assertEqual(e.exception.kind, "configuration")
        self.assertEqual(calls.calls, [])
        self.assertEqual(SUPPORTED_MODELS, ("openai/gpt-oss-20b", "openai/gpt-oss-120b"))

    def test_empty_answer_is_an_error(self):
        client, _ = fake_groq(completion(content="", finish_reason="length"))
        with self.assertRaises(LLMError) as e:
            client.generate([Message("user", "hi")], settings())
        self.assertEqual(e.exception.kind, "empty_response")
        self.assertIn("length", str(e.exception))

    def test_error_mapping_is_provider_neutral_and_safe(self):
        request = httpx.Request("POST", URL)
        cases = [(status_error(groq.AuthenticationError, 401), "authentication", False),
                 (status_error(groq.PermissionDeniedError, 403), "permission", False),
                 (status_error(groq.NotFoundError, 404), "model_not_found", False),
                 (status_error(groq.BadRequestError, 400), "bad_request", False),
                 (status_error(groq.RateLimitError, 429), "rate_limit", True),
                 (status_error(groq.InternalServerError, 500), "server", True),
                 (groq.APITimeoutError(request=request), "timeout", True),
                 (groq.APIConnectionError(request=request), "connection", True)]
        for error, kind, retryable in cases:
            mapped = map_groq_error(error)
            self.assertEqual((mapped.kind, mapped.retryable), (kind, retryable), kind)
            self.assertNotIn("secret-detail", str(mapped))
        self.assertEqual(map_groq_error(cases[0][0]).request_id, "req-err")

    def test_errors_raised_as_llm_error_without_chained_provider_exception(self):
        client, _ = fake_groq(status_error(groq.AuthenticationError, 401))
        with self.assertRaises(LLMError) as e:
            client.generate([Message("user", "hi")], settings())
        self.assertIsNone(e.exception.__cause__)
        self.assertTrue(e.exception.__suppress_context__)


class RetryTests(unittest.TestCase):
    def test_retryable_errors_retried_up_to_limit(self):
        client, calls = fake_groq(status_error(groq.RateLimitError, 429), status_error(groq.RateLimitError, 429),
                                  completion())
        waits = []
        client._sleep = waits.append
        r = client.generate([Message("user", "hi")], settings(max_retries=2, retry_backoff_s=0.5))
        self.assertEqual((r.attempts, len(calls.calls), waits), (3, 3, [0.5, 1.0]))

    def test_zero_retries_means_exactly_one_attempt(self):
        client, calls = fake_groq(status_error(groq.RateLimitError, 429), completion())
        with self.assertRaises(LLMError) as e:
            client.generate([Message("user", "hi")], settings(max_retries=0))
        self.assertEqual((e.exception.attempts, len(calls.calls)), (1, 1))

    def test_non_retryable_errors_not_retried(self):
        client, calls = fake_groq(status_error(groq.AuthenticationError, 401), completion())
        with self.assertRaises(LLMError) as e:
            client.generate([Message("user", "hi")], settings(max_retries=3))
        self.assertEqual((e.exception.attempts, len(calls.calls)), (1, 1))

    def test_retries_exhausted(self):
        client, calls = fake_groq(*[groq.APITimeoutError(request=httpx.Request("POST", URL))] * 3)
        with self.assertRaises(LLMError) as e:
            client.generate([Message("user", "hi")], settings(max_retries=2))
        self.assertEqual((e.exception.kind, e.exception.attempts, len(calls.calls)), ("timeout", 3, 3))


class FakeStore:
    """Ten vector-route results with headings, ranks 1..10."""
    def chunks_with_codes(self, query):
        return None

    def vector_search(self, query, top_k):
        return [{"rank": n, "chunk_id": n, "source": "S", "page": n, "text": f"t{n}", "score": 1 - n / 100,
                 "metadata": {"heading": f"Section: h{n}"}} for n in range(1, top_k + 1)]


class ReverseReranker:
    def __init__(self):
        self.with_heading = None

    def rerank(self, query, results, with_heading=False):
        self.with_heading = with_heading
        return [{**r, "retrieval_rank": r["rank"], "rank": i, "rerank_score": float(-i)}
                for i, r in enumerate(reversed(results), 1)]


class RetrieverTests(unittest.TestCase):
    def test_configurations_match_accepted_stage6(self):
        self.assertEqual(CONFIGURATIONS["main"], {"index": "faiss_store_v2", "tie_break": "vector", "pool": 10,
                                                  "reranker": "minilm", "with_heading": True, "top_k": 5})
        self.assertEqual(CONFIGURATIONS["fallback"], {"index": "faiss_store", "tie_break": "vector", "pool": 10,
                                                      "reranker": None, "with_heading": False, "top_k": 5})
        with self.assertRaises(ValueError):
            Stage6Retriever("other")

    def test_main_reranks_pool_of_ten_with_heading_and_keeps_five(self):
        reranker = ReverseReranker()
        ev = Stage6Retriever("main", store=FakeStore(), reranker=reranker).retrieve("q")
        self.assertTrue(reranker.with_heading)
        self.assertEqual([e["chunk_id"] for e in ev], [10, 9, 8, 7, 6])
        self.assertEqual([e["rank"] for e in ev], [1, 2, 3, 4, 5])
        self.assertEqual((ev[0]["retrieval_rank"], ev[0]["heading"], ev[0]["text"]), (10, "Section: h10", "t10"))

    def test_fallback_has_no_reranker(self):
        ev = Stage6Retriever("fallback", store=FakeStore()).retrieve("q")
        self.assertEqual([e["chunk_id"] for e in ev], [1, 2, 3, 4, 5])
        self.assertIsNone(ev[0]["rerank_score"])

    def test_evidence_without_heading(self):
        e = to_evidence({"rank": 1, "chunk_id": 1, "source": "S", "page": 2, "text": "t", "metadata": {}}, "fallback")
        self.assertIsNone(e["heading"])


class PipelineTests(unittest.TestCase):
    def test_question_to_answer(self):
        class FakeRetriever:
            def retrieve(self, question):
                return [evidence_item(1), evidence_item(2)]

        class FakeLLM(LLMClient):
            provider = "fake"

            def _complete(self, messages, s):
                self.messages = messages
                return LLMResponse(text="Grounded answer.", provider="fake", requested_model=s.model,
                                   returned_model=s.model, finish_reason="stop")

        llm = FakeLLM()
        result = answer_question("Who chairs Council?", FakeRetriever(), llm, settings())
        self.assertEqual(result.answer, "Grounded answer.")
        self.assertEqual(result.prompt_version, PROMPT_VERSION)
        self.assertEqual(result.prompt_sha256, prompt_sha256(llm.messages))
        self.assertEqual(result.evidence[0]["rerank_score"], 7.25)  # kept internally
        self.assertNotIn("7.25", llm.messages[1].content)  # not shown to the LLM

    def test_supplied_evidence_is_reused(self):
        class NoRetriever:
            def retrieve(self, question):
                raise AssertionError("must not retrieve")

        client, calls = fake_groq(completion())
        result = answer_question("Q?", NoRetriever(), client, settings(), evidence=[evidence_item(1)])
        self.assertIn("Body text 1.", calls.calls[0]["messages"][1]["content"])
        self.assertEqual(result.answer, "Final answer.")


if __name__ == "__main__":
    unittest.main()
