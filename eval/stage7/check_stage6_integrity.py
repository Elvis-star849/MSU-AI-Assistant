"""S7-0: verify that the accepted Stage 6 retrieval system is unchanged.

Checks, against eval/stage6/s6_6_freeze.json and the accepted milestone commit 5fc1370:
  - sha256 of the frozen retrieval source files, both indexes and both model snapshots
    (the three S6-6 evaluation scripts are excluded: documented line-ending issue, see the S6-6 commit notes)
  - the corpus fingerprint of both indexes and the heading fingerprint / structure version of faiss_store_v2
  - that the working copy of the retrieval source and indexes has no difference from commit 5fc1370
Usage: python eval/stage7/check_stage6_integrity.py before|after [experiment, default s7_0]   (from the project root)
Writes eval/stage7/<experiment>_integrity_<label>.json and exits non-zero on any mismatch.
"""
import hashlib, json, os, subprocess, sys, time

ACCEPTED_COMMIT = "5fc13708bc6e03f29fc0d12c02884fde647d1cfb"
EXCLUDED = {"eval/stage6/run_s6_6.py", "eval/stage6/make_s6_6_sheet.py", "eval/stage6/report_s6_6.py"}
HEADING_FINGERPRINT = "sha256:7ce5f4d96a17b4498b3de1240afb563c5b73cefd9ef92114e6c467cd49c68b8c"
STAGE6_PATHS = ["src/vectorstore.py", "src/embedding.py", "src/retrieval_v2.py", "src/rerank.py", "src/structure.py",
                "src/heading_store.py", "src/ambiguity.py", "faiss_store", "faiss_store_v2"]

label = sys.argv[1]
experiment = sys.argv[2] if len(sys.argv) > 2 else "s7_0"
freeze = json.load(open("eval/stage6/s6_6_freeze.json"))


def sha256(path):
    digest = hashlib.sha256()
    with open(os.path.expanduser(path), "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


files = {path: sha256(path) == digest for path, digest in freeze["sha256"].items() if path not in EXCLUDED}
manifests = {store: json.load(open(f"{store}/manifest.json")) for store in ("faiss_store", "faiss_store_v2")}
fingerprints = {
    "faiss_store corpus": manifests["faiss_store"]["corpus_fingerprint"] == freeze["corpus_fingerprint"],
    "faiss_store_v2 corpus": manifests["faiss_store_v2"]["corpus_fingerprint"] == freeze["corpus_fingerprint"],
    "faiss_store_v2 heading": manifests["faiss_store_v2"]["heading_fingerprint"] == HEADING_FINGERPRINT,
    "faiss_store_v2 structure_version": manifests["faiss_store_v2"]["structure_version"] == "v2",
}
head = git("rev-parse", "HEAD")
git_checks = {
    "accepted_commit_is_ancestor_of_head":
        subprocess.run(["git", "merge-base", "--is-ancestor", ACCEPTED_COMMIT, head]).returncode == 0,
    "stage6_paths_unchanged_since_accepted_commit": git("diff", "--name-only", ACCEPTED_COMMIT, "--", *STAGE6_PATHS) == "",
}
passed = all(files.values()) and all(fingerprints.values()) and all(git_checks.values())
report = {"experiment": experiment, "label": label, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "head": head,
          "accepted_stage6_commit": ACCEPTED_COMMIT, "freeze_record": "eval/stage6/s6_6_freeze.json",
          "excluded_from_hash_check": sorted(EXCLUDED),
          "excluded_reason": "S6-6 evaluation scripts: documented LF/CRLF line-ending issue; not modified in S7-0",
          "files_checked": len(files), "file_hash_matches": files, "fingerprints": fingerprints, "git": git_checks,
          "passed": passed}
json.dump(report, open(f"eval/stage7/{experiment}_integrity_{label}.json", "w"), indent=1)
print(f"{label}: {sum(files.values())}/{len(files)} hashes match | fingerprints {fingerprints} | git {git_checks}")
print("PASSED" if passed else "FAILED: " + ", ".join(p for p, ok in files.items() if not ok))
sys.exit(0 if passed else 1)
