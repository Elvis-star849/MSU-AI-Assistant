"""Validate the Stage 2 corrected JSON files against the source PDFs and the originals.

Usage (PDF paths optional; default data/source_pdfs):
    python stage2/validate_corrected.py [<intake_pdf> <roadmap_pdf>]

Writes validation_report.json and validation_report.md next to this script and exits
non-zero if any check fails.
"""
import collections
import datetime as dt
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
ORIG_INTAKE = DOCS_2027 / "originals" / "MSU_2027_Intake_Corrected.json"
ORIG_ROADMAP = DOCS_2027 / "originals" / "2027_ROADMAP_RAG_Ready.json"
NEW_INTAKE = DOCS_2027 / "MSU_2027_Intake_Corrected_v2.json"
NEW_ROADMAP = DOCS_2027 / "2027_ROADMAP_RAG_Ready_v2.json"

# Column boundaries of the intake table (from the clustered vertical rules, Step 2).
COLS = [60, 256.5, 561, 715]
EXPECTED_CONTENT_CHANGES = {"MSU-JF2027-099", "MSU-JF2027-100", "MSU-JF2027-107",
                            "MSU-JF2027-108", "MSU-JF2027-133"}
METADATA_KEYS = {"duration_by_mode", "duration_normalized", "source_document", "source_sha256", "verification", "verification_status",
                 "verification_note", "commencement", "commencement_basis",
                 "application_channel", "faculty_conditions_inherited"}

results = []


def check(group, name, ok, detail=""):
    results.append({"group": group, "check": name, "ok": bool(ok), "detail": str(detail)[:600]})


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"-\s*\n\s*", "-", s)).strip()


def squash(s):
    return re.sub(r"\s+", "", s)


def tok(s):
    return re.findall(r"[a-z0-9]+", s.lower().replace("’", "'"))


def rag_field(rag, label):
    for line in rag.split("\n"):
        if line.startswith(label + ": "):
            return line[len(label) + 2:]
    return None


# --------------------------------------------------------------------------- intake

def hrules(page):
    ys = []
    for dr in page.get_drawings():
        for it in dr["items"]:
            if it[0] == "re" and it[1].height < 3 and it[1].width > 5:
                ys.append((it[1].y0, it[1].x0, it[1].x1))
            elif it[0] == "l" and abs(it[1].y - it[2].y) < 1 and abs(it[1].x - it[2].x) > 5:
                ys.append((it[1].y, min(it[1].x, it[2].x), max(it[1].x, it[2].x)))
    return sorted({round(y, 1) for y, x0, x1 in ys if x0 <= COLS[0] + 15 and x1 >= COLS[1] - 15})


