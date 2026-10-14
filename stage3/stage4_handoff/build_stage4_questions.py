"""
Build the DRAFT Stage 4 question set (revision 2) with system-specific answer keys and verified evidence.

Every evidence quote is checked twice, never corrected silently:
  1. in the registered dataset record (intake / road map) or the frozen yearbook chunk (faiss_store_v2), and
  2. in the original source PDF page (text layer, normalised: case, quotes, dashes, punctuation, whitespace).
Unverified quotes are listed as discrepancies in the output.

Run from the MSU-AI-Assistant root:  python stage3/stage4_handoff/build_stage4_questions.py
Outputs (stage3/stage4_handoff/): stage4_questions_draft.json, stage4_answer_evidence.md,
regression_review_copy.md. Read-only on all project data. The set stays a DRAFT until the owner freezes it.
"""
import hashlib
import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
KB = ROOT / "knowledge_base"
DOCS = ROOT.parent / "msu docs"
PDF = {"intake": ROOT / "data/source_pdfs/MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf",
       "roadmap": ROOT / "data/source_pdfs/2027 DRAFT ROADMAP fin (1).pdf",
       "yearbook-humanities": DOCS / "HUMANITIES -GENERAL INFORMATION AND REGULATIONS final done (1).pdf",
       "yearbook-sciences-v2": DOCS / "SCIENCES - GENERAL INFORMATION AND REGULATIONS VOLUME2 final done (1).pdf"}
LABEL = {"intake": "MSU January/February 2027 Intake Advert", "roadmap": "MSU 2027 Road Map",
         "yearbook-humanities": "MSU Humanities Yearbook", "yearbook-sciences-v2": "MSU Sciences Yearbook Vol. 2"}
UIDP = {"intake": "intake-2027-jan-feb/v1/", "roadmap": "roadmap-2027/v1/"}

registry = json.loads((KB / "registry.json").read_text(encoding="utf-8"))
docs = {d["doc_id"]: d for d in registry["documents"]}
road = json.loads((KB / docs["roadmap-2027"]["dataset"]["path"]).read_text(encoding="utf-8"))
intake = json.loads((KB / docs["intake-2027-jan-feb"]["dataset"]["path"]).read_text(encoding="utf-8"))
RECORD = {**{e["id"]: e for e in road["events"]}, **{p["id"]: p for p in intake["programmes"]},
          **{r["id"]: r for r in intake["information_records"]}}
CHUNKS = [json.loads(l) for l in open(ROOT / "faiss_store_v2/chunks.jsonl", encoding="utf-8")]
_pdf_cache = {}


def norm(s: str) -> str:
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("½", " 1/2 ").replace("�", " ")
    return " ".join(re.findall(r"[a-z0-9$@/]+", s.lower()))


def pdf_page(doc, page):
    key = (doc, page)
    if key not in _pdf_cache:
        with pymupdf.open(PDF[doc]) as pdf:
            _pdf_cache[key] = norm(pdf[page - 1].get_text())
    return _pdf_cache[key]


def record_text(doc, ref):
    if doc in ("intake", "roadmap"):
        r = RECORD[ref]
        return norm(json.dumps({k: v for k, v in r.items() if k not in ("verification",)}, ensure_ascii=False))
    return norm(CHUNKS[ref]["text"])


def ev(doc, ref, page, quote, printed_in_source=True, note=None):
    """One evidence item: doc ('intake', 'roadmap', yearbook doc_id), record id or chunk id, PDF page, verbatim quote.
    printed_in_source=False marks an approved correction: the quote is the approved value in the registered record and
    is, by design, not printed in the source PDF (the printed original is given as a separate evidence item)."""
    uid = UIDP[doc] + ref if doc in UIDP else f"{doc}/v1/c{ref:05d}"
    e = {"doc": doc, "passage_uid": uid, "page": page, "citation": f"{LABEL[doc]}, p. {page}", "quote": quote,
         "printed_in_source": printed_in_source}
    if note:
        e["note"] = note
    return e


def key(behaviour, required=(), evidence=(), forbidden=(), note=None, full_credit=None, partial_credit=None):
    k = {"behaviour": behaviour, "required": list(required), "evidence": list(evidence),
         "acceptable_citations": sorted({e["citation"] for e in evidence}), "forbidden": list(forbidden)}
    if note:
        k["note"] = note
    if full_credit:
        k["full_credit"] = full_credit
    if partial_credit:
        k["partial_credit"] = partial_credit
    return k


NA_2027 = "not_available"
ROADMAP_BASELINE = key(NA_2027, ["says the 2027 dates are not in the available documents"],
                       forbidden=["any 2027 date", "dates borrowed from yearbook general regulations presented as 2027 dates"],
                       note="faiss_store_v2 contains no 2027 road map (control only; not in the call matrix)")


