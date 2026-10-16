"""
Audit src/eligibility/MSU_Eligibility_Rules.json against the official January/February 2027 intake advert.
Read-only: the rules file is never changed.

    python evaluation/eligibility_audit/audit_rules.py

Sources:
- the original advert PDF (data/source_pdfs/MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf);
- the approved structured advert records used for knowledge base 0006 (MSU_2027_Intake_Corrected_v2.json).

Per programme: (1) the rule's name, faculty, duration, modes, page and requirement text against the structured record;
(2) the requirement words found on the PDF page; (3) whether each element of the coded rule (A Level subjects, number
of subjects, minimum grades, points, O Level subjects and grades, employment) is supported by the advert wording;
(4) ambiguity markers ("preferably", alternatives, "relevant", diploma routes not modelled, ...). Heuristic checks
flag items for a human; they do not prove a rule right or wrong.

Reviewer verdicts in manual_review.json (beside this script) are merged into the results ('reviewed_status').
Writes evaluation/results/eligibility_rules_audit/rules_audit.json and rules_audit.csv, and
src/eligibility/rule_warnings.json: short warnings for programmes whose rule has a confirmed mismatch or an open
question. Informational since the corrected rules: the app itself reads src/eligibility/rule_overrides.json, which
turns each open question into a 'conditional' result with the question shown, never a definitive one.
Verdict 'corrected' = fixed in the corrected rules file (see corrections.json); it reverts to 'mismatch' if the
automatic check fails again.
"""
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "src/eligibility/MSU_Eligibility_Rules.json"
ADVERT_JSON = ROOT / ("knowledge_base/uploads/a91f01d6c67f3f90e21d99f03408eed7d01a18d9dcd8def1ea3d76898a470cbc/"
                      "MSU_2027_Intake_Corrected_v2.json")
ADVERT_PDF = ROOT / "data/source_pdfs/MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf"
OUT = ROOT / "evaluation/results/eligibility_rules_audit"
REVIEW = Path(__file__).with_name("manual_review.json")
WARNINGS = ROOT / "src/eligibility/rule_warnings.json"     # read by the app: shown next to affected programmes
CATEGORIES = {"SCI": "any science subject", "COM": "any commercial subject", "ARTS": "any arts/humanities subject",
              "LANG": "any language subject", "ANY": "any subject"}
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "1": 1, "2": 2, "3": 3}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(text):
    text = (text or "").replace("�", "'").replace("’", "'").replace("‘", "'").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip().lower()


def words(text):
    return {w for w in re.findall(r"[a-z]{4,}", norm(text))}


def subject_names(subject, aliases):
    names = {subject.lower()} | {a for a, s in aliases.items() if s == subject}
    if subject == "Mathematics":
        names |= {"maths", "math", "mathematics"}
    return names


def describe_rule(p):
    r, o = p["a_level_rule"], p["o_level_rule"]
    parts = []
    if p["route"] == "a_level":
        slots = []
        for s in r["slots"]:
            opts = [CATEGORIES.get(t, t) for t in s["any_of"]]
            slots.append(" or ".join(opts) + (f" (grade {s['min_grade']} or better)" if s.get("min_grade") else ""))
        parts.append(f"A Level: {len(slots)} passes: " + "; ".join(slots))
        if r.get("min_points"):
            parts.append(f"at least {r['min_points']} points (best three)")
        if r.get("requires_employment"):
            parts.append("employment required")
    elif p["route"] == "o_level_only":
        parts.append("O Level route only (no A Level rule)")
    else:
        parts.append("not decided by grades (diploma / qualification / employment route; advert text shown)")
    subs = ", ".join(f"{k}{' ' + v + '+' if v else ''}" for k, v in o["required_subjects"].items())
    parts.append(f"O Level: {o['min_passes']} passes at {o['min_pass_grade']}+ incl. {subs}")
    return "; ".join(parts)


