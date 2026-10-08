"""S7-1 freeze: sha256 of every input, script and source file the live run and the analysis depend on.

run_s7_1.py refuses to run (dry or live) unless every hash matches. Run once, after tests pass, from the project root.
"""
import json, os, subprocess, sys, time

sys.path.insert(0, ".")
sys.path.insert(0, "eval/stage7")
from s7_1_core import sha256_file

OUT = "eval/stage7/s7_1_freeze.json"
assert not os.path.exists(OUT), "S7-1 is already frozen"
FILES = [
    "eval/stage7/s7_1_design.json", "eval/stage7/s7_1_questions.json", "eval/stage7/s7_1_prompts.json",
    "eval/stage7/s7_1_evidence.json", "eval/stage7/s7_1_manifest.json",
    "eval/stage7/s7_1_core.py", "eval/stage7/prepare_s7_1.py", "eval/stage7/run_s7_1.py",
    "eval/stage7/s7_1_blind.py", "eval/stage7/report_s7_1.py", "eval/stage7/freeze_s7_1.py",
    "eval/stage7/check_stage6_integrity.py", "tests/test_s7_1.py",
    "src/context.py", "src/evidence.py", "src/answer.py",
    "src/llm/__init__.py", "src/llm/base.py", "src/llm/config.py", "src/llm/groq_client.py",
]
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
manifest = json.load(open("eval/stage7/s7_1_manifest.json", encoding="utf-8"))
prompts = json.load(open("eval/stage7/s7_1_prompts.json", encoding="utf-8"))
freeze = {"experiment": "S7-1", "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_head": head,
          "note": "git HEAD plus uncommitted S7-1 working files, frozen by hash below",
          "manifest_items": manifest["total_items"], "order_seed": manifest["seed"],
          "system_prompt_sha256": manifest["system_prompt_sha256"],
          "prompt_versions": {a: v["prompt_version"] for a, v in prompts["arms"].items()},
          "sha256": {path: sha256_file(path) for path in FILES}}
json.dump(freeze, open(OUT, "w"), indent=1)
print(f"frozen {len(FILES)} files at {head[:7]}")