def rm_q(qid, question, rid, activity_check, tags=(), equivalents=None, forbidden=()):
    e = RECORD[rid]
    if e["date_corrected"]:
        evid = [ev("roadmap", rid, 1, e["dates"], printed_in_source=False,
                   note="approved date (project owner confirmation 2026-10-13); recorded in the registered dataset and "
                        "correction history"),
                ev("roadmap", rid, 1, e["dates_in_source"], note="text printed in the original PDF (kept for traceability)")]
    else:
        evid = [ev("roadmap", rid, 1, e["dates"])]
    item = {"id": qid, "category": "roadmap", "question": question, "primary_passage": UIDP["roadmap"] + rid,
            "calendar": e["calendar_group"], "semester": e["semester"], "activity": e["activity"], "tags": list(tags),
            "keys": {"baseline": ROADMAP_BASELINE}}
    pub = key("answer", [f"{e['activity']} ({e['calendar_group']}, {e['semester']}): {e['dates']}", activity_check],
              evid, forbidden=list(forbidden))
    if equivalents:
        pub["equivalent_records"] = equivalents
    item["keys"]["public"] = item["keys"]["staging"] = pub
    return item


roadmap_qs = [
    rm_q("R01", "When does registration for the first semester of 2027 begin?", "RM2027-01", "registration (not orientation or semester start)"),
    rm_q("R02", "When is orientation for new conventional students in the first semester of 2027?", "RM2027-02", "conventional students, main calendar",
         forbidden=["5/01/2027 (Education block release orientation) given as the conventional orientation"]),
    rm_q("R03", "When does the first semester of 2027 start?", "RM2027-03", "commencement of semester (not registration)"),
    rm_q("R04", "When is the first semester break in 2027?", "RM2027-05", "first semester"),
    rm_q("R05", "When are the first semester examinations in 2027?", "RM2027-07", "main academic calendar identified",
         tags=["exam_equivalence", "crowding"],
         equivalents={"RM2027-17": "Faculty of Education Block Release, First Semester, Examinations, same dates",
                      "rule": "Full credit: 24/05/2027 - 04/06/2027 attributed to the main academic calendar (RM2027-07), "
                              "or both calendars given and distinguished. Partial credit: correct dates but attributed only "
                              "to the block release calendar, or no calendar identified. Identical dates alone are not proof "
                              "of a fully correct answer."}),
    rm_q("R06", "When does the second semester of 2027 start?", "RM2027-09", "commencement of second semester"),
    rm_q("R07", "When is the second semester break in 2027?", "RM2027-11", "approved date (2027)",
         tags=["approved_correction", "grounding"],
         forbidden=["13/09/2026 given as the start of the break", "any statement that the date is unverified"]),
    rm_q("R08", "When are the second semester examinations in 2027?", "RM2027-13", "main academic calendar identified",
         tags=["approved_correction", "exam_equivalence", "crowding", "flagged_ranking_case"],
         forbidden=["12/11/202 (truncated year)", "any statement that the date is unverified"],
         equivalents={"RM2027-21": "Faculty of Education Block Release, Second Semester, Examinations, same dates",
                      "rule": "Full credit: 01/11/2027 - 12/11/2027 attributed to the main academic calendar (RM2027-13), "
                              "or both calendars given and distinguished. Partial credit: correct dates attributed only to "
                              "the block release calendar, or no calendar identified."}),
    rm_q("R09", "When does face-to-face tuition for the fourth quarter run in 2027?", "RM2027-12", "fourth quarter"),
    rm_q("R10", "When is orientation for Faculty of Education block release students in the first semester?", "RM2027-14",
         "orientation (5/01/2027), not face-to-face tuition", tags=["crowding"],
         forbidden=["the face-to-face tuition period 5/01/2027-8/01/2027 given as the orientation date"]),
    rm_q("R11", "When do Faculty of Education block release students write first semester examinations?", "RM2027-17",
         "Faculty of Education block release identified", tags=["exam_equivalence"],
         equivalents={"RM2027-07": "Main academic calendar, First Semester, Examinations, same dates",
                      "rule": "Full credit: dates attributed to the Faculty of Education block release calendar "
                              "(RM2027-17). Partial credit: correct dates supported only by the main-calendar row without "
                              "saying they apply to block release students."}),
    rm_q("R12", "When is the online learning period for Faculty of Education block release in the second semester?",
         "RM2027-20", "online learning (not the semester break that starts on the same day)",
         forbidden=["13/09/2027 - 17/09/2027 (main calendar semester break) given as the online learning period"]),
    rm_q("R13", "When is orientation for block release students in the second semester of 2027?", "RM2027-18",
         "block release (not the conventional orientation 26/07/2027 - 30/07/2027)"),
]