def audit_programme(p, rec, pages, aliases):
    issues, ambiguities, info = [], [], []
    req = " ".join(p["requirements_as_advertised"])
    rec_req = " ".join(rec["entry_requirements"])
    text = norm(rec_req)
    context = norm(" ".join([rec_req, rec.get("faculty_note") or "", rec.get("programme_note") or ""]))

    # (1) record fields
    if norm(p["programme"]) != norm(rec["programme"]):
        issues.append(f"programme name differs from advert record: '{rec['programme']}'")
    if norm(p["faculty"]) != norm(rec["faculty"]):
        issues.append(f"faculty differs from advert record: '{rec['faculty']}'")
    if norm(p["duration"]) != norm(rec["duration_as_advertised"]):
        issues.append(f"duration differs: rule '{p['duration']}' vs advert '{rec['duration_as_advertised']}'")
    rec_modes = [m["as_written"] for m in rec["modes_of_entry"]]
    if [norm(m) for m in p["modes"]] != [norm(m) for m in rec_modes]:
        issues.append(f"modes differ: rule {p['modes']} vs advert {rec_modes}")
    if p["source_page"] != rec["source_page"]:
        issues.append(f"source page differs: rule {p['source_page']} vs advert {rec['source_page']}")
    if norm(req) != norm(rec_req):
        issues.append("requirement text differs from the advert record")

    # (2) original PDF page
    page_text = " ".join(pages.get(n, "") for n in (rec["source_page"] - 1, rec["source_page"], rec["source_page"] + 1))
    req_words = words(rec_req)
    coverage = len(req_words & words(page_text)) / len(req_words) if req_words else 1.0
    if coverage < 0.8:
        issues.append(f"only {coverage:.0%} of the requirement words found on PDF pages {rec['source_page']}±1")

    # (3) coded rule elements supported by the advert wording
    r, o = p["a_level_rule"], p["o_level_rule"]
    if p["route"] == "a_level":
        for s in r["slots"]:
            for t in s["any_of"]:
                if t in CATEGORIES:
                    continue
                if not any(re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", text) for n in subject_names(t, aliases)):
                    issues.append(f"A Level subject '{t}' in the rule is not named in the advert requirement")
        cats = sorted({t for s in r["slots"] for t in s["any_of"] if t in CATEGORIES and t != "ANY"})
        if cats:
            info.append("subject categories used (" + ", ".join(cats) + "): category membership is an assumption to confirm")
        m = re.search(r"\b(one|two|three|four|[123])\b[^.]{0,40}?\ba[' ]?\s*level", text) or \
            re.search(r"\ba[' ]?\s*level\b[^.]{0,15}?\b(one|two|three|[123])\b", text)
        if m and NUM_WORDS[m.group(1)] != len(r["slots"]):
            issues.append(f"advert says {m.group(1)} A Level subject(s); rule has {len(r['slots'])} slot(s)")
        elif not m:
            ambiguities.append(f"number of A Level passes not stated as a number; rule assumes {len(r['slots'])}")
        grades_in_text = re.search(r"\b(?:with (?:an? )?|grade |at least (?:an? )?)([a-e])\b|\b([a-e]) or better\b", text)
        rule_grades = [s["min_grade"] for s in r["slots"] if s.get("min_grade")]
        if rule_grades and not grades_in_text:
            issues.append(f"rule sets A Level minimum grade(s) {rule_grades} not found in the advert wording")
        if grades_in_text and not rule_grades and "o level" not in text[max(0, grades_in_text.start() - 40):grades_in_text.start()]:
            ambiguities.append("advert wording mentions a grade that the A Level rule does not use (check whether it is an O Level grade)")
        if bool(re.search(r"\bpoints?\b", text)) != bool(r.get("min_points")):
            issues.append("points requirement: advert and rule disagree")
        if bool(re.search(r"employ", text)) != bool(r.get("requires_employment")):
            ambiguities.append("employment wording vs rule.requires_employment differ (often an alternative route)")
        if re.search(r"\b(diploma|hnd|national certificate|nc\b|nd\b)", text):
            ambiguities.append("advert also allows a diploma/certificate route that the A Level rule does not model")
    elif p["route"] == "other_qualification" and re.search(r"\ba[' ]?\s*levels?\b", text):
        ambiguities.append("advert mentions A Levels but the programme is not decided by grades (route kept as text)")
    for subj, grade in o["required_subjects"].items():
        if subj == "English Language":
            continue
        if not any(n in context for n in subject_names(subj, aliases) | ({"science"} if "Science" in subj else set())):
            issues.append(f"O Level subject '{subj}' in the rule is not named in the advert text or faculty note")
        elif grade and not re.search(rf"\b{grade.lower()}\b", context):
            issues.append(f"O Level {subj} grade {grade} in the rule not found in the advert text or faculty note")
    note = norm(rec.get("faculty_note") or "")
    if "maths required for all" in note.replace("mathematics", "maths") and "Mathematics" not in o["required_subjects"]:
        issues.append("faculty note requires O Level Maths for all programmes, but the rule does not require it")
    if "some programmes" in note:
        info.append("faculty note: O Level Maths 'required for some programmes' (which ones is not stated)")

    # (4) ambiguity markers in the advert wording
    for pattern, label in ((r"\bpreferabl", "'preferably' wording (preference or requirement?)"),
                           (r"\brelevant\b", "'relevant' subject/qualification (not defined)"),
                           (r"\bequivalent\b", "'equivalent' qualification (not defined)"),
                           (r"\bany other\b", "'any other' subject/qualification"),
                           (r"\bconsidered\b", "'may be considered' (discretionary)"),
                           (r"\band/or\b|/", "'/' or 'and/or' alternatives (scope unclear)")):
        if re.search(pattern, text):
            ambiguities.append(label)
    for n in p.get("modelling_notes") or []:
        info.append("modeller's note: " + n)
    status = "mismatch" if issues else "needs_human_verification" if ambiguities else "consistent"
    return {"id": p["id"], "programme": p["programme"], "faculty": p["faculty"], "source_page": rec["source_page"],
            "route": p["route"], "advert_requirements": rec["entry_requirements"], "faculty_note": rec.get("faculty_note"),
            "rule_as_coded": describe_rule(p), "pdf_requirement_word_coverage": round(coverage, 2), "status": status,
            "mismatches": issues, "ambiguities": ambiguities, "info": info}


def main():
    import pymupdf as fitz
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    advert = json.loads(ADVERT_JSON.read_text(encoding="utf-8"))
    records = {r["id"]: r for r in advert["programmes"]}
    with fitz.open(ADVERT_PDF) as pdf:
        pages = {i + 1: page.get_text() for i, page in enumerate(pdf)}
    rows = []
    for p in rules["programmes"]:
        rec = records.get(p["id"])
        if rec is None:
            rows.append({"id": p["id"], "programme": p["programme"], "status": "mismatch",
                         "mismatches": ["no advert record with this id"], "ambiguities": [], "info": []})
            continue
        rows.append(audit_programme(p, rec, pages, rules["aliases"]))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))["verdicts"] if REVIEW.exists() else {}
    warnings = {}
    for r in rows:
        v = review.get(r["id"])
        r["review"] = v
        if v is None:
            r["reviewed_status"] = r["status"]
        elif v["verdict"] == "audit_false_positive":
            r["reviewed_status"] = "needs_human_verification" if r["ambiguities"] else "consistent"
        elif v["verdict"] == "confirmed_mismatch":
            r["reviewed_status"] = "mismatch_confirmed"
        elif v["verdict"] == "corrected":            # fixed in the corrected rules file (corrections.json)
            r["reviewed_status"] = ("mismatch" if r["status"] == "mismatch" else "corrected")
        else:
            r["reviewed_status"] = "needs_human_verification"
        if v and v["verdict"] == "confirmed_mismatch" and v["impact"] in ("high", "medium"):
            warnings[r["id"]] = v.get("user_warning") or ("Rule under review: " + v["finding"].rstrip(".") +
                                                           ". Check this requirement with the Admissions Office.")
        elif v and v["verdict"] == "ambiguous" and v["impact"] in ("high", "medium"):
            warnings[r["id"]] = "Rule under review: the advert wording is ambiguous (" +                                 (v.get("question_for_admissions") or v["finding"]).rstrip(".?") + "). Check with the Admissions Office."
    covered = {p["id"] for p in rules["programmes"]}
    ug_ids = {r["id"] for r in records.values() if not r["level"].startswith("Postgraduate")}
    summary = {"rules_file_sha256": sha(RULES), "advert_records_sha256": sha(ADVERT_JSON), "advert_pdf_sha256": sha(ADVERT_PDF),
               "advert_pdf_pages": len(pages), "programmes_in_rules": len(rows),
               "undergraduate_and_diploma_records_in_advert": len(ug_ids),
               "advert_programmes_missing_from_rules": sorted(ug_ids - covered),
               "rules_not_in_advert": sorted(covered - set(records)),
               "status_counts": dict(Counter(r["status"] for r in rows)),
               "reviewed_status_counts": dict(Counter(r["reviewed_status"] for r in rows)),
               "user_facing_warnings": len(warnings),
               "route_counts": dict(Counter(r.get("route") for r in rows)),
               "mismatch_types": dict(Counter(re.sub(r"'[^']*'|\[.*?\]|\d+%|[A-E]\b|\d+", "…", m)
                                              for r in rows for m in r["mismatches"]).most_common()),
               "ambiguity_types": dict(Counter(a for r in rows for a in r["ambiguities"]).most_common()),
               "global_assumptions": rules["meta"].get("assumptions", [])}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rules_audit.json").write_text(json.dumps({"summary": summary, "programmes": rows}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    WARNINGS.write_text(json.dumps({"generated_by": "evaluation/eligibility_audit/audit_rules.py",
                                    "rules_file_sha256": summary["rules_file_sha256"], "warnings": warnings},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    with open(OUT / "rules_audit.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "programme", "faculty", "source_page", "route", "status", "reviewed_status", "review_finding",
                    "advert_requirements", "rule_as_coded", "mismatches", "ambiguities", "info"])
        for r in rows:
            w.writerow([r["id"], r["programme"], r.get("faculty", ""), r.get("source_page", ""), r.get("route", ""),
                        r["status"], r.get("reviewed_status", ""), (r.get("review") or {}).get("finding", ""),
                        " | ".join(r.get("advert_requirements", [])), r.get("rule_as_coded", ""),
                        " | ".join(r["mismatches"]), " | ".join(r["ambiguities"]), " | ".join(r["info"])])
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
