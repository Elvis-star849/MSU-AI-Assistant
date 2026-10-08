"""S6-3: build the heading-aware index in faiss_store_v2/ from the frozen chunk records (faiss_store/ is only read)."""
import hashlib, json, os, sys, time

sys.path.insert(0, ".")
from src.heading_store import HeadingAwareStore

baseline = json.load(open("eval/stage6/baseline_hashes.json"))
for path, digest in baseline["sha256"].items():
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest, f"baseline file changed: {path}"

records = [json.loads(line) for line in open("faiss_store/chunks.jsonl", encoding="utf-8")]
start = time.perf_counter()
store = HeadingAwareStore("faiss_store_v2")
store.build_from_records(records)
store.save()
total = time.perf_counter() - start
assert store.manifest["corpus_fingerprint"] == baseline["corpus_fingerprint"], "chunk text changed!"

check = HeadingAwareStore("faiss_store_v2")
check.load(expected_fingerprint=baseline["corpus_fingerprint"])
sizes = {f: os.path.getsize(os.path.join("faiss_store_v2", f)) for f in os.listdir("faiss_store_v2")}
report = {"build_s": round(total, 1), "timings": {k: round(v, 1) for k, v in store.timings.items()},
          "sizes_bytes": sizes, "manifest": store.manifest,
          "chunks_with_heading": sum(1 for r in store.records if r["heading"]),
          "structure_py_sha256": hashlib.sha256(open("src/structure.py", "rb").read()).hexdigest()}
json.dump(report, open("eval/stage6/s6_3_build.json", "w"), indent=1)
print(json.dumps({k: report[k] for k in ("build_s", "timings", "sizes_bytes", "chunks_with_heading")}, indent=1))