ADV = "Intake advert content is only in staging 0006 (not published). "
intake_qs = [
    {"id": "I01", "question": "What is the application fee for the January/February 2027 intake?",
     "keys": {
         "staging": key("answer", ["local applicants: US$10 or ZIG equivalent at interbank rate",
                                   "international applicants: US$50", "the application fee is non-refundable"],
                        [ev("intake", "MSU-JF2027-INFO-02", 36, "Application fee is US$10 or ZIG equivalent at interbank rate for local applicants and US$50 for International applicants"),
                         ev("intake", "MSU-JF2027-INFO-02", 36, "NB*APPLICATION FEE IS NON-REFUNDABLE")]),
         "public": key("partial", ["says the amount of the 2027 application fee is not in the available documents"],
                       [ev("yearbook-humanities", 533, 130, "Application fees are non-refundable")],
                       ["any fee amount"], note=ADV + "The yearbook only says application fees are non-refundable; "
                                                    "stating that (with its citation) is acceptable."),
     }},
    {"id": "I02", "question": "Which bank accounts can I use to pay the MSU application fee?",
     "keys": {
         "staging": key("answer", ["ZB BANK ACCOUNT (ZWL) 4575486039200", "Banc ABC (ZWL) 28624025502017",
                                   "Banc ABC (USD) 28624026633189", "CBZ ACCOUNT (ZWL) 01820772520046",
                                   "CBZ (USD) 10720772520202", "Branch Sort Code 107", "Swift Code COBZZWHA",
                                   "original deposit slip must accompany the completed application form"],
                        [ev("intake", "MSU-JF2027-INFO-03", 36, "ZB BANK ACCOUNT (ZWL) 4575486039200, Banc ABC (ZWL) 28624025502017 (USD) 28624026633189"),
                         ev("intake", "MSU-JF2027-INFO-03", 36, "CBZ ACCOUNT (ZWL) 01820772520046, (USD)10720772520202"),
                         ev("intake", "MSU-JF2027-INFO-03", 36, "Completed application form should be accompanied by an original deposit slip of the application fee")],
                        ["a bank or account number not in the advert"],
                        note="Accounts must be reproduced exactly; one wrong digit is a critical unsupported claim."),
         "public": key("not_available", ["says the bank details are not in the available documents"], [],
                       ["any account number, bank name or SWIFT code"], note=ADV + "No yearbook passage contains bank details."),
     }},
    {"id": "I03", "question": "How can I contact MSU admissions about the 2027 intake?",
     "keys": {
         "staging": key("answer", ["phone 054 2260029", "WhatsApp 0716626820", "email admissions@admin.msu.ac.zw"],
                        [ev("intake", "MSU-JF2027-INFO-04", 37, "054 2260029"),
                         ev("intake", "MSU-JF2027-INFO-04", 37, "0716626820"),
                         ev("intake", "MSU-JF2027-INFO-04", 37, "admissions@admin.msu.ac.zw")]),
         "public": key("not_available", ["says the admissions contact details are not in the available documents"], [],
                       ["any phone number or email address"], note=ADV + "No yearbook passage contains these contacts."),
     }},
    {"id": "I04", "question": "How do I apply for the January/February 2027 intake?",
     "keys": {
         "staging": key("answer", ["applicants can apply online, or obtain an application form physically from the Admissions "
                                   "Office at the Gweru, Harare (No. 1 Kwame Nkrumah), Bulawayo Nkulumane Complex, Zvishavane "
                                   "or Kwekwe campuses",
                                   "the website www.msu.ac.zw has more information on the programmes and how to apply",
                                   "at least 5 'O' level passes at grade C or better including English Language, in addition "
                                   "to the specified 'A' level subjects or diplomas"],
                        [ev("intake", "MSU-JF2027-INFO-01", 1, "Applicants can apply online or alternatively an applicant can obtain an application form physically from the Admissions Office at the Gweru, Harare (No. 1 Kwame Nkrumah), Bulawayo Nkulumane Complex, Zvishavane and Kwekwe Campuses"),
                         ev("intake", "MSU-JF2027-INFO-01", 1, "Applicants are advised to visit our website, www.msu.ac.zw for more information on the available programmes and how to apply"),
                         ev("intake", "MSU-JF2027-INFO-01", 1, "Applicants must hold at least 5")],
                        ["a claim that the advert says applications are made 'via the website' (it says the website has information; applicants can apply online)"]),
         "public": key("partial", ["general procedure from the yearbook: applications in hard or soft copy to the Admissions, "
                                   "Registration and Student Statistics Office, or online through the university online "
                                   "admissions platform; closing dates are advertised by the Registrar's Office",
                                   "says intake-specific (January/February 2027) details are not in the available documents"],
                       [ev("yearbook-humanities", 528, 129, "Applications must be submitted either in hard copy or soft copy to Admissions, Registration and Student Statistics Office or online through the university online admissions platform")],
                       ["2027-specific campuses, dates or fees"],
                       note=ADV + "Humanities Yearbook pp. 141-142 describe the POSTGRADUATE application procedure; using "
                                  "them for undergraduate applications without saying so is an attribution error."),
     }},
    {"id": "I05", "question": "When does the Bachelor of Education Honours Degree in Science and Applied Technologies start?",
     "keys": {
         "staging": key("answer", ["February 2027 (stated in the programme row: Gweru Conventional, commences February 2027)"],
                        [ev("intake", "MSU-JF2027-107", 18, "commences February 2027")],
                        ["January 2027 (the Faculty of Education default) given as this programme's start"],
                        note="The programme row overrides the faculty default; this is a grounding trap."),
         "public": key("not_available", ["says the 2027 start date is not in the available documents"], [],
                       ["any start month"], note=ADV),
     }},
    {"id": "I06", "question": "When does the Bachelor of Education Honours in Early Childhood Development and Child Protection start?",
     "keys": {
         "staging": key("answer", ["January 2027, from the Faculty of Education note that all programmes, unless indicated "
                                   "otherwise, commence in January 2027 (the programme row gives no other date)"],
                        [ev("intake", "MSU-JF2027-083", 13, "All programmes, unless indicated otherwise, commence in January 2027",
                            note="Faculty of Education banner, p. 13; the programme row itself is on p. 14"),
                         ev("intake", "MSU-JF2027-083", 14, "Bachelor of Education Honours in Early Childhood Development and Child Protection")],
                        note="Derived from the faculty banner (rule), not stated in the programme row; full credit if the "
                             "answer gives January 2027 and the basis."),
         "public": key("not_available", ["says the 2027 start date is not in the available documents"], [],
                       ["any start month"], note=ADV),
     }},
    {"id": "I07", "question": "When does the Bachelor of Engineering Honours Degree in Electrical and Electronic Engineering (HEEE) (5 years) start, and what is the application deadline?",
     "keys": {
         "staging": key("answer", ["commences in August 2027 (Faculty of Engineering and Geosciences note)",
                                   "applications to be submitted online only",
                                   "deadline for submission of applications is 31 March 2027"],
                        [ev("intake", "MSU-JF2027-126", 20, "All programmes in the Faculty of Engineering and Geosciences commence in August 2027"),
                         ev("intake", "MSU-JF2027-126", 21, "Deadline for submission of applications is 31 March 2027")]),
         "public": key("not_available", ["says the 2027 start date and application deadline are not in the available documents"],
                       [ev("yearbook-sciences-v2", 8321, 636, "Duration of Degree: 5 years")],
                       ["any start date or deadline"],
                       note=ADV + "Mentioning the 5-year duration from the Sciences Yearbook (cited) is acceptable."),
     }},
    {"id": "I08", "question": "How long is the Bachelor of Science in Biomedical Sciences programme?",
     "tags": ["conflicting_or_complementary_evidence", "grounding"],
     "keys": {
         "staging": key("answer", ["the January/February 2027 intake advert does not state the duration",
                                   "the Sciences Yearbook states 3 years (General) and 4 years (Honours)"],
                        [ev("intake", "MSU-JF2027-146", 26, "Bachelor of Science in Biomedical Sciences"),
                         ev("yearbook-sciences-v2", 8754, 726, "Duration: 3 Years (General), 4 Years (Honours)")],
                        ["a duration attributed to the intake advert", "a single unqualified duration"],
                        full_credit="Both facts, each attributed to its own source.",
                        partial_credit="Only one of the two (e.g. the yearbook durations without saying the advert is silent)."),
         "public": key("answer", ["3 years (General) and 4 years (Honours), per the Sciences Yearbook"],
                       [ev("yearbook-sciences-v2", 8754, 726, "Duration: 3 Years (General), 4 Years (Honours)")],
                       ["a duration attributed to the 2027 intake advert"]),
     },
     "related_conflict": "Entry requirements differ between the sources: the advert says 'A' Level Chemistry with an A and "
                         "any two of Mathematics, Physics or Biology; the Sciences Yearbook (p. 726) says passes in 'A' Level "
                         "Chemistry and any other two from Biology, Mathematics, Physics. An answer that mentions entry "
                         "requirements must attribute each version."},
    {"id": "I09", "question": "Where is the Bachelor of Laws (LLB) offered and what are the extra 'O' level requirements?",
     "tags": ["conflicting_evidence"],
     "keys": {
         "staging": key("answer", ["Kwekwe Conventional (2027 advert)", "5 years (2027 advert)",
                                   "'O' level Mathematics and English Language with B or better (Faculty of Law note in the advert)",
                                   "applications to be submitted online only"],
                        [ev("intake", "MSU-JF2027-147", 26, "Kwekwe Conventional"),
                         ev("intake", "MSU-JF2027-147", 26, "Mathematics and English Language with B or better")],
                        ["the yearbook rule presented as the 2027 advert rule (or vice versa) without attribution"],
                        note="If the yearbook passage is also retrieved, the answer must point out that the yearbook requires "
                             "English Language at B or better (no Mathematics B) and attribute each requirement.",
                        full_credit="Advert facts correct and attributed; any yearbook difference pointed out."),
         "public": key("partial", ["from the Humanities Yearbook: English Language at B or better at 'O' level, a pass in "
                                   "'A' level English Literature or History and two further 'A' levels; ten semesters full time",
                                   "says the 2027 campus and intake details are not in the available documents"],
                       [ev("yearbook-humanities", 3577, 619, "must have passed the English Language with at least a B or better at 'O' Level"),
                        ev("yearbook-humanities", 3577, 619, "completed over a period of ten semesters"),
                        ev("yearbook-humanities", 271, 76, "Kwekwe Campus, which is scheduled to host the Faculty of Law")],
                       ["'O' level Mathematics B attributed to the yearbook", "Kwekwe stated as a 2027 fact"],
                       note=ADV + "Mentioning that the yearbook says the Kwekwe Campus is scheduled to host the Faculty of "
                                  "Law is acceptable with that wording and citation."),
     }},
    {"id": "I10", "question": "What are the entry requirements for Mining Engineering?",
     "tags": ["routes_must_not_merge", "conflicting_evidence", "crowding", "flagged_ranking_case"],
     "keys": {
         "staging": key("answer", [
             "ROUTE 1 - 4 years, Zvishavane Conventional (MSU-JF2027-132): passed at least 5 subjects at Ordinary Level "
             "including Mathematics, English and Combined Science or equivalent; 'A' Level passes in Mathematics, Physics and "
             "any other science subject; holders of a recognised National Diploma in the relevant field may be considered "
             "under the ZNQF framework starting in year 2; deadline for applications 31 March 2027",
             "ROUTE 2 - 3 years, Zvishavane Visiting (MSU-JF2027-133): passed at least 5 subjects at Ordinary Level including "
             "Mathematics, English and Combined Science or equivalent; National Diploma in Mining, Geology, Survey or any other "
             "relevant diploma from a recognised institution; currently employed within the mining industry; attach proof of "
             "employment from the Human Resources office"],
             [ev("intake", "MSU-JF2027-132", 23, "Applicants with a recognized National Diploma in the relevant field may be considered using the ZNQF framework starting in year 2"),
              ev("intake", "MSU-JF2027-133", 23, "National Diploma in Mining, Geology, Survey, or any other relevant diploma from a recognized institution"),
              ev("intake", "MSU-JF2027-133", 23, "Should be currently employed within the mining industry")],
             ["any requirement of one route attributed to the other",
              "the employment requirement attached to the 4-year conventional route",
              "the National Diploma route-entry (year 2) attached to the visiting route"],
             note="Merging the two routes is a CRITICAL failure. If the yearbook passage is also retrieved, its different "
                  "Visiting School rule ('A' levels plus employment within the minerals industry) must be attributed to the "
                  "yearbook and the difference pointed out.",
             full_credit="Both routes, kept separate and correctly attributed.",
             partial_credit="One route complete and correct, the other missing (but not merged)."),
         "public": key("answer", [
             "from the Sciences Yearbook (Mining Engineering ENG08, 4 years): Normal Entry - 'A' Level Mathematics, Physics "
             "and any relevant science subject, and passes in 'O' Level Mathematics and English; Special Entry - a National "
             "Diploma in Mining from a recognised institution; Visiting School - 'A' Level Mathematics, Physics and a relevant "
             "science subject, 'O' Level Mathematics and English, plus employment within the minerals industry"],
             [ev("yearbook-sciences-v2", 8597, 692, "Normal Entry: 'A' Level subjects, Mathematics, Physics and any relevant science subject"),
              ev("yearbook-sciences-v2", 8597, 692, "Special Entry: A National Diploma in Mining from a recognized Institution"),
              ev("yearbook-sciences-v2", 8598, 692, "Plus employment within the minerals industry")],
             ["entry routes merged", "the yearbook rules presented as the 2027 advert"],
             note=ADV + "Normal, special and visiting entry must stay distinct."),
     }},
    {"id": "I11", "question": "What are the requirements and duration of the Master of Education in Food Technology & Design?",
     "tags": ["crowding", "complementary_evidence"],
     "keys": {
         "staging": key("answer", ["1 1/2 years (advert)", "BSc Education, Bachelor of Education, or BSc with Post Graduate "
                                   "Diploma in Education, Graduate Diploma in Education or Grad CE (with specialisation in "
                                   "the relevant area), or equivalent from accredited and recognised institutions (advert)"],
                        [ev("intake", "MSU-JF2027-118", 20, "BSc Education, Bachelor of Education, or BSc with Post Graduate Diploma in Education, Graduate Diploma in Education or Grad CE (with specialisation in the relevant area)")],
                        ["requirements of another M.Ed. specialisation presented as different"],
                        note="The requirement text is shared by eight M.Ed. records on p. 20 (MSU-JF2027-118..125); citing a "
                             "sibling record is a citation error even though the requirement text is identical."),
         "public": key("answer", ["1 1/2 years (Humanities Yearbook)", "a BEd degree or approved equivalent in the appropriate "
                                  "subject area, or a degree or Post-Graduate Diploma in Education or approved equivalent "
                                  "(Humanities Yearbook)"],
                       [ev("yearbook-humanities", 3496, 604, "MASTER OF EDUCATION DEGREE IN FOOD TECHNOLOGY AND DESIGN (EDU18)"),
                        ev("yearbook-humanities", 3497, 605, "Duration 11/2Years"),
                        ev("yearbook-humanities", 3498, 605, "Obtained a BED degree or approved equivalent from any recognised university in the appropriate subject area")],
                       ["the advert's list presented as the yearbook's"],
                       note=ADV + "The yearbook prints the duration as '11/2Years' (1 1/2 years)."),
     }},
    {"id": "I12", "question": "What are the entry requirements for the Master of Arts Degree in Museum Studies?",
     "tags": ["crowding"],
     "keys": {
         "staging": key("answer", ["a good first degree in Archaeology, Museum Studies, Art and Design, Anthropology and "
                                   "Records Management"],
                        [ev("intake", "MSU-JF2027-047", 7, "A good first Degree in Archaeology, Museum Studies, Art and Design, Anthropology and Records Management")],
                        ["the requirements of MSU-JF2027-048 (MA Archaeology) cited as this programme's"],
                        note="MSU-JF2027-048 has near-identical text; the citation must be to -047."),
         "public": key("not_available", ["says the specific entry requirements are not in the available documents (the "
                                         "yearbook refers to the general postgraduate regulations)"],
                       [ev("yearbook-humanities", 687, 162, "ENTRY REQUIREMENT Refer to Section 5 of the General Academic Regulations")],
                       ["a list of qualifying degrees"], note=ADV),
     }},
    {"id": "I13", "question": "When does the Bachelor of Science Honours Degree in Psychology start?",
     "tags": ["grounding", "missing_information"],
     "keys": {
         "staging": key("answer", ["the advert does not state a commencement date for this programme (it lists Gweru "
                                   "Conventional, 4 years)"],
                        [ev("intake", "MSU-JF2027-175", 31, "Bachelor of Science Honours Degree in Psychology")],
                        ["any start month", "the Faculty of Education default (January 2027) applied to a Social Sciences programme"]),
         "public": key("not_available", ["says the start date is not in the available documents"], [], ["any start month"], note=ADV),
     }},
    {"id": "I14", "question": "How is the Special Honors Degree in Monitoring and Evaluation offered?",
     "keys": {
         "staging": key("answer", ["Zvishavane Visiting", "Harare Weekend Class", "Bulawayo Weekend School"],
                        [ev("intake", "MSU-JF2027-021", 4, "Zvishavane Visiting"),
                         ev("intake", "MSU-JF2027-021", 4, "Harare Weekend Class")],
                        ["a campus or mode not listed"],
                        note="'Harare Weekend Class' is the advert's wording (not 'Weekend School')."),
         "public": key("not_available", ["says the modes of entry are not in the available documents"], [],
                       ["any campus or mode"], note=ADV + "The yearbook lists the programme (p. 158) but not its 2027 modes."),
     }},
    {"id": "I15", "question": "What are the entry requirements for the Bachelor of Engineering Honours Degree in Electrical and Electronic Engineering (HEEE) (3 years, visiting)?",
     "tags": ["crowding", "routes_must_not_merge"],
     "keys": {
         "staging": key("answer", ["passed at least 5 subjects at Ordinary Level including Mathematics, English and Combined "
                                   "Science or equivalent", "a National Diploma in Electrical Engineering, Electronics "
                                   "Engineering or any other relevant engineering field; may be invited for an interview or "
                                   "entrance examination", "formally employed in the relevant field of expertise",
                                   "attach proof of employment from the Human Resources office"],
                        [ev("intake", "MSU-JF2027-128", 21, "Hold a National Diploma in Electrical Engineering, Electronics Engineering or any other relevant engineering field"),
                         ev("intake", "MSU-JF2027-128", 21, "Be formally employed in the relevant field of expertise")],
                        ["the 4-year block release route's National Certificate requirement (MSU-JF2027-127)",
                         "the 5-year conventional route's 'A' level requirement"],
                        note="MSU-JF2027-127 (4 years, block release) differs only by National Certificate vs Diploma "
                             "(cosine 0.998)."),
         "public": key("not_available", ["says the visiting route is not described in the available documents"],
                       [ev("yearbook-sciences-v2", 8321, 636, "Duration of Degree: 5 years")],
                       ["the yearbook's normal or special entry presented as the visiting-route requirements"],
                       note=ADV + "Describing the yearbook's general (5-year) entry rules is acceptable only if clearly "
                                  "labelled as such."),
     }},
]
for q in intake_qs:
    q["category"] = "intake"
    q["keys"]["baseline"] = q["keys"]["public"]          # same yearbook content (public adds only the road map)
    q.setdefault("tags", [])

