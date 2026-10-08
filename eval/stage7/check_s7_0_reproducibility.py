"""S7-0: does the Stage 7 wrapper (src/evidence.py) return the same top-5 chunk IDs as the accepted Stage 6 pipeline?

Stage 5 development questions only (all 35); the Stage 6 held-out set is not read.
Reference method (a), recorded runs whose settings match exactly (verified in the S7-0 record):
  main     <- eval/stage6/s6_3_runs.json "B": T1 routed_search(faiss_store_v2, q, 10, "vector")
              -> MiniLM rerank(with_heading=True); its first 5. Same faiss_store_v2 build as now
              (S6-3 build manifest == current manifest: build fingerprint, vectors checksum, heading fingerprint).
  fallback <- eval/stage6/s6_3_runs.json "T1_v1": routed_search(faiss_store, q, 10, "vector"); its first 5
              (cross-checked: identical top 5 to eval/stage6/s6_1_runs.json "T1" on every question).
Writes eval/stage7/s7_0_reproducibility.json. Run from the project root.
"""
import json, os, sys

sys.path.insert(0, ".")
os.environ["HF_HUB_OFFLINE"] = "1"
from src.evidence import Stage6Retriever

questions = json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
s63 = json.load(open("eval/stage6/s6_3_runs.json"))
assert s63["pool"] == 10
REFERENCES = {"main": ("eval/stage6/s6_3_runs.json", "B"), "fallback": ("eval/stage6/s6_3_runs.json", "T1_v1")}

report = {"questions": "Stage 5 development set (eval/stage5_questions.json), all 35; held-out set not used",
          "reference_method": "(a) existing recorded Stage 6 development run with exactly matching settings",
          "checks": {}}
for configuration, (path, run) in REFERENCES.items():
    retriever = Stage6Retriever(configuration)
    mismatches = []
    for q in questions:
        got = [e["chunk_id"] for e in retriever.retrieve(q["question"])]
        expected = [r["chunk_id"] for r in s63["runs"][run][q["id"]][:5]]
        if got != expected:
            mismatches.append({"question_id": q["id"], "expected": expected, "got": got})
    report["checks"][configuration] = {"reference": f"{path} runs[{run!r}], first 5", "questions": len(questions),
                                       "identical": len(questions) - len(mismatches), "mismatches": mismatches,
                                       "passed": not mismatches}
    print(f"{configuration}: {len(questions) - len(mismatches)}/{len(questions)} identical top-5 chunk IDs")
report["passed"] = all(c["passed"] for c in report["checks"].values())
json.dump(report, open("eval/stage7/s7_0_reproducibility.json", "w"), indent=1)
print("PASSED" if report["passed"] else "FAILED")
sys.exit(0 if report["passed"] else 1)
