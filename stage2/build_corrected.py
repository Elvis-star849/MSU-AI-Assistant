"""Stage 2 corrections: build corrected copies of the two user-supplied JSON files.

Reads the originals in msu docs/2027/originals (never writes to them) and the source
PDFs in data/source_pdfs, applies the fixes approved on 2026-10-13 (see
audit/stage2_json_review.md), and writes *_v2.json to msu docs/2027.

Usage (PDF paths optional):
    python stage2/build_corrected.py [<intake_pdf> <roadmap_pdf>]
"""
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent          # MSU-AI-Assistant/stage2
RAG = HERE.parent.parent                        # RAG/
DOCS_2027 = RAG / "msu docs" / "2027"
SOURCE_PDFS = HERE.parent / "data" / "source_pdfs"
DEFAULT_INTAKE_PDF = SOURCE_PDFS / "MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf"
DEFAULT_ROADMAP_PDF = SOURCE_PDFS / "2027 DRAFT ROADMAP fin (1).pdf"
SRC_INTAKE_JSON = DOCS_2027 / "originals" / "MSU_2027_Intake_Corrected.json"
SRC_ROADMAP_JSON = DOCS_2027 / "originals" / "2027_ROADMAP_RAG_Ready.json"
OUT_INTAKE_JSON = DOCS_2027 / "MSU_2027_Intake_Corrected_v2.json"
OUT_ROADMAP_JSON = DOCS_2027 / "2027_ROADMAP_RAG_Ready_v2.json"

EDITION_DATE = "2026-10-13"
AUDIT_REPORT = "MSU-AI-Assistant/audit/stage2_json_review.md"
VALIDATION_REPORT = "MSU-AI-Assistant/stage2/validation_report.md"
# Pages rendered and inspected by eye during the Stage 2 review.
VISUALLY_CHECKED_PAGES = {17, 18, 20, 21, 22, 23, 26, 27, 29, 34, 35}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def page_text(doc, page_no):
    """Whitespace-normalised text of a 1-based page, with line-break hyphens rejoined."""
    t = doc[page_no - 1].get_text()
    t = re.sub(r"-\s*\n\s*", "-", t)
    return re.sub(r"\s+", " ", t).strip()


def excerpt(text, start, end):
    """Verbatim excerpt from `start` up to and including `end`; fails loudly if absent."""
    i = text.find(start)
    j = text.find(end, i)
    if i < 0 or j < 0:
        raise ValueError(f"source text not found: {start!r} .. {end!r}")
    return text[i:j + len(end)]


# --------------------------------------------------------------------------- intake

PROGRAMME_OPTIONAL_KEYS = ("commencement", "commencement_basis", "application_channel",
                           "faculty_conditions_inherited", "duration_by_mode")
# Joins non-contiguous verbatim excerpts inside one source_text.
EXCERPT_SEP = " [...] "


