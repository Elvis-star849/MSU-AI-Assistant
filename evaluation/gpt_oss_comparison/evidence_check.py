"""
Shared evidence for the model comparison (offline: no Groq call, network disabled while retrieving).

    python evaluation/gpt_oss_comparison/evidence_check.py

Runs the app's own retrievers (public KB 0005 for the 18 public held-out questions; the intake profile on KB 0006,
with its advert supplement, for the 22 intake questions) after the app's query clean-up, then rebuilds the C3 messages
and checks they are byte-identical to the frozen inputs both model passes send. Writes
evaluation/results/gpt_oss_comparison/evidence_references.json: the knowledge-base versions, the retrieval
configuration, each question's top-5 passage references, the message hashes, and the retrieval latency per question
(model-independent, so end-to-end latency = retrieval + model generation).
"""
import hashlib
import json
import socket
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
OUT = ROOT / "evaluation/results/gpt_oss_comparison/evidence_references.json"


def main() -> int:
    from run_comparison import INPUTS, INPUTS_SHA256, canonical_sha, load_items
    from src.evidence import Stage6Retriever
    from src.kb.retriever import ACCEPTED
    from src.profiles import (EXPECTED_PUBLIC, EXPECTED_STAGING, IntakeAwareRetriever, build_c3_messages,
                              open_intake_retriever, open_public_retriever)
    from src.query_normalise import normalise_query

    doc = load_items()
    models = Stage6Retriever("main")
    models._load()
    retrievers = {"public": open_public_retriever(models),
                  "staging": IntakeAwareRetriever(open_intake_retriever(models))}
    retrievers["public"].retrieve("warm-up")
    real_connect = socket.socket.connect
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network disabled"))
    rows = []
    try:
        for it in doc["items"]:
            question, changes = normalise_query(it["question"])
            t = time.perf_counter()
            evidence = retrievers[it["system"]].retrieve(question)
            ms = round((time.perf_counter() - t) * 1000, 1)
            msgs = [{"role": m.role, "content": m.content} for m in build_c3_messages(question, evidence)]
            rows.append({"id": it["id"], "system": it["system"], "kb_version": "0005" if it["system"] == "public" else "0006",
                         "question_unchanged_by_cleanup": question == it["question"] and not changes,
                         "retrieval_ms": ms, "messages_sha256": canonical_sha(msgs),
                         "identical_to_frozen_inputs": canonical_sha(msgs) == it["messages_sha256"],
                         "evidence": [{"number": i + 1, "passage_uid": e.get("passage_uid"), "source": e["source"],
                                       "page": e["page"], "route": e.get("route"),
                                       "rerank_score": round(float(e["rerank_score"]), 4) if e.get("rerank_score") is not None else None}
                                      for i, e in enumerate(evidence)]})
    finally:
        socket.socket.connect = real_connect
    lat = [r["retrieval_ms"] for r in rows]
    out = {"inputs_file": str(INPUTS.relative_to(ROOT)).replace("\\", "/"), "inputs_sha256": INPUTS_SHA256,
           "knowledge_base": {"public": EXPECTED_PUBLIC, "intake": EXPECTED_STAGING},
           "retrieval_configuration": {"stage6_main": ACCEPTED, "prompt": doc["config"]["prompt"],
                                       "format": doc["config"]["format"],
                                       "candidate_module_sha256": doc["config"]["candidate_module_sha256"]},
           "all_identical_to_frozen_inputs": all(r["identical_to_frozen_inputs"] for r in rows),
           "retrieval_ms": {"mean": round(statistics.mean(lat), 1), "median": round(statistics.median(lat), 1),
                            "max": max(lat)},
           "items": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "items"}, indent=1, default=str))
    print("mismatches:", [r["id"] for r in rows if not r["identical_to_frozen_inputs"]])
    return 0 if out["all_identical_to_frozen_inputs"] else 1


if __name__ == "__main__":
    sys.exit(main())
