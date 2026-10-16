"""
Live smoke test of the optional second model (one Groq call) through the full assistant pipeline.

    python evaluation/gpt_oss_comparison/smoke_test.py [--model-env GROQ_MODEL_2] [--profile c3_public_0005]

Records the requested and returned model, HTTP status, latency, token usage, whitelisted rate-limit headers, citations
and safeguard notes to evaluation/results/gpt_oss_comparison/smoke_test_<model-env>.json. The key is never read here.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stage4"))
OUT = ROOT / "evaluation/results/gpt_oss_comparison"
QUESTION = "When does second-quarter face-to-face tuition run in 2027?"     # road map: 12 April to 21 May 2027
EXPECTED = (r"12\W*April", r"21\W*May")      # models may use no-break spaces


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-env", default="GROQ_MODEL_2")
    ap.add_argument("--profile", default="c3_public_0005")
    a = ap.parse_args()
    import run_generation_v2 as v2
    from src.assistant import Assistant
    from src.safeguards import cited_numbers

    assistant = Assistant.create(profile=a.profile, model_env=a.model_env)
    if assistant.llm is None:
        sys.exit(f"STOPPED: {assistant.llm_unavailable_reason}")
    client = v2.make_header_client(assistant.llm)
    raw_create = client._client.chat.completions.with_raw_response.create
    seen = {}

    def create(**kw):
        import groq
        try:
            raw = raw_create(**kw)
        except groq.APIStatusError as error:
            seen["http_status"] = error.status_code
            raise
        seen["http_status"] = raw.status_code
        return raw
    client._client = type("SDK", (), {"chat": type("C", (), {"completions": type("CC", (), {
        "with_raw_response": type("R", (), {"create": staticmethod(create)})})})})
    responses = []
    real_generate = client.generate
    client.generate = lambda messages, settings: responses.append(real_generate(messages, settings)) or responses[-1]
    assistant.llm = client
    t = time.perf_counter()
    r = assistant.ask(QUESTION)
    total = round((time.perf_counter() - t) * 1000, 1)
    resp = responses[-1] if responses else None
    record = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model_env": a.model_env,
        "profile": r.profile, "question": QUESTION, "status": r.status, "http_status": seen.get("http_status"),
        "requested_model": r.model, "returned_model": getattr(resp, "returned_model", None),
        "finish_reason": getattr(resp, "finish_reason", None), "request_id": getattr(resp, "request_id", None),
        "generation_latency_ms": getattr(resp, "latency_ms", None), "pipeline_latency_ms": total,
        "timings_ms": r.timings_ms, "usage": r.usage, "rate_limit_headers": getattr(client, "last_headers", {}),
        "error": {"kind": r.error_kind, "message": r.error_message,
                  "provider_detail": getattr(client, "last_error_detail", {})} if r.error_kind else None,
        "answer": r.answer, "citations": cited_numbers(r.answer or ""), "n_sources": len(r.sources),
        "sources": [f"[{s['number']}] {s['document']} p. {s['pdf_page']}" for s in r.sources],
        "safety_notes": [n["kind"] for n in r.safety_notes], "not_found": r.not_found,
        "expected_facts_present": all(re.search(x, r.answer or "") for x in EXPECTED),
        "prompt_version": r.prompt_version, "settings": getattr(resp, "settings", None),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"smoke_test_{a.model_env}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=1))
    ok = r.status == "answered" and record["expected_facts_present"] and record["citations"] and \
        (record["returned_model"] or "").endswith(record["requested_model"].split("/")[-1])
    print("SMOKE TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
