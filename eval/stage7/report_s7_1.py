"""S7-1 results and the pre-agreed criteria (eval/stage7/s7_1_design.json). Frozen by hash before generation.

Run exactly once, only after: grading -> owner spot-check -> corrections applied -> grades frozen and hashed.
Inputs: eval/stage7/s7_1_grades.json (grader output + owner corrections, with its frozen sha256 recorded in
eval/stage7/s7_1_grades_freeze.json), the private mappings and runs (verified against the blinding commitment).
This script is the unblinding step: it copies the runs and mappings into the repository and writes
eval/stage7/s7_1_results.json.
"""
import copy, json, os, shutil, sys

sys.path.insert(0, ".")
sys.path.insert(0, "eval/stage7")
from s7_1_core import PRIVATE_DIR, compute_results, read_attempts, sha256_file

OUT = "eval/stage7/s7_1_results.json"
assert not os.path.exists(OUT), "the S7-1 report has already been run; a re-run must be disclosed and approved"
assert sha256_file("eval/stage7/s7_1_grades.json") == \
    json.load(open("eval/stage7/s7_1_grades_freeze.json"))["s7_1_grades_sha256"], "grades changed after freezing"
commitment = json.load(open("eval/stage7/s7_1_blinding_commitment.json"))
abs_path, pair_path = (os.path.join(PRIVATE_DIR, f) for f in ("s7_1_absolute_mapping.json", "s7_1_pairwise_mapping.json"))
assert sha256_file(abs_path) == commitment["absolute_mapping_sha256"]
assert sha256_file(pair_path) == commitment["pairwise_mapping_sha256"]

grades = json.load(open("eval/stage7/s7_1_grades.json", encoding="utf-8"))
absolute, pairwise = copy.deepcopy(grades["absolute"]), copy.deepcopy(grades["pairwise"])
index = {e["label"]: e for e in absolute["main"] + absolute["oos"]} | {e["label"]: e for e in pairwise["pairwise"]}
for c in grades["owner_spot_check"]["corrections"]:  # owner value replaces the grader value; both stay recorded
    assert index[c["label"]][c["field"]] == c["grader_value"], c
    index[c["label"]][c["field"]] = c["owner_value"]

evidence = json.load(open("eval/stage7/s7_1_evidence.json", encoding="utf-8"))
manifest = json.load(open("eval/stage7/s7_1_manifest.json", encoding="utf-8"))
runs_private = os.path.join(PRIVATE_DIR, "s7_1_runs.jsonl")
attempts = read_attempts(runs_private)
results = compute_results(evidence, absolute, json.load(open(abs_path))["mapping"], pairwise,
                          json.load(open(pair_path))["mapping"], attempts, manifest)
results["owner_corrections_applied"] = len(grades["owner_spot_check"]["corrections"])
results["latency_and_tokens"] = {
    arm: {"median_latency_ms": sorted(a["latency_ms"] for a in attempts if a["succeeded"] and a["arm"] == arm)[
        len([a for a in attempts if a["succeeded"] and a["arm"] == arm]) // 2],
          "total_tokens": sum(a["usage"].get("total_tokens", 0) for a in attempts if a["succeeded"] and a["arm"] == arm)}
    for arm in ("arm0", "arm1", "arm2", "arm0_replicate")}

for src, dst in ((runs_private, "eval/stage7/s7_1_runs.jsonl"), (abs_path, "eval/stage7/s7_1_absolute_mapping.json"),
                 (pair_path, "eval/stage7/s7_1_pairwise_mapping.json")):
    shutil.copyfile(src, dst)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=1, ensure_ascii=False)
print(json.dumps({k: results[k] for k in ("validity", "eligibility", "selected_prompt", "selection_rule_applied",
                                          "instability", "conclusiveness")}, indent=1))
for arm in ("arm0", "arm1", "arm2", "arm0_replicate"):
    print(arm, results["summary"][arm]["overall"])
print("pairwise:", {k: (v["win"], v["tie"], v["loss"]) for k, v in results["pairwise"].items()})
print("OOS:", results["oos_S7_1B"]["counts"])
