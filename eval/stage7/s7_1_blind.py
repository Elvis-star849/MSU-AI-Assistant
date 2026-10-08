"""S7-1 blind grading tools. Run from the project root.

  sample <out_dir>   preflight preview: both grading packages built with placeholder answers (mapping discarded)
  packages           after all 75 items succeeded: build the absolute and pairwise packages (repository, blind) and
                     their label mappings (~/rag_private/s7_1, private); record sha256 commitments in the repository
  validate           check eval/stage7/s7_1_grading/{absolute,pairwise}_grades_raw.json are complete and well formed
  spotcheck          build the blind owner spot-check sheet (eval/stage7/s7_1_grading/owner_spot_check.txt)
"""
import json, os, sys

sys.path.insert(0, ".")
sys.path.insert(0, "eval/stage7")
from s7_1_core import (PRIVATE_DIR, build_absolute_package, build_pairwise_package, new_blind_rng, read_attempts,
                       sha256_file, spot_check_selection, strip_markdown, validate_absolute, validate_pairwise)

GRADING = "eval/stage7/s7_1_grading"
ABS_MAP = os.path.join(PRIVATE_DIR, "s7_1_absolute_mapping.json")
PAIR_MAP = os.path.join(PRIVATE_DIR, "s7_1_pairwise_mapping.json")
COMMITMENT = "eval/stage7/s7_1_blinding_commitment.json"
command = sys.argv[1]
design = json.load(open("eval/stage7/s7_1_design.json", encoding="utf-8"))
evidence = json.load(open("eval/stage7/s7_1_evidence.json", encoding="utf-8"))
manifest = json.load(open("eval/stage7/s7_1_manifest.json", encoding="utf-8"))


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


if command == "sample":
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    placeholder = {i["item_id"]: "**[placeholder answer - no generation has happened]**" for i in manifest["order"]}
    a_text, a_map = build_absolute_package(design, evidence, placeholder, new_blind_rng())
    p_text, p_map = build_pairwise_package(design, evidence, placeholder, new_blind_rng())
    write(os.path.join(out, "absolute_package_SAMPLE.txt"), a_text)
    write(os.path.join(out, "pairwise_package_SAMPLE.txt"), p_text)
    leaked = [w for w in ("arm0", "arm1", "arm2", "replicate", "Arm 0", "prompt", "/arm") if w in a_text + p_text]
    print(json.dumps({"absolute_labels": len(a_map), "pairwise_comparisons": len(p_map),
                      "absolute_chars": len(a_text), "pairwise_chars": len(p_text),
                      "arm_or_prompt_words_in_packages": leaked}, indent=1))

elif command == "packages":
    attempts = read_attempts(os.path.join(PRIVATE_DIR, "s7_1_runs.jsonl"))
    answers = {a["item_id"]: a["answer"] for a in attempts if a["succeeded"]}
    assert set(answers) == {i["item_id"] for i in manifest["order"]}, "all 75 items must have succeeded first"
    assert not os.path.exists(ABS_MAP) and not os.path.exists(PAIR_MAP), "packages already built"
    os.makedirs(GRADING, exist_ok=True)
    a_rng, p_rng = new_blind_rng(), new_blind_rng()
    a_text, a_map = build_absolute_package(design, evidence, answers, a_rng)
    p_text, p_map = build_pairwise_package(design, evidence, answers, p_rng)
    write(f"{GRADING}/absolute_package.txt", a_text)
    write(f"{GRADING}/pairwise_package.txt", p_text)
    json.dump({"seed": a_rng.seed_value, "mapping": a_map}, open(ABS_MAP, "w"), indent=1)
    json.dump({"seed": p_rng.seed_value, "mapping": p_map}, open(PAIR_MAP, "w"), indent=1)
    json.dump({"absolute_mapping_sha256": sha256_file(ABS_MAP), "pairwise_mapping_sha256": sha256_file(PAIR_MAP),
               "absolute_package_sha256": sha256_file(f"{GRADING}/absolute_package.txt"),
               "pairwise_package_sha256": sha256_file(f"{GRADING}/pairwise_package.txt"),
               "private_dir": "~/rag_private/s7_1", "note": "mappings stay private until grading is complete"},
              open(COMMITMENT, "w"), indent=1)
    print(f"packages built: {len(a_map)} absolute labels, {len(p_map)} pairwise comparisons; commitments recorded")

elif command == "validate":
    a_map = json.load(open(ABS_MAP))["mapping"]
    p_map = json.load(open(PAIR_MAP))["mapping"]
    a = json.load(open(f"{GRADING}/absolute_grades_raw.json", encoding="utf-8"))
    p = json.load(open(f"{GRADING}/pairwise_grades_raw.json", encoding="utf-8"))
    problems = {"absolute": validate_absolute(a, a_map), "pairwise": validate_pairwise(p, p_map)}
    print(json.dumps(problems, indent=1))
    sys.exit(1 if any(problems.values()) else 0)

elif command == "spotcheck":
    a_map = json.load(open(ABS_MAP))["mapping"]
    p_map = json.load(open(PAIR_MAP))["mapping"]
    a = json.load(open(f"{GRADING}/absolute_grades_raw.json", encoding="utf-8"))
    p = json.load(open(f"{GRADING}/pairwise_grades_raw.json", encoding="utf-8"))
    attempts = {x["item_id"]: x["answer"] for x in read_attempts(os.path.join(PRIVATE_DIR, "s7_1_runs.jsonl"))
                if x["succeeded"]}
    sel = spot_check_selection(a, a_map, p_map, design["owner_spot_check"]["sample_seed"])
    grades = {e["label"]: e for e in a["main"] + a["oos"]}
    pref = {e["label"]: e for e in p["pairwise"]}
    lines = ["S7-1 OWNER SPOT-CHECK (blind: labels only, no arm mapping)", ""]
    for title, labels in (("HALLUCINATION / INVENTED-MSU FLAGS", sel["hallucination_flags"]),
                          ("RANDOM ONE-THIRD OF ABSOLUTE GRADES", sel["absolute_sample"])):
        lines.append(f"######## {title} ({len(labels)})")
        for label in labels:
            qid = label.rsplit("-", 1)[0]
            lines += [f"---- {label} | {evidence['questions'][qid]['question']}",
                      strip_markdown(attempts[a_map[label]]), "GRADE: " + json.dumps(grades[label]), ""]
    lines.append(f"######## MAIN PAIRWISE JUDGEMENTS ({len(sel['main_pairwise'])})")
    for label in sel["main_pairwise"]:
        m = p_map[label]
        lines += [f"---- {label} | {evidence['questions'][m['question_id']]['question']}",
                  "A: " + strip_markdown(attempts[m["A"]]), "B: " + strip_markdown(attempts[m["B"]]),
                  "JUDGEMENT: " + json.dumps(pref[label]), ""]
    write(f"{GRADING}/owner_spot_check.txt", "\n".join(lines))
    json.dump(sel, open(f"{GRADING}/owner_spot_check_selection.json", "w"), indent=1)
    print({k: len(v) for k, v in sel.items()})

else:
    sys.exit(f"unknown command {command}")