DECLINE = key("decline", ["says the MSU documents do not contain this information"], [],
              ["invented facts", "loosely related passages cited as support"])
oos_new = [
    {"id": "X03", "question": "What is the weather forecast for Gweru tomorrow?"},
    {"id": "X04", "question": "What is the application fee at the University of Zimbabwe?",
     "trap": "other institution: the MSU fee (staging) must not be given as the UZ fee"},
    {"id": "X05", "question": "Who won the 2026 Zimbabwe Premier Soccer League?"},
    {"id": "X06", "question": "When does the 2028 first semester start?",
     "trap": "only 2027 dates are available; 2027 dates must not be presented as 2028 dates"},
]
for o in oos_new:
    o.update({"category": "out_of_scope", "keys": {"baseline": DECLINE, "public": DECLINE, "staging": DECLINE}})

overlap = [
    {"id": "O4", "alias": "X01", "question": "How do I apply for a UK student visa?",
     "flag": "staging retrieves MSU-JF2027-INFO-01 (how to apply) in the top 5",
     "rule": "Kept unchanged as frozen regression question O4; counted once in aggregate metrics (as O4). Also run on "
             "staging and reported separately as an overlap case.",
     "keys": {"baseline": DECLINE, "public": DECLINE,
              "staging": {**DECLINE, "forbidden": DECLINE["forbidden"] + ["MSU application steps presented as UK visa advice"]}}},
    {"id": "O5", "alias": "X02", "question": "What time does the campus gym open?",
     "flag": "public and staging retrieve RM2027-02 (orientation week) in the top 5",
     "rule": "Kept unchanged as frozen regression question O5; counted once in aggregate metrics (as O5). Also run on "
             "staging and reported separately as an overlap case.",
     "keys": {"baseline": DECLINE,
              "public": {**DECLINE, "forbidden": DECLINE["forbidden"] + ["the road map cited for gym hours"]},
              "staging": {**DECLINE, "forbidden": DECLINE["forbidden"] + ["the road map cited for gym hours"]}}},
]

