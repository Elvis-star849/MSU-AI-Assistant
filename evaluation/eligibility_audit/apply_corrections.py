"""
Apply the recorded corrections (corrections.json) to the supplied rules file and write the corrected rules file.

    python evaluation/eligibility_audit/apply_corrections.py [--check]

Input:  src/eligibility/MSU_Eligibility_Rules.supplied.json (the file as supplied; never modified)
Output: src/eligibility/MSU_Eligibility_Rules.json (meta.version and meta.corrections record what changed)
Each correction asserts its 'old' value before changing it, so a correction can never silently overwrite something
else. --check verifies that the current corrected file is exactly what the corrections produce.
"""
import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPLIED = ROOT / "src/eligibility/MSU_Eligibility_Rules.supplied.json"
CORRECTED = ROOT / "src/eligibility/MSU_Eligibility_Rules.json"
CORRECTIONS = Path(__file__).with_name("corrections.json")
ADVERT = ROOT / ("knowledge_base/uploads/a91f01d6c67f3f90e21d99f03408eed7d01a18d9dcd8def1ea3d76898a470cbc/"
                 "MSU_2027_Intake_Corrected_v2.json")


def build() -> dict:
    rules = json.loads(SUPPLIED.read_text(encoding="utf-8"))
    out = deepcopy(rules)
    progs = {p["id"]: p for p in out["programmes"]}
    corrections = json.loads(CORRECTIONS.read_text(encoding="utf-8"))["corrections"]
    advert = {r["id"]: r for r in json.loads(ADVERT.read_text(encoding="utf-8"))["programmes"]}
    for c in corrections:
        field = c["field"]
        if field.startswith("o_level_rule.required_subjects."):
            subject = field.rsplit(".", 1)[1]
            for pid in c["programmes"]:
                req = progs[pid]["o_level_rule"]["required_subjects"]
                assert subject not in req, (c["id"], pid, "old value is not absent")
                req[subject] = c["new"]
        elif field == "requirements_as_advertised":
            for pid in c["programmes"]:
                assert len(progs[pid]["requirements_as_advertised"]) == 4, (c["id"], pid)
                progs[pid]["requirements_as_advertised"] = list(advert[pid]["entry_requirements"])
        elif field.startswith("taxonomy."):
            subject = field.split(".", 1)[1]
            assert out["taxonomy"][subject] == c["old"], (c["id"], subject)
            out["taxonomy"][subject] = list(c["new"])
        else:
            raise SystemExit(f"unknown correction field {field}")
    out["meta"]["version"] = "2027-jf-v2-corrected"
    out["meta"]["corrections"] = {"supplied_file_sha256": hashlib.sha256(SUPPLIED.read_bytes()).hexdigest(),
                                  "corrections_file": "evaluation/eligibility_audit/corrections.json",
                                  "applied": [c["id"] for c in corrections]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if a.check:
        same = CORRECTED.read_text(encoding="utf-8") == text
        print("corrected rules file is up to date" if same else "corrected rules file differs from the corrections")
        return 0 if same else 1
    CORRECTED.write_text(text, encoding="utf-8")
    print("wrote", CORRECTED.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
