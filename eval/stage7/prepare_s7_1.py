"""S7-1 preparation (no Groq call): freeze the evidence and build the 75-item randomized request manifest.

1. Checks the frozen question subset and that Arm 0 is byte-identical to the S7-0 baseline prompt.
2. Retrieves the top-5 evidence once per question with the accepted main configuration and verifies the chunk IDs
   against eval/stage6/s6_3_runs.json runs['B'] (first 5). Also confirms Arm 0 reproduces the S7-0 recorded prompt
   hash for N3. Writes eval/stage7/s7_1_evidence.json.
3. Builds the manifest (seeded order, adjacency rule, per-item request hashes). Writes eval/stage7/s7_1_manifest.json.
Refuses to run if the S7-1 freeze record exists. Run from the project root.
"""
import json, os, sys

sys.path.insert(0, ".")
sys.path.insert(0, "eval/stage7")
os.environ["HF_HUB_OFFLINE"] = "1"
from collections import Counter

from s7_1_core import MAIN_ARMS, REPLICATE, build_request, plan_items, randomized_order, replicate_adjacent, sha256_text
from src.context import SYSTEM_PROMPT, build_messages, prompt_sha256
from src.evidence import Stage6Retriever

S7_0_N3_PROMPT_SHA = "sha256:ca51984ea3237abeb4ca425c6bac1338ce639fbae616d65e29218957e86fe2ff"
assert not os.path.exists("eval/stage7/s7_1_freeze.json"), "S7-1 is frozen; preparation cannot be re-run"

design = json.load(open("eval/stage7/s7_1_design.json", encoding="utf-8"))
subset = json.load(open("eval/stage7/s7_1_questions.json", encoding="utf-8"))
prompts = json.load(open("eval/stage7/s7_1_prompts.json", encoding="utf-8"))
stage5 = {q["id"]: q for q in json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]}
reference = json.load(open("eval/stage6/s6_3_runs.json"))
grades = {}
for path in ("eval/stage5_grades.json", "eval/stage6/grades.json"):
    for g in json.load(open(path))["grades"]:
        grades[(g["question_id"], g["chunk_id"])] = g["grade"]

# 1. subset and prompts
assert prompts["arms"]["arm0"]["text"] == SYSTEM_PROMPT, "Arm 0 differs from the frozen S7-0 prompt"
citation = "- When you use a passage, cite it by its number, source and page."
assert all(prompts["arms"][a]["text"].endswith(citation) for a in ("arm0", "arm1", "arm2"))
main_ids = [q for cat in ("natural_language", "exact_code", "code_in_context") for q in subset["main"][cat]]
oos_ids = subset["oos_diagnostic_S7_1B"]
for cat, ids in subset["main"].items():
    assert len(ids) == 5 and all(stage5[q]["category"] == cat for q in ids), cat
assert len(set(main_ids)) == 15 and all(stage5[q]["category"] == "out_of_scope" for q in oos_ids) and len(oos_ids) == 5
assert "N3" not in main_ids

# 2. evidence, retrieved once
retriever = Stage6Retriever("main")
n3 = stage5["N3"]["question"]
assert prompt_sha256(build_messages(n3, retriever.retrieve(n3))) == S7_0_N3_PROMPT_SHA, "Arm 0 does not reproduce S7-0"
print("Arm 0 reproduces the S7-0 recorded prompt hash for N3: yes")
evidence = {"experiment": "S7-1", "retrieval": "Stage6Retriever('main'), retrieved once before generation",
            "reference": "eval/stage6/s6_3_runs.json runs['B'], first 5", "questions": {}}
for qid in main_ids + oos_ids:
    q = stage5[qid]
    ev = retriever.retrieve(q["question"])
    got = [e["chunk_id"] for e in ev]
    expected = [r["chunk_id"] for r in reference["runs"]["B"][qid][:5]]
    assert got == expected, f"{qid}: evidence {got} differs from accepted S6-3 reference {expected}"
    evidence["questions"][qid] = {
        "question": q["question"], "category": q["category"], "set": "main" if qid in main_ids else "oos",
        "answer_key": {"sufficient": q["sufficient"], "pages": q["pages"]} if q.get("sufficient") else None,
        "sufficient_evidence_numbers": [n for n, e in enumerate(ev, 1) if grades.get((qid, e["chunk_id"])) == 2],
        "evidence": ev}
print(f"evidence: {len(evidence['questions'])} questions, all identical to the S6-3 reference top 5")
with open("eval/stage7/s7_1_evidence.json", "w", encoding="utf-8") as f:
    json.dump(evidence, f, indent=1, ensure_ascii=False)

# 3. manifest
items = plan_items(main_ids, oos_ids)
order, reshuffles = randomized_order(items, design["ordering"]["seed"])
assert not replicate_adjacent(order)
for position, item in enumerate(order, 1):
    request = build_request(item, evidence, prompts)
    item.update({"position": position, "system_sha256": request["system_sha256"],
                 "user_sha256": request["user_sha256"], "prompt_sha256": request["prompt_sha256"]})
per_q = {}
for item in order:
    per_q.setdefault(item["question_id"], []).append(item)
for qid, its in per_q.items():
    assert len({i["user_sha256"] for i in its}) == 1, f"{qid}: user message differs across arms"
    by_arm = {i["arm"]: i for i in its}
    assert len({by_arm[a]["system_sha256"] for a in ("arm0", "arm1", "arm2")}) == 3
    if REPLICATE in by_arm:
        assert by_arm[REPLICATE]["prompt_sha256"] == by_arm["arm0"]["prompt_sha256"]
counts = {"total": len(order), "by_set": dict(Counter(i["set"] for i in order)),
          "by_set_and_arm": dict(Counter(f"{i['set']}/{i['arm']}" for i in order))}
assert counts["total"] == design["request_budget"]["total_manifest_items"] == 75
assert counts["by_set"] == {"main": 60, "oos": 15}
assert all(counts["by_set_and_arm"][f"main/{a}"] == 15 for a in MAIN_ARMS)
assert all(counts["by_set_and_arm"][f"oos/{a}"] == 5 for a in ("arm0", "arm1", "arm2"))
manifest = {"experiment": "S7-1", "seed": design["ordering"]["seed"], "reshuffles_for_adjacency_rule": reshuffles,
            "total_items": len(order), "counts": counts,
            "system_prompt_sha256": {a: sha256_text(prompts["arms"][a]["text"]) for a in ("arm0", "arm1", "arm2")},
            "settings": design["generation_settings"], "order": order}
with open("eval/stage7/s7_1_manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=1, ensure_ascii=False)
print(f"manifest: {len(order)} items, seed {manifest['seed']}, reshuffles {reshuffles}, counts {counts['by_set_and_arm']}")