cross = [
    {"id": "C01", "category": "cross_document", "question": "Are MSU application fees refundable?",
     "keys": {
         "baseline": key("answer", ["application fees are non-refundable (Humanities Yearbook)"],
                         [ev("yearbook-humanities", 533, 130, "Application fees are non-refundable")]),
         "public": key("answer", ["application fees are non-refundable (Humanities Yearbook)"],
                       [ev("yearbook-humanities", 533, 130, "Application fees are non-refundable")]),
         "staging": key("answer", ["application fees are non-refundable; both the Humanities Yearbook and the 2027 intake "
                                   "advert say so (either citation is correct)"],
                        [ev("yearbook-humanities", 533, 130, "Application fees are non-refundable"),
                         ev("intake", "MSU-JF2027-INFO-02", 36, "NB*APPLICATION FEE IS NON-REFUNDABLE")])}},
    {"id": "C02", "category": "cross_document", "question": "Is there a fee for late applications?",
     "keys": {s: key("answer", ["late applicants may be considered upon payment of the prescribed late application fee; "
                                "the amount is not stated"],
                     [ev("yearbook-humanities", 528, 129, "Late applicants may be considered upon payment of the prescribed late application fee")],
                     ["US$10 or US$50 (the ordinary 2027 application fee) given as the late fee", "an invented amount"])
              for s in ("baseline", "public", "staging")}},
]