def validate_intake(pdf_path):
    G = "intake"
    new = json.loads(NEW_INTAKE.read_text(encoding="utf-8"))
    orig = json.loads(ORIG_INTAKE.read_text(encoding="utf-8"))
    doc = pymupdf.open(pdf_path)
    pdf_sha = sha256(pdf_path)
    P, I = new["programmes"], new["information_records"]

    # Schema
    keysets = collections.Counter(tuple(sorted(p)) for p in P)
    check(G, "every programme record has the same keys", len(keysets) == 1, keysets.most_common())
    check(G, "every information record has the same keys",
          len({tuple(sorted(r)) for r in I}) == 1)
    ids = [p["id"] for p in P] + [r["id"] for r in I]
    check(G, "record ids unique", len(ids) == len(set(ids)))
    check(G, "222 programme records (same as original)", len(P) == len(orig["programmes"]) == 222)
    check(G, "4 information records", len(I) == 4, [r["topic"] for r in I])
    check(G, "programme_count per faculty matches records",
          all(f["programme_count"] == sum(p["faculty"] == f["name"] for p in P)
              for f in new["faculties"]))

    # Traceability
    check(G, "source PDF sha256 matches recorded hash", new["source"]["sha256"] == pdf_sha, pdf_sha)
    check(G, "source filename matches the real file",
          new["source"]["filename"] == Path(pdf_path).name, new["source"]["filename"])
    allrec = P + I
    check(G, "every record carries the PDF filename and sha256",
          all(r["source_document"] == Path(pdf_path).name and r["source_sha256"] == pdf_sha
              for r in allrec))
    check(G, "derived_from hash matches the untouched original JSON",
          new["derived_from"]["sha256"] == sha256(ORIG_INTAKE))
    check(G, "every source_page within 1..37",
          all(1 <= r["source_page"] <= doc.page_count for r in allrec))

    # Word coverage (programme content vs PDF pages)
    pdfw = collections.defaultdict(collections.Counter)
    for i in range(doc.page_count):
        pdfw[i + 1] = collections.Counter(tok(" ".join(w[4] for w in doc[i].get_text("words"))))
    jw = collections.defaultdict(collections.Counter)
    for p in P:
        jw[p["source_page"]] += collections.Counter(tok(" ".join(
            [p["programme_title_as_advertised"], p["programme_note"]] + p["entry_requirements"]
            + [m["as_written"] + " " + m.get("note", "") * m.get("note", "").startswith("(")
               for m in p["modes_of_entry"]])))  # bracketed notes are advert text; others are editorial
    for r in I:  # information records cover the advert's intro and fee/contact text
        jw[r["source_page"]] += collections.Counter(tok(r["source_text"]))
    allpdf = sum(pdfw.values(), collections.Counter())
    invented = {w: c for w, c in sum(jw.values(), collections.Counter()).items() if w not in allpdf}
    check(G, "no programme word absent from the PDF", not invented, invented)
    skip = set(tok(" ".join(f["name"] + " " + f["note"] for f in new["faculties"])))
    skip |= set(tok("Programme Duration Entry Requirements Mode of Entry Programmes Faculty "
                    "Undergraduate Postgraduate"))
    missing = {}
    for pg in range(1, 37):
        win = jw[pg - 1] + jw[pg] + jw[pg + 1]
        m = {w: c - win[w] for w, c in pdfw[pg].items()
             if c > win[w] and w not in skip and w != str(pg)}
        if m:
            missing[pg] = m
    check(G, "no PDF table word missing from programme records (pp.1-36)", not missing, missing)

    # Content consistency per programme
    bad = []
    for p in P:
        r = p["rag_text"]
        exp = {
            "PROGRAMME": p["programme"],
            "DURATION AS ADVERTISED": p["duration_as_advertised"],
            "ENTRY REQUIREMENTS": " ".join(p["entry_requirements"]),
            "FACULTY": p["faculty"],
        }
        for label, val in exp.items():
            if rag_field(r, label) != val:
                bad.append((p["id"], label))
        comm = rag_field(r, "COMMENCEMENT")
        if comm != p["commencement"]:
            bad.append((p["id"], "COMMENCEMENT", comm, p["commencement"]))
        modes = rag_field(r, "MODES OF ENTRY") or ""
        if any(m["as_written"] not in modes for m in p["modes_of_entry"]):
            bad.append((p["id"], "MODES"))
        if not r.rstrip().endswith(f"page {p['source_page']}"):
            bad.append((p["id"], "SOURCE page"))
    check(G, "rag_text agrees with structured fields (programme, duration, requirements, "
             "faculty, commencement, modes, page)", not bad, bad[:20])

    # Commencement rules
    wrong = []
    for p in P:
        notes = " ".join(m.get("note", "") for m in p["modes_of_entry"])
        m = re.search(r"commences (\w+ 2027)", notes)
        if m and p["commencement"] != m.group(1):
            wrong.append((p["id"], p["commencement"], m.group(1)))
        elif not m and p["faculty"] == "Faculty of Education" and p["commencement"] != "January 2027":
            wrong.append((p["id"], p["commencement"], "January 2027 (faculty default)"))
        elif p["faculty"] in ("Faculty of Engineering and Geosciences",
                              "Faculty of Medicine and Health Sciences") \
                and p["commencement"] != "August 2027":
            wrong.append((p["id"], p["commencement"], "August 2027"))
    check(G, "commencement follows explicit row notes, then faculty banners", not wrong, wrong)
    feb = sorted(p["id"] for p in P if p["commencement"] == "February 2027")
    check(G, "exactly the 4 'commences February 2027' programmes are February",
          feb == ["MSU-JF2027-099", "MSU-JF2027-100", "MSU-JF2027-107", "MSU-JF2027-108"], feb)
    pdf_feb = sum(len(re.findall(r"commences\s+February", doc[i].get_text()))
                  for i in range(doc.page_count))
    check(G, "PDF contains exactly 4 'commences February' notes", pdf_feb == 4, pdf_feb)

    # List markers
    stray = [(p["id"], q) for p in P for q in p["entry_requirements"]
             if re.search(r"\s(i|ii|iii|iv|v)\.$", q)]
    check(G, "no entry requirement ends with a dangling list marker", not stray, stray)

    # Information records
    pages = {n: norm(doc[n - 1].get_text()) for n in (1, 36, 37)}
    for r in I:
        pg = pages[r["source_page"]]
        parts = r["source_text"].split(" [...] ")
        check(G, f"{r['id']} source_text is verbatim from p.{r['source_page']} "
                 f"({len(parts)} excerpt{'s' if len(parts) > 1 else ''})",
              all(part in pg for part in parts), [x[:60] for x in parts if x not in pg])
        check(G, f"{r['id']} rag_text contains the full source_text",
              all(part in r["rag_text"] for part in parts))
        tokens = re.findall(r"[\w.@$]*\d[\w.@$]*|[\w.]+@[\w.]+|COBZZWHA",
                            r["rag_text"] + json.dumps(r["facts"], ensure_ascii=False))
        absent = sorted({t.rstrip(".") for t in tokens if t.rstrip(".") not in pg
                         and t.rstrip(".") not in ("2027",)})
        check(G, f"{r['id']} every number/code/email in rag_text and facts exists on the page",
              not absent, absent)
        check(G, f"{r['id']} rag_text cites page {r['source_page']}",
              r["rag_text"].rstrip().endswith(f"page {r['source_page']}"))

    # Verification metadata
    check(G, "automated verification recorded on every record",
          all(r["verification"]["automated"]["status"] == "passed" for r in allrec))
    check(G, "human approval kept separate and pending on every record",
          all(r["verification"]["human_approval"]["status"] == "pending" for r in allrec))
    check(G, "old verification_status/verification_note fields removed (history kept only "
             "under verification.prior_check)",
          all("verification_status" not in p and "verification_note" not in p for p in P)
          and "not_individually_verified" not in json.dumps(
              [{k: v for k, v in p.items() if k != "verification"} for p in P]))

    # Diff vs original: only expected changes
    O = {p["id"]: p for p in orig["programmes"]}
    unexpected = []
    for p in P:
        o = O[p["id"]]
        for k in set(o) | set(p):
            if k in METADATA_KEYS:
                continue
            if o.get(k) != p.get(k) and p["id"] not in EXPECTED_CONTENT_CHANGES:
                unexpected.append((p["id"], k))
        if p["id"] not in EXPECTED_CONTENT_CHANGES:
            for k in ("commencement", "application_channel", "faculty_conditions_inherited"):
                if o.get(k) != p.get(k):
                    unexpected.append((p["id"], k))
    check(G, "content changed only in -099, -100, -107, -108, -133", not unexpected, unexpected)
    check(G, "top-level text fields unchanged",
          all(orig[k] == new[k] for k in ("how_to_apply", "general_requirement",
                                          "application_fee_and_payment", "enquiries",
                                          "faculties", "title", "intake")))
    return new