def fix_intake(src, pdf_path):
    d = copy.deepcopy(src)
    pdf_sha = sha256(pdf_path)
    doc = pymupdf.open(pdf_path)
    source = {
        "filename": Path(pdf_path).name,
        "sha256": pdf_sha,
        "page_count": doc.page_count,
        "previously_recorded_filename": "MSU JANUARY FEBRUARY 2027 INTAKE ADVERT(1).pdf",
    }
    changes = []
    P = {p["id"]: p for p in d["programmes"]}

    # Fix 1: -107 and -108 explicitly say "(commences February 2027)" on p.18.
    for pid in ("MSU-JF2027-107", "MSU-JF2027-108", "MSU-JF2027-099", "MSU-JF2027-100"):
        p = P[pid]
        assert any("commences February 2027" in m.get("note", "") for m in p["modes_of_entry"]), pid
        before = p.get("commencement")
        p["commencement"] = "February 2027"
        p["commencement_basis"] = ("Stated in the programme row: 'Gweru Conventional "
                                   "(commences February 2027)'; overrides the faculty default "
                                   "of January 2027.")
        p["rag_text"] = p["rag_text"].replace("COMMENCEMENT: January 2027",
                                              "COMMENCEMENT: February 2027")
        if before != "February 2027":
            changes.append(f"{pid}: commencement {before} -> February 2027 (structured field, "
                           "commencement_basis and rag_text)")

    # Fix 2: misplaced list marker in -133.
    p = P["MSU-JF2027-133"]
    old_req = list(p["entry_requirements"])
    assert old_req[0].endswith("including i."), old_req[0]
    p["entry_requirements"] = [
        "i. Passed at least 5 subjects at Ordinary Level including Mathematics, English and "
        "Combined Science or equivalent. National Diploma in Mining, Geology, Survey, or any "
        "other relevant diploma from a recognized institution.",
        old_req[2],
        old_req[3],
    ]
    p["rag_text"] = p["rag_text"].replace("ENTRY REQUIREMENTS: " + " ".join(old_req),
                                          "ENTRY REQUIREMENTS: " + " ".join(p["entry_requirements"]))
    assert "including i." not in p["rag_text"]
    changes.append("MSU-JF2027-133: moved list marker 'i.' to the start of the first entry "
                   "requirement (structured field and rag_text)")

    # Fix 3: source traceability and uniform schema on every programme record.
    for p in d["programmes"]:
        p["source_document"] = source["filename"]
        p["source_sha256"] = pdf_sha
        for k in PROGRAMME_OPTIONAL_KEYS:
            p.setdefault(k, None)
        if "duration_normalized" in p:
            assert p.pop("duration_normalized") is None, p["id"]
        # Fix 5: verification metadata (automated vs human kept separate).
        prior = {"status": p.pop("verification_status"), "note": p.pop("verification_note")}
        p["verification"] = {
            "automated": {
                "status": "passed",
                "date": EDITION_DATE,
                "checks": ["word_coverage_vs_source_page", "row_attribution_vs_source_row"],
                "report": AUDIT_REPORT,
            },
            "visual_page_check": p["source_page"] in VISUALLY_CHECKED_PAGES,
            "prior_check": prior,
            "human_approval": {"status": "pending", "approved_by": None, "date": None},
        }
    changes.append("All 222 programme records: source_document corrected to the real filename, "
                   "source_sha256 added")
    changes.append("All 222 programme records: missing optional keys "
                   f"{', '.join(PROGRAMME_OPTIONAL_KEYS)} added as null, so every record has "
                   "the same keys")
    changes.append("MSU-JF2027-037, MSU-JF2027-146: removed redundant 'duration_normalized: "
                   "null' (duration_as_advertised already says 'Not stated in the advert')")
    changes.append("All 222 programme records: verification_status/verification_note replaced "
                   "by a 'verification' object (automated / visual / prior / human_approval)")

    # Fix 4: separate searchable records for application procedure, fees, banking, enquiries.
    p1, p36, p37 = page_text(doc, 1), page_text(doc, 36), page_text(doc, 37)
    common = {"source_document": source["filename"], "source_sha256": pdf_sha,
              "intake": d["intake"]}
    proc = excerpt(p1, "MIDLANDS STATE UNIVERSITY", "or diplomas.")
    fees = (excerpt(p36, "Application fee is US$10", "International applicants.") + EXCERPT_SEP
            + excerpt(p36, "NB*APPLICATION FEE", "REFUNDABLE."))
    bank = excerpt(p36, "Completed application form", "COBZZWHA.")
    enq = excerpt(p37, "FOR ENQUIRIES CONTACT:", "admissions@admin.msu.ac.zw")
    footer = "SOURCE: Original MSU January/February 2027 intake advert, page {}"
    info = [
        {"id": "MSU-JF2027-INFO-01", "topic": "application_procedure", "source_page": 1,
         "source_text": proc,
         "facts": {"website": "www.msu.ac.zw",
                   "apply_online": True,
                   "paper_forms_from_admissions_offices": [
                       "Gweru", "Harare (No. 1 Kwame Nkrumah)", "Bulawayo Nkulumane Complex",
                       "Zvishavane", "Kwekwe"],
                   "general_requirement": d["general_requirement"]},
         "rag_text": "\n".join([
             "TOPIC: How to apply - MSU January/February 2027 intake",
             "APPLICATION PROCEDURE: " + proc,
             "INTAKE ADVERT: January/February 2027",
             footer.format(1)])},
        {"id": "MSU-JF2027-INFO-02", "topic": "application_fee", "source_page": 36,
         "source_text": fees,
         "facts": {"local_applicants": "US$10 or ZIG equivalent at interbank rate",
                   "international_applicants": "US$50",
                   "refundable": False},
         "rag_text": "\n".join([
             "TOPIC: Application fee - MSU January/February 2027 intake",
             "APPLICATION FEE: " + fees.replace(EXCERPT_SEP, " "),
             "INTAKE ADVERT: January/February 2027",
             footer.format(36)])},
        {"id": "MSU-JF2027-INFO-03", "topic": "fee_payment_banking_details", "source_page": 36,
         "source_text": bank,
         "facts": {"deposit_slip_required": "original deposit slip must accompany the "
                                            "completed application form",
                   "accounts_as_written": [
                       "ZB BANK ACCOUNT (ZWL) 4575486039200",
                       "Banc ABC (ZWL) 28624025502017",
                       "Banc ABC (USD) 28624026633189",
                       "CBZ ACCOUNT (ZWL) 01820772520046",
                       "CBZ ACCOUNT (USD) 10720772520202"],
                   "branch_sort_code": "107",
                   "swift_code": "COBZZWHA"},
         "rag_text": "\n".join([
             "TOPIC: Paying the application fee - bank accounts - MSU January/February 2027 intake",
             "BANKING DETAILS: " + bank,
             "INTAKE ADVERT: January/February 2027",
             footer.format(36)])},
        {"id": "MSU-JF2027-INFO-04", "topic": "enquiries_contacts", "source_page": 37,
         "source_text": enq,
         "facts": dict(d["enquiries"]),
         "rag_text": "\n".join([
             "TOPIC: Admissions enquiries contacts - MSU January/February 2027 intake",
             "CONTACTS: " + enq,
             "INTAKE ADVERT: January/February 2027",
             footer.format(37)])},
    ]
    for r in info:
        r.update(common)
        r["verification"] = {
            "automated": {"status": "passed", "date": EDITION_DATE,
                          "checks": ["source_text_is_verbatim_excerpt_of_source_page"],
                          "report": VALIDATION_REPORT},
            "human_approval": {"status": "pending", "approved_by": None, "date": None},
        }
    d["information_records"] = info
    changes.append("Added 4 information_records (INFO-01 procedure p.1, INFO-02 fee p.36, "
                   "INFO-03 banking p.36, INFO-04 enquiries p.37) with verbatim source_text, "
                   "source_page and rag_text")

    d["source"] = source
    d["previous_verification_scope"] = d.pop("verification_scope")
    d["verification"] = {
        "automated": {
            "status": "passed",
            "date": EDITION_DATE,
            "scope": "All 222 programme records and 4 information records",
            "summary": "No JSON words absent from the PDF; no PDF table words missing; every "
                       "record matched to its own PDF row; known defects corrected in this "
                       "edition.",
            "reports": [AUDIT_REPORT, VALIDATION_REPORT],
        },
        "human_review": {
            "audit_report_accepted_by_project_owner": EDITION_DATE,
            "record_level_approval": "pending",
        },
    }
    d["correction_edition"] = f"{EDITION_DATE} stage-2 corrected edition (v2)"
    d["derived_from"] = {"file": SRC_INTAKE_JSON.name, "sha256": sha256(SRC_INTAKE_JSON)}
    d["changelog"] = changes
    return d, changes