# ------------------------------------------------------------------ verification of every evidence quote
def verify(items):
    results, discrepancies = [], []
    for q in items:
        for system, k in q["keys"].items():
            for e in k["evidence"]:
                ref = e["passage_uid"].rsplit("/", 1)[1]
                in_record = norm(e["quote"]) in record_text(e["doc"], int(ref[1:]) if e["doc"].startswith("yearbook") else ref)
                in_pdf = norm(e["quote"]) in pdf_page(e["doc"], e["page"])
                e["verified"] = {"in_registered_record": in_record, "in_source_pdf_page": in_pdf}
                if not e["printed_in_source"]:
                    e["verified"]["approved_correction"] = True
                    if in_pdf:
                        e["verified"]["caution"] = ("page-level match comes from another row with the same text; the "
                                                    "row itself prints the original value")
                    in_pdf = True                              # by design; the printed original is checked separately
                results.append((q["id"], system, e["citation"], in_record, in_pdf))
                if not (in_record and in_pdf):
                    discrepancies.append({"question": q["id"], "system": system, "citation": e["citation"],
                                          "quote": e["quote"], **e["verified"]})
    return results, discrepancies


all_items = roadmap_qs + intake_qs + oos_new + overlap + cross
results, discrepancies = verify(all_items)

frozen_path = ROOT / "eval/stage5_questions.json"
frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
ambiguous = [{"id": "A1", "question": "What is ACC 135?", "ambiguity_note": "ACC135"},
             {"id": "A2", "question": "Tell me about ACC 136.", "ambiguity_note": "ACC136"},
             {"id": "A3", "question": "What is AECS 131 about?", "ambiguity_note": "AECS131"},
             {"id": "A4", "question": "What is covered in HAWS 443?", "ambiguity_note": "HAWS443"},
             {"id": "A5", "question": "What does HAWS 444 cover?", "ambiguity_note": "HAWS444"}]