# --------------------------------------------------------------------------- roadmap

DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")


def parse_range(s):
    ds = [dt.date(int(y), int(m), int(d)) for d, m, y in DATE.findall(s)]
    return ds[0], ds[-1]


def validate_roadmap(pdf_path):
    G = "roadmap"
    new = json.loads(NEW_ROADMAP.read_text(encoding="utf-8"))
    orig = json.loads(ORIG_ROADMAP.read_text(encoding="utf-8"))
    doc = pymupdf.open(pdf_path)
    text = doc[0].get_text()
    pdf_sha = sha256(pdf_path)
    E = new["events"]

    check(G, "21 events", len(E) == 21)
    check(G, "every event has the same keys", len({tuple(sorted(e)) for e in E}) == 1)
    check(G, "event ids unique and sequential",
          [e["id"] for e in E] == [f"RM2027-{i:02d}" for i in range(1, 22)])
    check(G, "source PDF sha256 matches", new["source"]["sha256"] == pdf_sha, pdf_sha)
    check(G, "source filename preserved (contains DRAFT)",
          new["source"]["filename"] == Path(pdf_path).name and "DRAFT" in new["source"]["filename"],
          new["source"]["filename"])
    check(G, "every event and summary carries filename, sha256 and page 1",
          all(x["source_sha256"] == pdf_sha and x["source_document"] == Path(pdf_path).name
              and x["source_page"] == 1 for x in E + new["semester_summaries"]))
    check(G, "derived_from hash matches the untouched original JSON",
          new["derived_from"]["sha256"] == sha256(ORIG_ROADMAP))

    # Status wording
    check(G, "status is 'approved' at top level and on every event/summary",
          new["status"] == "approved"
          and all(x["status"] == "approved" for x in E + new["semester_summaries"]))
    basis = new["status_basis"]
    check(G, "status basis cites the project owner's confirmation",
          "project owner" in basis, basis)
    check(G, "status basis disclaims independent Registry verification",
          "Not independently verified with the Registry" in basis, basis)
    blob = json.dumps(new).lower()
    check(G, "corrections not described as 'inferred'", "inferred" not in blob)
    check(G, "no claim of Registry verification",
          not re.search(r"verified (with|by) the registry",
                        blob.replace("not independently verified with the registry", "")))

    # Source dates: verbatim and complete
    sq = squash(text)
    check(G, "every dates_in_source is verbatim in the PDF",
          all(squash(e["dates_in_source"]) in sq for e in E),
          [e["id"] for e in E if squash(e["dates_in_source"]) not in sq])
    pdf_dates = collections.Counter(DATE.findall(text))
    json_dates = collections.Counter(d for e in E for d in DATE.findall(e["dates_in_source"]))
    check(G, "date tokens in PDF == date tokens in dates_in_source (both directions)",
          pdf_dates == json_dates, (pdf_dates - json_dates, json_dates - pdf_dates))

    corrected = {e["id"]: (e["dates_in_source"], e["dates"]) for e in E if e["date_corrected"]}
    check(G, "exactly RM2027-11 and RM2027-13 corrected, with the approved values",
          corrected == {"RM2027-11": ("13/09/2026 - 17/09/2027", "13/09/2027 - 17/09/2027"),
                        "RM2027-13": ("01/11/2027 - 12/11/202", "01/11/2027 - 12/11/2027")},
          corrected)
    check(G, "uncorrected events: dates == dates_in_source",
          all(e["dates"] == e["dates_in_source"] for e in E if not e["date_corrected"]))
    O = {e["id"]: e for e in orig["events"]}
    check(G, "approved dates equal the original JSON's dates",
          all(e["dates"] == O[e["id"]]["dates_as_written"] for e in E))

    # Approved dates sanity
    probs = []
    last = {}
    for e in E:
        s, t = parse_range(e["dates"])
        if (s.isoformat(), t.isoformat()) != (e["start_date"], e["end_date"]):
            probs.append((e["id"], "ISO mismatch"))
        if s.year != 2027 or t.year != 2027:
            probs.append((e["id"], "not 2027"))
        if t < s or (t - s).days > 120:
            probs.append((e["id"], "bad span", (t - s).days))
        key = (e["calendar_group"], e["semester"])
        if key in last and s < last[key]:
            probs.append((e["id"], "out of order"))
        last[key] = s
    check(G, "approved dates: valid, 2027, ISO match, end>=start, span<=120d, in order",
          not probs, probs)

    # rag_text
    rbad = []
    for e in E:
        r = e["rag_text"]
        if rag_field(r, "DATES") != e["dates"]:
            rbad.append((e["id"], "DATES"))
        if rag_field(r, "STATUS") != "Approved 2027 road map for this project.":
            rbad.append((e["id"], "STATUS"))
        corr = rag_field(r, "DATE CORRECTION")
        if e["date_corrected"] != (corr is not None):
            rbad.append((e["id"], "DATE CORRECTION presence"))
        if corr and (e["dates_in_source"] not in corr or e["dates"] not in corr):
            rbad.append((e["id"], "DATE CORRECTION text"))
        body = "\n".join(l for l in r.split("\n") if not l.startswith("DATE CORRECTION"))
        if e["date_corrected"] and e["dates_in_source"] + "\n" in body + "\n":
            rbad.append((e["id"], "erroneous date used outside correction line"))
        if f"RECORD: {e['id']}" not in r:
            rbad.append((e["id"], "RECORD"))
    check(G, "event rag_text: DATES, STATUS, DATE CORRECTION lines consistent", not rbad, rbad)

    # Semester summaries agree with events
    sbad = []
    for s in new["semester_summaries"]:
        evs = [e for e in E if (e["calendar_group"], e["semester"]) ==
               (s["calendar_group"], s["semester"])]
        acts = [(a["activity"], a["dates"], a["dates_in_source"]) for a in s["activities"]]
        if acts != [(e["activity"], e["dates"], e["dates_in_source"]) for e in evs]:
            sbad.append((s["id"], "activities differ from events"))
        for a in s["activities"]:
            if a["dates"] not in s["text"]:
                sbad.append((s["id"], a["activity"], "missing from text"))
            if a["date_corrected"] and f"prints {a['dates_in_source']};" not in s["text"]:
                sbad.append((s["id"], a["activity"], "no correction note"))
        if "STATUS: Approved 2027 road map for this project." not in s["text"]:
            sbad.append((s["id"], "STATUS"))
    check(G, "semester summaries agree with events (dates, source dates, notes, status)",
          not sbad, sbad)
    check(G, "every corrections_applied entry keeps dates_in_source and corrected_to",
          all(c["dates_in_source"] and c["corrected_to"] for c in new["corrections_applied"])
          and len(new["corrections_applied"]) == 2)
    return new


