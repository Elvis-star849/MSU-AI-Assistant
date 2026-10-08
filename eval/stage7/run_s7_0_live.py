"""S7-0 live Groq connectivity test: exactly one attempt to openai/gpt-oss-20b and one to openai/gpt-oss-120b.

Infrastructure/connectivity only: the answers are saved for audit/debugging and are NOT for model quality comparison.
- Preflight: .env must be Git-ignored, untracked, absent from history; GROQ_API_KEY must be configured
  (only "configured: yes/no" is ever reported).
- One Stage 5 development question (N3: no course code, so no ambiguity; its top 5 contains chunks graded
  sufficient in Stage 5/6). Evidence is retrieved once (main configuration) and the prompt built once; both models
  receive exactly the same messages (prompt sha256 recorded).
- max_retries=0. If a request fails, the failure is recorded and the test stops.
Refuses to run if eval/stage7/s7_0_live.json exists. Run from the project root.
"""
import json, os, re, subprocess, sys, time

sys.path.insert(0, ".")
os.environ["HF_HUB_OFFLINE"] = "1"
OUT = "eval/stage7/s7_0_live.json"
QUESTION_ID = "N3"
MODELS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")
LABEL = "S7-0 connectivity output — NOT FOR MODEL QUALITY COMPARISON"
# obvious reasoning / chain-of-thought markers (heuristic only, not proof)
REASONING_MARKERS = [r"<think>", r"</think>", r"<\|channel\|>", r"\bassistantfinal\b", r"^\s*analysis\b",
                     r"chain[- ]of[- ]thought", r"\bthe user (asks|is asking|wants)\b", r"\bwe need to\b",
                     r"\blet me think\b", r"\bi need to (check|figure|think)\b", r"^\s*reasoning\s*:"]


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


assert not os.path.exists(OUT), "S7-0 live test has already been run; a re-run must be disclosed and approved"
preflight = {
    "env_ignored": git("check-ignore", "-q", ".env").returncode == 0,
    "env_not_tracked": git("ls-files", "--error-unmatch", ".env").returncode != 0,
    "env_not_staged": ".env" not in git("diff", "--cached", "--name-only").stdout.split(),
    "env_not_in_history": git("log", "--all", "--oneline", "--", ".env").stdout.strip() == "",
}
from src.llm import create_client, load_config  # noqa: E402

config = load_config()
preflight["groq_api_key_configured"] = config.key_configured
print("preflight:", preflight)
assert all(preflight.values()), "preflight failed; no request sent"

from src.ambiguity import ambiguity_note, ambiguous_codes, code_titles  # noqa: E402
from src.answer import answer_question  # noqa: E402
from src.context import PROMPT_VERSION, build_messages, prompt_sha256  # noqa: E402
from src.evidence import Stage6Retriever  # noqa: E402
from src.llm import LLMError  # noqa: E402

question = next(q for q in json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
                if q["id"] == QUESTION_ID)
retriever = Stage6Retriever("main")
evidence = retriever.retrieve(question["question"])
note = ambiguity_note(question["question"], evidence, ambiguous_codes(code_titles(retriever._store.records)))
assert not note, "chosen question has a known ambiguity"
messages = build_messages(question["question"], evidence)
prompt_hash = prompt_sha256(messages)

client = create_client(config)
results = []
for model in MODELS:
    settings = config.settings.with_changes(model=model, max_retries=0)
    sent_hash = prompt_sha256(build_messages(question["question"], evidence))
    assert sent_hash == prompt_hash
    record = {"requested_model": model, "settings": settings.to_record(), "prompt_sha256": sent_hash,
              "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        result = answer_question(question["question"], retriever, client, settings, evidence=evidence)
    except LLMError as error:
        record.update({"succeeded": False, "attempts": error.attempts, "error": error.to_record()})
        results.append(record)
        print(f"{model}: FAILED ({error.kind}); stopping")
        break
    r = result.llm
    markers = [m for m in REASONING_MARKERS if re.search(m, r.text, re.IGNORECASE | re.MULTILINE)]
    record.update({
        "succeeded": True, "attempts": r.attempts, "returned_model": r.returned_model, "latency_ms": r.latency_ms,
        "usage": r.usage, "finish_reason": r.finish_reason, "request_id": r.request_id,
        "reasoning_check": {
            "reasoning_requested_excluded": r.reasoning_requested_excluded,
            "provider_returned_reasoning_field": r.provider_returned_reasoning,
            "adapter_exposes_reasoning_field": hasattr(r, "reasoning"),
            "answer_reasoning_markers_found": markers,
            "only_final_answer_returned": r.reasoning_requested_excluded and not hasattr(r, "reasoning")
                                          and not markers,
            "note": "answer-text inspection is a heuristic, not proof"},
        "answer": {"label": LABEL, "text": r.text}})
    results.append(record)
    print(f"{model}: ok | returned {r.returned_model} | {r.latency_ms} ms | attempts {r.attempts} | "
          f"tokens {r.usage.get('total_tokens')} | finish {r.finish_reason} | markers {markers}")

report = {"experiment": "S7-0", "purpose": "Groq connectivity/integration only; not an answer-quality experiment",
          "label": LABEL, "preflight": preflight, "question_set": "Stage 5 development (held-out set not used)",
          "question_id": QUESTION_ID, "question": question["question"], "retrieval_configuration": "main",
          "evidence": [{k: e[k] for k in ("rank", "chunk_id", "source", "page", "heading", "retrieval_rank",
                                          "rerank_score")} for e in evidence],
          "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_hash, "calls": results,
          "identical_input_to_both_models": len({c["prompt_sha256"] for c in results}) == 1,
          "total_requests_attempted": sum(c["attempts"] for c in results)}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=1, ensure_ascii=False)
print("saved", OUT, "| identical input:", report["identical_input_to_both_models"],
      "| requests attempted:", report["total_requests_attempted"])