draft = {
    "status": "DRAFT revision 2 - for project-owner review; NOT frozen; no retrieval or generation has been run",
    "built_from": {"registry_sha256": hashlib.sha256((KB / "registry.json").read_bytes()).hexdigest(),
                   "roadmap_dataset_sha256": docs["roadmap-2027"]["dataset"]["sha256"],
                   "intake_dataset_sha256": docs["intake-2027-jan-feb"]["dataset"]["sha256"],
                   "frozen_regression_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
                   "public_version": "0005", "staging_version": "0006", "baseline_index": "faiss_store_v2"},
    "systems": {"baseline": "faiss_store_v2 via Stage6Retriever('main') - yearbooks only",
                "public": "knowledge-base CURRENT 0005 via PublicRetriever - yearbooks + 2027 road map",
                "staging": "knowledge-base STAGING 0006 via StagingRetriever - yearbooks + road map + staged intake"},
    "key_fields": {"behaviour": "answer | partial | not_available | decline",
                   "required": "elements a sufficient answer must contain",
                   "evidence": "verified quotes (record + source PDF page) that support the required elements",
                   "acceptable_citations": "citations that count as correct source attribution",
                   "forbidden": "claims that make the answer an unsupported-claim failure"},
    "regression": {"file": "eval/stage5_questions.json (frozen, unchanged; readable copy in regression_review_copy.md)",
                   "questions": len(frozen["questions"]), "ambiguous_code_queries": ambiguous,
                   "keys": "baseline and public: the frozen 'sufficient' text and pages of each question; staging: same "
                           "(only O4/O5 are run on staging - see overlap_cases)",
                   "ambiguity_rule": "A1-A5: the answer must mention every meaning listed in the ambiguity note or ask "
                                     "which programme applies (Stage 6/7 rule)"},
    "roadmap": roadmap_qs, "intake": intake_qs, "out_of_scope": oos_new, "overlap_cases": overlap,
    "cross_document": cross,
    "evidence_verification": {"quotes_checked": len(results),
                              "verified_in_record_and_pdf": sum(1 for r in results if r[3] and r[4]),
                              "discrepancies": discrepancies},
}
(HERE / "stage4_questions_draft.json").write_text(json.dumps(draft, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

# Readable evidence table
lines = ["# Stage 4 draft (revision 2): answer-key evidence", "",
         "DRAFT, not frozen. Each quote was checked in the registered record (dataset or frozen yearbook chunk) and on "
         "the original source PDF page (normalised text). Generated by `build_stage4_questions.py`.", "",
         f"Quotes checked: {len(results)}. Verified in both: {sum(1 for r in results if r[3] and r[4])}. "
         f"Discrepancies: {len(discrepancies)}.", "",
         "| Question | System(s) | Citation | Quote | Record | PDF page |", "|---|---|---|---|---|---|"]
seen = {}
for q in all_items:
    for system, k in q["keys"].items():
        for e in k["evidence"]:
            key_ = (q["id"], e["citation"], e["quote"])
            seen.setdefault(key_, {"systems": [], "v": e["verified"]})["systems"].append(system)
for (qid, cit, quote), v in seen.items():
    lines.append(f"| {qid} | {', '.join(v['systems'])} | {cit} | {quote.replace('|', '/')} | "
                 f"{'yes' if v['v']['in_registered_record'] else 'NO'} | {'yes' if v['v']['in_source_pdf_page'] else 'NO'} |")
(HERE / "stage4_answer_evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

# Readable copy of the frozen regression questions (the frozen file itself is not modified)
rl = ["# Frozen regression questions: readable review copy", "",
      f"Source: `eval/stage5_questions.json` (frozen; SHA-256 `{draft['built_from']['frozen_regression_sha256']}`). "
      "This copy is for review only; the frozen file is unchanged.", "",
      "| ID | Category | Question | Sufficient answer (frozen key) | Pages |", "|---|---|---|---|---|"]
for q in frozen["questions"]:
    rl.append(f"| {q['id']} | {q['category']} | {q['question']} | {q.get('sufficient', '').replace('|', '/')} | "
              f"{', '.join(q.get('pages') or [])} |")
rl += ["", "## Ambiguous-code queries (Stage 3.2/3.4 comparisons)", "",
       "| ID | Question | Ambiguity note expected |", "|---|---|---|"]
rl += [f"| {a['id']} | {a['question']} | {a['ambiguity_note']} |" for a in ambiguous]
rl += ["", "Overlap: O4 = X01 (UK student visa) and O5 = X02 (campus gym) are counted once, as O4/O5."]
(HERE / "regression_review_copy.md").write_text("\n".join(rl) + "\n", encoding="utf-8")
print(f"{len(roadmap_qs)} road map, {len(intake_qs)} intake, {len(oos_new)} new out-of-scope, {len(overlap)} overlap, "
      f"{len(cross)} cross-document; evidence quotes {len(results)}, discrepancies {len(discrepancies)}")
for d in discrepancies:
    print("DISCREPANCY:", d)