def main(intake_pdf, roadmap_pdf):
    validate_intake(intake_pdf)
    validate_roadmap(roadmap_pdf)
    failed = [r for r in results if not r["ok"]]
    (HERE / "validation_report.json").write_text(json.dumps(
        {"date": dt.date.today().isoformat(),
         "files": {p.name: sha256(p) for p in (NEW_INTAKE, NEW_ROADMAP)},
         "passed": len(results) - len(failed), "failed": len(failed), "checks": results},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = ["# Stage 2 corrected files: validation report", "",
             f"Run: {dt.date.today().isoformat()}  |  checks: {len(results)}  |  "
             f"passed: {len(results) - len(failed)}  |  failed: {len(failed)}", "",
             "| Group | Check | Result | Detail |", "|---|---|---|---|"]
    for r in results:
        detail = r["detail"] if not r["ok"] else ""
        lines.append(f"| {r['group']} | {r['check']} | {'PASS' if r['ok'] else 'FAIL'} | "
                     f"{detail.replace('|', '/')} |")
    lines += ["", "Validated files:", ""]
    lines += [f"- `{p.name}` sha256 `{sha256(p)}`" for p in (NEW_INTAKE, NEW_ROADMAP)]
    (HERE / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for r in results:
        print(("PASS " if r["ok"] else "FAIL ") + f"[{r['group']}] {r['check']}"
              + ("" if r["ok"] else f"  -> {r['detail']}"))
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(*(sys.argv[1:3] or (DEFAULT_INTAKE_PDF, DEFAULT_ROADMAP_PDF)))
