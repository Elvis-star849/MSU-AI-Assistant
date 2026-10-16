"""
Build src/eligibility/entry_routes.json: the structured admission-route conditions used by src/entry_routes.py.

    python evaluation/eligibility_audit/build_entry_routes.py [--check]

Sources (nothing is invented; every condition is traceable):
- mature entry per programme: the advert wording kept in MSU_Eligibility_Rules.json (mature_entry_text, copied
  verbatim as 'quote'). Each encoded condition must be visible in that quote (asserted below), except the conditions
  marked 'from_general_regulation', which come from the general regulation quoted under 'general_regulations';
- general regulations: MSU Humanities Yearbook, General Academic Regulations for Undergraduate Degrees, section 3.2
  (Special Entry) and 3.3 (Mature Entry), p. 129, quoted verbatim from knowledge base 0006 (yearbook regulations may be
  older than the 2027 advert; the app says so).
--check verifies that the file on disk is what this script builds.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "src/eligibility/MSU_Eligibility_Rules.json"
OUT = ROOT / "src/eligibility/entry_routes.json"
AGE = {"female": 23, "male": 25}
WEEKEND = ["Harare Weekend School", "Bulawayo Weekend School"]
INDIGENOUS = ["Barwe", "Khoisan", "Ndau", "Chewa", "Shangani", "Tswana", "Xhosa", "Venda", "Sotho", "Kalanga", "Nambya",
              "Tonga"]

GENERAL = {
    "mature": {
        "source": "MSU Humanities Yearbook", "page": 129,
        "section": "General Academic Regulations for Undergraduate Degrees, 3.3 Mature Entry",
        "quote": ("Persons who are at least 25 years of age for males and 23 years for females on the first day of the "
                  "academic year in which admission is sought and who are not eligible for entry under the Normal or "
                  "Special Entry Regulations may apply for Mature Entry provided that: 3.3.1 applicants must have passed "
                  "at least five approved 'O' Level subjects including English Language and Mathematics (where "
                  "required) or equivalents, and must have demonstrated potential suitability for University studies "
                  "by virtue of their attainments and/or relevant work experience. 3.3.2 normally, applicants should "
                  "have completed their full-time school or college education at least five years before the start of "
                  "the academic year in which admission is sought. 3.3.3 applicants who wish to be considered under the "
                  "Mature Entry provisions may be required to attend interviews and/or special tests at the University "
                  "designed to assess their command of the English Language, numeracy and reasoning ability and general "
                  "suitability for admission to the Bachelor's degree studies."),
        "age": AGE,
    },
    "special": {
        "source": "MSU Humanities Yearbook", "page": 129,
        "section": "General Academic Regulations for Undergraduate Degrees, 3.2 Special Entry",
        "quote": ("The following persons may apply for Special Entry and for permission to proceed to a first degree "
                  "with exemption from the whole or part of the normal entry requirements: - 3.2.1 a person who has "
                  "obtained a degree of this or another university or degree awarding institution. 3.2.2 a person who "
                  "has obtained from a University or an Institution of similar status, academic qualifications (other "
                  "than degrees) acceptable to Senate. [...] 3.2.4 students who apply for admission under this "
                  "regulation may be required to attend interviews and/or special tests at the University to determine "
                  "their suitability for admission to Bachelor's degree studies."),
    },
}

SCIENCE = {"age": AGE, "o_level_passes": 5, "o_level_subjects": ["English Language", "Mathematics", "Science"],
           "work_years": 5, "work_relevant": True}
MATURE = {
    "MSU-JF2027-026": {"age": AGE, "o_level_passes": 5, "o_level_subjects": ["English Language"],
                       "from_general_regulation": ["o_level_passes", "o_level_subjects"]},
    "MSU-JF2027-027": {"age": AGE, "o_level_passes": 5, "o_level_subjects": ["English Language"],
                       "from_general_regulation": ["o_level_passes", "o_level_subjects"]},
    **{pid: {"age": AGE, "o_level_passes": 5, "o_level_subjects": ["English Language"], "employed_related": True,
             "modes": WEEKEND}
       for pid in ("MSU-JF2027-029", "MSU-JF2027-030", "MSU-JF2027-031", "MSU-JF2027-032")},
    "MSU-JF2027-058": {"age": AGE, "o_level_passes": 5, "o_level_subjects": ["English Language"],
                       "suitability": True},
    "MSU-JF2027-100": {"age": AGE, "o_level_passes": 5, "o_level_subjects": ["English Language"],
                       "o_level_any_of": INDIGENOUS, "from_general_regulation": ["age"]},
    **{pid: SCIENCE for pid in ("MSU-JF2027-148", "MSU-JF2027-151", "MSU-JF2027-154", "MSU-JF2027-155",
                                "MSU-JF2027-156", "MSU-JF2027-157", "MSU-JF2027-159", "MSU-JF2027-165",
                                "MSU-JF2027-166", "MSU-JF2027-168")},
}
# words that must be visible in the advert quote for each encoded condition
EVIDENCE = {"age": ["23", "25"], "o_level_passes": ["5", "O"], "employed_related": ["employ"],
            "work_years": ["5 years"], "work_relevant": ["relevant field"], "suitability": ["work experience"],
            "modes": ["Weekend School"], "o_level_any_of": INDIGENOUS[:3]}


def build() -> dict:
    rules = {p["id"]: p for p in json.loads(RULES.read_text(encoding="utf-8"))["programmes"]}
    mature = {}
    for pid, cond in MATURE.items():
        p = rules[pid]
        quote = " ".join(p["mature_entry_text"])
        assert p["has_mature_entry"] and quote, pid
        general = set(cond.get("from_general_regulation", []))
        for key, words in EVIDENCE.items():
            if key in cond and key not in general:
                missing = [w for w in words if w not in quote]
                assert not missing, (pid, key, missing)
        for subject in cond.get("o_level_subjects", []):
            if "o_level_subjects" not in general:
                assert subject.split()[0] in quote, (pid, subject)
        mature[pid] = {"programme": p["programme"], "page": p["source_page"], "quote": quote, "conditions": cond}
    assert set(mature) == {pid for pid, p in rules.items() if p["has_mature_entry"]}, "every advertised mature route"
    return {"note": "Built by evaluation/eligibility_audit/build_entry_routes.py from the advert wording in "
                    "MSU_Eligibility_Rules.json and the general regulations quoted below. Do not edit by hand.",
            "general_regulations": GENERAL, "mature_entry": mature}


def main() -> int:
    data = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == data
        print("entry routes file is up to date" if ok else "entry routes file is OUT OF DATE")
        return 0 if ok else 1
    OUT.write_text(data, encoding="utf-8", newline="\n")
    print("wrote", OUT.relative_to(ROOT), "-", len(MATURE), "advertised mature-entry routes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
