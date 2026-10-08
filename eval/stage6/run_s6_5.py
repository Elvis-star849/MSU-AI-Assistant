"""S6-5: ambiguous-code metadata (no ranking change), checked on the Stage 5 development set only.

Uses the stored S6-3 variant B results (the provisional configuration), since retrieval is unchanged.
Writes eval/stage6/s6_5_ambiguous_codes.json and eval/stage6/s6_5_results.json. Run from the project root.
"""
import hashlib, json, sys

sys.path.insert(0, ".")
from src.ambiguity import ambiguity_note, ambiguous_codes, code_titles
from src.vectorstore import course_codes

records = [json.loads(line) for line in open("faiss_store/chunks.jsonl", encoding="utf-8")]
titles = code_titles(records)
ambiguous = ambiguous_codes(titles)
json.dump({"ambiguity_py_sha256": hashlib.sha256(open("src/ambiguity.py", "rb").read()).hexdigest(),
           "codes_with_titles": len(titles), "ambiguous": len(ambiguous),
           "codes": {c: [{k: g[k] for k in ("title", "pages", "chunk_ids")} for g in groups]
                     for c, groups in sorted(ambiguous.items())}},
          open("eval/stage6/s6_5_ambiguous_codes.json", "w"), indent=1)

questions = json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
runs_b = json.load(open("eval/stage6/s6_3_runs.json"))["runs"]["B"]
by_id = {r["chunk_id"]: r for r in records}
dev = {}
for q in questions:
    codes = course_codes(q["question"])
    if not codes:
        continue
    top5 = [{"chunk_id": r["chunk_id"]} for r in runs_b[q["id"]][:5]]
    dev[q["id"]] = {"codes": codes, "flagged": [c for c in codes if c in ambiguous],
                    "note_top5": ambiguity_note(q["question"], top5, ambiguous)}
out = {"codes_with_titles": len(titles), "ambiguous_codes": len(ambiguous), "development": dev}
json.dump(out, open("eval/stage6/s6_5_results.json", "w"), indent=1)
print(len(titles), "codes with a title;", len(ambiguous), "flagged ambiguous")
for qid, d in dev.items():
    if d["flagged"]:
        print(qid, json.dumps(d["note_top5"], ensure_ascii=False))
print("development code questions flagged:", [q for q, d in dev.items() if d["flagged"]],
      "of", len(dev))