# --------------------------------------------------------------------------- roadmap

ROADMAP_CORRECTIONS = {
    "RM2027-11": ("13/09/2026 - 17/09/2027", "13/09/2027 - 17/09/2027"),
    "RM2027-13": ("01/11/2027 - 12/11/202", "01/11/2027 - 12/11/2027"),
}
STATUS_BASIS = ("Confirmed by the project owner on 2026-10-13 as the approved 2027 road map for "
                "this project. Not independently verified with the Registry.")


def fix_roadmap(src, pdf_path):
    d = copy.deepcopy(src)
    pdf_sha = sha256(pdf_path)
    doc = pymupdf.open(pdf_path)
    text = page_text(doc, 1)
    changes = []

    d["source"] = {"filename": Path(pdf_path).name, "sha256": pdf_sha,
                   "page_count": doc.page_count,
                   "filename_note": "The source filename contains 'DRAFT'; the content is "
                                    "recorded as approved per the project owner's confirmation."}
    d["status"] = "approved"
    d["status_basis"] = STATUS_BASIS
    changes.append("Added top-level source (filename incl. DRAFT, sha256), status 'approved' and "
                   "status_basis")

    for c in d["corrections_applied"]:
        rid = "RM2027-11" if "Break" in c["item"] else "RM2027-13"
        raw, fixed = ROADMAP_CORRECTIONS[rid]
        assert c["corrected_to"] == fixed, c
        c["event_id"] = rid
        c["dates_in_source"] = raw
        c["basis"] = STATUS_BASIS
    changes.append("corrections_applied: added event_id, dates_in_source (original PDF text) and "
                   "basis")

    status_line = "STATUS: Approved 2027 road map for this project."
    for e in d["events"]:
        written = e.pop("dates_as_written")
        raw, fixed = ROADMAP_CORRECTIONS.get(e["id"], (written, written))
        assert written == fixed, e["id"]
        assert re.sub(r"\s+", "", raw) in re.sub(r"\s+", "", text), (e["id"], raw)
        e["dates"] = fixed
        e["dates_in_source"] = raw
        e["date_corrected"] = raw != fixed
        e["source_document"] = d["source"]["filename"]
        e["source_sha256"] = pdf_sha
        e["source_page"] = 1
        e["status"] = "approved"
        lines = e["rag_text"].split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("DATES: "))
        extra = [status_line]
        if e["date_corrected"]:
            extra.insert(0, f"DATE CORRECTION: The source PDF prints {raw}; the approved "
                            f"date is {fixed}.")
        e["rag_text"] = "\n".join(lines[:k + 1] + extra + lines[k + 1:])
    changes.append("All 21 events: dates_as_written replaced by 'dates' (approved) plus "
                   "'dates_in_source' (verbatim PDF) and 'date_corrected'; added source_document, "
                   "source_sha256, source_page, status; STATUS line added to rag_text")
    changes.append("RM2027-11, RM2027-13: DATE CORRECTION line added to rag_text")

    for s in d["semester_summaries"]:
        for a in s["activities"]:
            a["dates_in_source"] = a["dates"]
            for rid, (raw, fixed) in ROADMAP_CORRECTIONS.items():
                ev = next(e for e in d["events"] if e["id"] == rid)
                if (s["calendar_group"], s["semester"], a["activity"], a["dates"]) == \
                        (ev["calendar_group"], ev["semester"], ev["activity"], fixed):
                    a["dates_in_source"] = raw
            a["date_corrected"] = a["dates_in_source"] != a["dates"]
        s["source_document"] = d["source"]["filename"]
        s["source_sha256"] = pdf_sha
        s["source_page"] = 1
        s["status"] = "approved"
        notes = [f"DATE CORRECTION: {a['activity']} - the source PDF prints "
                 f"{a['dates_in_source']}; the approved date is {a['dates']}."
                 for a in s["activities"] if a["date_corrected"]]
        lines = s["text"].split("\n")
        k = next(i for i, l in enumerate(lines) if l.startswith("SEMESTER: "))
        s["text"] = "\n".join(lines[:k + 1] + [status_line] + notes + lines[k + 1:])
    changes.append("All 4 semester summaries: dates_in_source/date_corrected per activity, source "
                   "fields, status; STATUS and DATE CORRECTION lines added to text")

    d["verification"] = {
        "automated": {"status": "passed", "date": EDITION_DATE,
                      "checks": ["21_events_vs_source_text", "dates_in_source_verbatim",
                                 "iso_dates_match_approved_dates"],
                      "reports": [AUDIT_REPORT, VALIDATION_REPORT]},
        "human_review": {"content_status_confirmed_by_project_owner": EDITION_DATE,
                         "registry_verification": "not performed"},
    }
    d["correction_edition"] = f"{EDITION_DATE} stage-2 corrected edition (v2)"
    d["derived_from"] = {"file": SRC_ROADMAP_JSON.name, "sha256": sha256(SRC_ROADMAP_JSON)}
    d["changelog"] = changes
    return d, changes


def main(intake_pdf, roadmap_pdf):
    for out, src, pdf, fn in ((OUT_INTAKE_JSON, SRC_INTAKE_JSON, intake_pdf, fix_intake),
                              (OUT_ROADMAP_JSON, SRC_ROADMAP_JSON, roadmap_pdf, fix_roadmap)):
        data, changes = fn(json.loads(src.read_text(encoding="utf-8")), pdf)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out.name}: {len(changes)} change groups")


if __name__ == "__main__":
    main(*(sys.argv[1:3] or (DEFAULT_INTAKE_PDF, DEFAULT_ROADMAP_PDF)))
