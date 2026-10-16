"""
GPT-OSS-20B vs GPT-OSS-120B: one generation pass of one model over the FROZEN held-out inputs.

    python evaluation/gpt_oss_comparison/run_comparison.py --model-env GROQ_MODEL     # Model A (accepted 20B)
    python evaluation/gpt_oss_comparison/run_comparison.py --model-env GROQ_MODEL_2   # Model B (120B)
    python evaluation/gpt_oss_comparison/run_comparison.py --model-env GROQ_MODEL_2 --dry-run --out <scratch dir>

Isolation: every item sends the byte-identical messages of remediation/experiments/heldout/HO_S_C3_inputs.json (the
C3 G2+F2 prompt over the Stage 6 retrieval top 5; tests/test_c3_profile.py proves the app builds the same messages).
Retrieval is therefore done once, frozen, and shared by both models. Only the model differs: temperature, reasoning
effort and the completion-token cap come from src.assistant.generation_settings, the app's own settings function.

Safety: the inputs file and every messages hash are verified first; the first call is a gate (an authentication,
permission or model error stops the pass before any further request); calls are paced (--min-interval); rate-limit,
timeout, connection and server errors get at most --retries retries with exponential backoff (5, 10, 20 s ...); a
rate limit that persists, a daily-quota signal or the cost cap stops the pass and the rest is reported as incomplete.
Re-running resumes: only items without a result are sent (an item stopped by an account or configuration error, such
as a model blocked for the organisation, gets no result line). Every failed attempt is logged in api_errors.jsonl. Existing results are never overwritten. The key is never read
here (src.llm.load_config holds it).
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stage4"))
INPUTS = ROOT / "remediation/experiments/heldout/HO_S_C3_inputs.json"
INPUTS_SHA256 = "21f6f2ce3406f41ecae36e9442951da786c6fb26b7f19cba164ad243e70a59c5"
QUESTIONS = ROOT / "remediation/heldout/heldout_questions.json"
RESULTS = ROOT / "evaluation/results/gpt_oss_comparison"
PRICES = {"openai/gpt-oss-20b": (0.10, 0.50), "openai/gpt-oss-120b": (0.15, 0.75)}   # US$/M tokens, conservative
CAP_USD = 0.50                                   # per pass; observed cost is a few cents
STOP_KINDS = {"authentication", "permission", "configuration", "model_not_found", "bad_request"}
RETRY_KINDS = {"rate_limit", "timeout", "connection", "server"}


def iso(t=None):
    return datetime.fromtimestamp(t or time.time(), timezone.utc).isoformat(timespec="seconds")


def canonical_sha(messages):
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True, indent=1).encode() + b"\n").hexdigest()


def cost(model, usage):
    pin, pout = PRICES.get(model, (0.15, 0.75))
    return (usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout) / 1e6


def load_items():
    raw = INPUTS.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUTS_SHA256:
        sys.exit("STOPPED: frozen inputs file hash mismatch")
    doc = json.loads(raw)
    strata = {q["id"]: q["stratum"] for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    for it in doc["items"]:
        if canonical_sha(it["messages"]) != it["messages_sha256"]:
            sys.exit(f"STOPPED: messages hash mismatch for {it['id']}")
        it["stratum"] = strata[it["id"]]
    return doc


def daily_quota_exhausted(headers):
    """True when the response headers say the daily request allowance is used up (reset measured in hours)."""
    reset = str(headers.get("x-ratelimit-reset-requests", ""))
    return headers.get("x-ratelimit-remaining-requests") == "0" and "h" in reset


class DryRunClient:
    """No network and no credentials: deterministic placeholder answers citing Evidence 1 (or declining)."""
    last_headers, last_error_detail = {}, {}

    def generate(self, messages, settings):
        from src.llm.base import LLMResponse
        text = f"[DRY RUN {settings.model}] Placeholder answer [Evidence 1]."
        return LLMResponse(text=text, provider="dry-run", requested_model=settings.model, returned_model=settings.model,
                           finish_reason="dry_run", usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                           latency_ms=0.0, settings=settings.to_record())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-env", required=True, help="GROQ_MODEL (Model A) or GROQ_MODEL_2 (Model B)")
    ap.add_argument("--out", default=None, help="default evaluation/results/gpt_oss_comparison/<model-env>")
    ap.add_argument("--min-interval", type=float, default=3.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None, help="only the first N scheduled items (smoke runs)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from src.assistant import generation_settings
    from src.llm import LLMError, Message, create_client, load_config
    import run_generation_v2 as v2

    doc = load_items()
    config = load_config(model_env=a.model_env)            # ModelSelectionError if the variable is missing/invalid
    settings = generation_settings(config, a.model_env).with_changes(max_retries=0)   # retries are handled below
    model = settings.model
    out = Path(a.out) if a.out else RESULTS / a.model_env
    if a.dry_run and RESULTS in out.resolve().parents:
        sys.exit("STOPPED: a dry run must not write into the results folder; pass --out <scratch dir>")
    out.mkdir(parents=True, exist_ok=True)
    meta_path, results_path = out / "run_meta.json", out / "results.jsonl"
    meta = {"model_env": a.model_env, "model": model, "settings": settings.to_record(), "provider": config.provider,
            "inputs_file": str(INPUTS.relative_to(ROOT)).replace("\\", "/"), "inputs_sha256": INPUTS_SHA256,
            "inputs_config": doc["config"], "items": len(doc["items"]), "dry_run": a.dry_run}
    if meta_path.exists():
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        if {k: old.get(k) for k in meta} != meta:
            sys.exit("STOPPED: the output folder belongs to a different model, settings or inputs")
    else:
        meta_path.write_text(json.dumps({**meta, "created": iso()}, ensure_ascii=False, indent=1), encoding="utf-8")
    done = set()
    if results_path.exists():
        done = {json.loads(l)["id"] for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()}
    order = list(doc["items"])
    random.Random(f"gpt-oss-comparison|{a.model_env}").shuffle(order)
    schedule = [it for it in order if it["id"] not in done][:a.limit]
    if not schedule:
        print("nothing to do: every item has been attempted")
        return 0
    print(f"{a.model_env} = {model}: {len(schedule)} items to send ({len(done)} already attempted)", flush=True)

    client = DryRunClient() if a.dry_run else v2.make_header_client(create_client(config))
    if os.name == "nt" and not a.dry_run:                 # keep Windows from idle-sleeping during a pass
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    spent, stopped, last_sent = 0.0, None, 0.0
    with open(results_path, "a", encoding="utf-8", newline="\n") as results:
        for n, it in enumerate(schedule):
            msgs = [Message(m["role"], m["content"]) for m in it["messages"]]
            rec = {"id": it["id"], "system": it["system"], "stratum": it["stratum"], "question": it["question"],
                   "model_env": a.model_env, "requested_model": model, "messages_sha256": it["messages_sha256"],
                   "settings": settings.to_record(), "sent_at": iso(), "attempts": []}
            t_item = time.perf_counter()
            for attempt in range(a.retries + 1):
                wait = max(0.0, a.min_interval - (time.time() - last_sent))
                if attempt:
                    wait = max(wait, 5.0 * 2 ** (attempt - 1))
                if not a.dry_run:
                    time.sleep(wait)
                last_sent = time.time()
                t = time.perf_counter()
                try:
                    resp = client.generate(msgs, settings)
                except LLMError as err:
                    headers = dict(getattr(client, "last_headers", {}) or {})
                    rec["attempts"].append({"status": "error", "latency_ms": round((time.perf_counter() - t) * 1000, 1),
                                            "error": err.to_record(), "provider_detail": getattr(client, "last_error_detail", {}),
                                            "rate_limit_headers": headers})
                    if err.kind in STOP_KINDS or daily_quota_exhausted(headers):
                        stopped = "daily_quota" if daily_quota_exhausted(headers) else err.kind
                        break
                    if err.kind not in RETRY_KINDS or attempt == a.retries:
                        if err.kind == "rate_limit":
                            stopped = "rate_limit_persisted"
                        break
                    continue
                usage = resp.usage or {}
                rec["attempts"].append({"status": "answered", "latency_ms": resp.latency_ms,
                                        "rate_limit_headers": dict(getattr(client, "last_headers", {}) or {})})
                rec.update({"status": "answered", "answer": resp.text, "returned_model": resp.returned_model,
                            "finish_reason": resp.finish_reason, "request_id": resp.request_id, "usage": usage,
                            "generation_latency_ms": resp.latency_ms,
                            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                            "usd": 0.0 if a.dry_run else round(cost(model, usage), 6)})
                spent += rec["usd"]
                break
            rec.setdefault("status", "error")
            rec["item_wall_ms"] = round((time.perf_counter() - t_item) * 1000, 1)
            failed = [x for x in rec["attempts"] if x["status"] == "error"]
            if failed:
                with open(out / "api_errors.jsonl", "a", encoding="utf-8", newline="\n") as errors:
                    for x in failed:
                        errors.write(json.dumps({"id": it["id"], "at": rec["sent_at"], **x}, ensure_ascii=False) + "\n")
            if stopped in STOP_KINDS:        # account/configuration problem: the item stays unattempted for a resume
                print(f"STOPPED before {it['id']}: {stopped} {failed[-1].get('provider_detail') or failed[-1]['error']}")
                break
            results.write(json.dumps(rec, ensure_ascii=False) + "\n")
            results.flush()
            os.fsync(results.fileno())
            print(f"{n + 1}/{len(schedule)} {it['id']} {rec['status']} "
                  f"{rec.get('generation_latency_ms') or ''} ms {rec.get('usage', {}).get('total_tokens', '')} tok",
                  flush=True)
            if spent > CAP_USD:
                stopped = "cost_cap"
            if stopped:
                break
    attempted = {json.loads(l)["id"] for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()}
    summary = {"model_env": a.model_env, "model": model, "stopped": stopped, "attempted": len(attempted),
               "not_attempted": sorted(i["id"] for i in doc["items"] if i["id"] not in attempted),
               "usd_this_invocation": round(spent, 4)}
    print(json.dumps(summary))
    return 2 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
