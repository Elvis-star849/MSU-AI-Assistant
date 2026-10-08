"""S7-1 runner. Default is a dry run: every frozen check, every one of the 75 requests built and verified, no client.

  python eval/stage7/run_s7_1.py                       dry run (no Groq client is created)
  python eval/stage7/run_s7_1.py --live [--pace S]     live run (only after explicit owner approval)
  python eval/stage7/run_s7_1.py --live --resend ITEM --approval "owner approval text"
                                                       one approved extra attempt for a failed item
Live answers go to ~/rag_private/s7_1/s7_1_runs.jsonl (outside the repository) until grading is complete.
Run from the project root.
"""
import argparse, json, os, subprocess, sys
from collections import Counter

sys.path.insert(0, ".")
sys.path.insert(0, "eval/stage7")
from s7_1_core import (MIN_PACE_S, PRIVATE_DIR, build_request, execute, frozen_settings, read_attempts,
                       replicate_adjacent, sha256_file)

FREEZE = "eval/stage7/s7_1_freeze.json"
RUNS = os.path.join(PRIVATE_DIR, "s7_1_runs.jsonl")

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true")
parser.add_argument("--pace", type=float, default=MIN_PACE_S)
parser.add_argument("--resend")
parser.add_argument("--approval")
args = parser.parse_args()


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True)


# ---- frozen files
freeze = json.load(open(FREEZE, encoding="utf-8"))
changed = [p for p, digest in freeze["sha256"].items() if sha256_file(p) != digest]
assert not changed, f"frozen S7-1 files changed: {changed}"
design = json.load(open("eval/stage7/s7_1_design.json", encoding="utf-8"))
prompts = json.load(open("eval/stage7/s7_1_prompts.json", encoding="utf-8"))
evidence = json.load(open("eval/stage7/s7_1_evidence.json", encoding="utf-8"))
manifest = json.load(open("eval/stage7/s7_1_manifest.json", encoding="utf-8"))
settings = frozen_settings(design)

# ---- every request rebuilt from frozen evidence and checked against the manifest
order = manifest["order"]
mismatch = [i["item_id"] for i in order if build_request(i, evidence, prompts)["prompt_sha256"] != i["prompt_sha256"]]
checks = {
    "freeze_hashes_verified": len(freeze["sha256"]),
    "manifest_items": len(order),
    "distinct_items": len({i["item_id"] for i in order}),
    "items_equal_budget": len(order) == design["request_budget"]["total_manifest_items"] == 75,
    "positions_1_to_75": [i["position"] for i in order] == list(range(1, 76)),
    "request_hash_mismatches": mismatch,
    "identical_user_message_across_arms": all(
        len({i["user_sha256"] for i in order if i["question_id"] == q}) == 1 for q in evidence["questions"]),
    "replicate_adjacent_to_original": replicate_adjacent(order),
    "by_set_and_arm": dict(Counter(f"{i['set']}/{i['arm']}" for i in order)),
    "settings": settings.to_record(),
    "settings_max_retries_zero": settings.max_retries == 0,
    "model": settings.model,
}
assert not mismatch and checks["items_equal_budget"] and checks["positions_1_to_75"] and checks["distinct_items"] == 75
assert checks["identical_user_message_across_arms"] and not checks["replicate_adjacent_to_original"]
assert settings.max_retries == 0 and settings.model == "openai/gpt-oss-20b" and settings.temperature == 0.0

if not args.live:
    previous = read_attempts(RUNS)
    checks.update({"mode": "dry run - no Groq client created, no request sent",
                   "groq_client_created": False, "private_runs_file_exists": os.path.exists(RUNS),
                   "attempts_already_recorded": len(previous), "requests_a_live_run_would_send": 75 - len(previous)})
    print(json.dumps(checks, indent=1))
    sys.exit(0)

# ---- live run
preflight = {"env_ignored": git("check-ignore", "-q", ".env").returncode == 0,
             "env_not_tracked": git("ls-files", "--error-unmatch", ".env").returncode != 0,
             "env_not_staged": ".env" not in git("diff", "--cached", "--name-only").stdout.split(),
             "env_not_in_history": git("log", "--all", "--oneline", "--", ".env").stdout.strip() == ""}
from src.llm import create_client, load_config  # noqa: E402

config = load_config()
preflight["groq_api_key_configured"] = config.key_configured
print("preflight:", preflight)
assert all(preflight.values()), "preflight failed; no request sent"
os.makedirs(PRIVATE_DIR, exist_ok=True)
result = execute(manifest, evidence, prompts, create_client(config), settings, RUNS, pace_s=args.pace,
                 resend_item=args.resend, resend_approval=args.approval)
attempts = read_attempts(RUNS)
print(json.dumps({"this_run": result, "total_attempts_recorded": len(attempts),
                  "planned_items_attempted": len({a["item_id"] for a in attempts}),
                  "succeeded": sum(a["succeeded"] for a in attempts)}, indent=1))
