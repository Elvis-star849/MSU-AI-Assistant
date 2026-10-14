"""
Remediation candidate components (development artefacts; production code is NOT changed):

  G2_SYSTEM_PROMPT        grounding prompt v2
  format_user_message()   F2 structured evidence formatting: a deterministic re-rendering of the SAME passages.
                          It never adds a fact: it labels the source type, states the scope of advert route records,
                          states explicitly when a field is absent ("not stated"), puts the road-map calendar first,
                          and appends a row-by-row reading of programme tables that have a Prerequisite column
                          (only rows that parse cleanly; blank cells become "none listed"). The original passage text
                          is always kept.
"""
import re

G2_PROMPT_VERSION = "r-g2-grounding-v1"
G2_SYSTEM_PROMPT = """You answer questions about Midlands State University (MSU) using only the numbered evidence \
passages in the user's message. The passages may come from the 2027 intake advert, the approved 2027 road map, or the \
MSU yearbooks (general information and regulations, which can be older than the 2027 advert).

Rules:
1. Use only the evidence. Never add facts, background, explanations or advice that the passages do not state.
2. Cite every fact with its evidence number, source and page. Do not cite a passage for something it does not say.
3. Answer exactly what was asked. If part of the answer is not in the evidence, say clearly which part is missing \
and give the parts that are present. If nothing relevant is present, say that the documents provided do not contain \
the information and stop.
4. Tables: read each row on its own. A blank cell (for example an empty Prerequisite) means "none listed"; never take \
a value from a neighbouring row.
5. Admission routes: a programme can have several routes (for example conventional, block release, visiting, weekend \
school), each with its own duration and requirements. Keep each route separate and never move a requirement or a \
duration from one route to another.
6. Dates: give dates exactly as stated. Do not infer a start date or month from the name of an intake, from another \
programme, or from a different activity. If a commencement date is not stated, say so. If a date comes from a faculty \
note such as "unless otherwise indicated", say that this is its basis.
7. Calendars: name the calendar each date belongs to (for example the main academic calendar or the Faculty of \
Education block release calendar), and do not swap activities (orientation, registration, commencement, tuition, \
examinations).
8. Durations: report durations exactly as printed, per route or mode as printed. If a duration is not stated, say so.
9. Different sources: if the 2027 advert and a yearbook passage differ, give both, each attributed to its source, \
state the difference, and present the 2027 advert as the current requirement. Never present a yearbook requirement \
as the current 2027 requirement or as overriding the advert, and never merge the two.
10. Questions about other institutions or topics the documents do not cover: say the MSU documents provided do not \
contain this information, and do not cite loosely related passages as if they answered it."""

# G3 = G2 rules 1-10 unchanged + rules 11-15 (dev iteration; see remediation/ITERATION_G3_PREREG.md)
G3_PROMPT_VERSION = "r-g3-grounding-v1"
G3_SYSTEM_PROMPT = G2_SYSTEM_PROMPT + """
11. Advert records: the entry requirements in one advert record apply to every mode of entry listed in that record, \
exactly as printed. Do not split them into separate routes, do not assign parts of them to particular modes, and do \
not relabel them with yearbook entry categories (normal, visiting school, special or mature entry). Use mode names \
exactly as printed. Two advert records for the same programme with different modes are separate routes, not a \
conflict.
12. Yearbook material shown next to the advert: label it as older regulations given for comparison. Do not describe \
it as an alternative, as possibly still applying, or as general or overarching criteria for the 2027 intake.
13. Commencement from a faculty note: give the month and state its basis, quoting the faculty note (for example: \
"January 2027 - basis: the faculty note says all programmes commence in January 2027 unless otherwise indicated").
14. Do not add anything that is not printed in the evidence: no campus or location, no study mode such as full-time \
or part-time, no year or edition for a yearbook, and no expansion of an abbreviation.
15. Before answering, check each sentence against rules 1-14 and remove anything the evidence does not state."""

ADVERT = "MSU January/February 2027 Intake Advert"
ROADMAP = "MSU 2027 Road Map"
HEADER = re.compile(r"\[Evidence (\d+)\]\nSource: (.+)\nPage: (.+)\n(?:Heading: (.*)\n)?Text:\n", re.M)
CODE = r"\*{0,2}[A-Z]{2,6} ?\d{3}[A-Z]?\*{0,2}"
CODE_LINE = re.compile(rf"^({CODE})(?:\s+(.+))?$")
PREREQ_TOKEN = re.compile(r"^\(?([A-Z]{2,6} ?\d{3}[A-Z]?(?:\s*[,/&]\s*[A-Z]{2,6} ?\d{3}[A-Z]?)*)\)?$")
PAREN_PREREQ = re.compile(r"^(.*?)\s*\(([A-Z]{2,6} ?\d{3}[A-Z]?(?:\s*[,/&]\s*[A-Z]{2,6} ?\d{3}[A-Z]?)*)\)\s*$")
CREDITS = re.compile(r"^\d{1,3}$")
ANY_CODE = re.compile(r"[A-Z]{2,6} ?\d{3}[A-Z]?")
TRAILING_PREREQ = re.compile(r"^(.*[a-z)])\s+([A-Z]{2,6} ?\d{3}[A-Z]?(?:\s*[,/&]\s*[A-Z]{2,6} ?\d{3}[A-Z]?)*)$")


def parse_blocks(user):
    """Split the frozen user message into (header fields, text) blocks and the trailing question."""
    qpos = user.rfind("\n\nQuestion: ")
    body, question_part = user[:qpos], user[qpos:]
    heads = list(HEADER.finditer(body))
    blocks = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        blocks.append({"n": int(h.group(1)), "source": h.group(2), "page": h.group(3), "heading": h.group(4),
                       "text": body[h.end():end].rstrip("\n")})
    return blocks, question_part


def _norm_code(c):
    m = re.match(r"([A-Z]{2,6}) ?(\d{3}[A-Z]?)", c)
    return f"{m.group(1)} {m.group(2)}" if m else c


def _only_codes(line):
    """A line that is nothing but module codes (with brackets, asterisks, commas, '&', '/', 'pre-requisite')."""
    rest = re.sub(r"\*|\[|\]|\(|\)|,|&|/|pre-?requisites?", " ", ANY_CODE.sub(" ", line), flags=re.I)
    return bool(ANY_CODE.search(line)) and not rest.strip()


ROW_START = re.compile(r"^\*{0,2}([A-Z]{2,6} ?\d{3}[A-Z]?)\*{0,2}(?:\s+(.*))?$")


def table_reading(text):
    """Row-by-row reading of programme tables that have a Prerequisite column. Returns lines or [].
    A row = a line starting with a module code up to its credits line. Its prerequisites are EVERY other module code
    printed in the row (never dropped); a blank prerequisite is 'none listed'. Rows that look merged (an inline credit
    number followed by another title) or that do not reach a credits line are not rendered."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out, i, in_table, level = [], 0, False, None
    while i < len(lines):
        l = lines[i]
        if re.match(r"^Level \d", l):
            level, in_table = l, False
            i += 1
            continue
        if re.search(r"pre-?requisite", l, re.I) and not ROW_START.match(l):
            in_table = True
            i += 1
            continue
        m = ROW_START.match(l) if in_table else None
        if not m or _only_codes(l) and not m.group(2) and i + 1 < len(lines) and CREDITS.match(lines[i + 1]):
            i += 1
            continue
        code, code_shown = _norm_code(m.group(1)), m.group(1)
        parts, j, ok = [m.group(2) or ""], i + 1, False
        while j < len(lines) and j < i + 7:
            t = lines[j]
            if CREDITS.match(t):
                ok = True
                break
            if ROW_START.match(t) and not _only_codes(t):
                break                                # next row (code followed by a title)
            if _only_codes(t) and not any(p.strip() for p in parts):
                break                                # code-only line before any title: next row starts
            if _only_codes(t) and j + 1 < len(lines) and not CREDITS.match(lines[j + 1]) and not _only_codes(lines[j + 1]):
                break                                # code-only line followed by a title: next row starts
            parts.append(t)
            j += 1
        row = " ".join(p for p in parts if p).strip()
        if not ok or not row or re.search(r"(?<![A-Z0-9])\d{1,3}\s+[A-Z][a-z]", row):
            i += 1
            continue
        shown = {}
        for c in ANY_CODE.findall(row):                  # keep each code as printed; de-duplicate on the normalised form
            if _norm_code(c) != code:
                shown.setdefault(_norm_code(c), c)
        prereq = list(shown.values())
        title = re.sub(r"\s+", " ", re.sub(r"\*|\[|\]|\(\s*\)|pre-?requisites?", " ",
                                           ANY_CODE.sub(" ", row), flags=re.I))
        title = re.sub(r"[\s,&/(]+$", "", re.sub(r"\(\s*[,&/\s]*\)", "", title)).strip(" ,&/")
        if not title or len(title) > 110:
            i += 1
            continue
        out.append(f"- {code_shown} {title} | Prerequisite: {', '.join(prereq) if prereq else 'none listed'} | "
                   f"Credits: {lines[j]}" + (f" | {level}" if level else ""))
        i = j + 1
    return out


def field(text, name):
    m = re.search(rf"^{name}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def render_block(b):
    src, text = b["source"], b["text"]
    extra = []
    if src == ADVERT:
        kind = "SOURCE TYPE: 2027 intake advert (current information for the January/February 2027 intake)."
        if field(text, "PROGRAMME") and field(text, "DURATION AS ADVERTISED"):
            dur, modes = field(text, "DURATION AS ADVERTISED"), field(text, "MODES OF ENTRY") or "not stated"
            extra.append(f"ROUTE SCOPE: this record covers ONE route of the programme only (duration as printed: "
                         f"'{dur}'; modes of entry: {modes}). Its entry requirements apply to this route only; other "
                         f"routes of the same programme are separate records.")
            if not field(text, "COMMENCEMENT"):
                extra.append("COMMENCEMENT: not stated in the advert for this programme (do not infer it from the intake name).")
            else:
                note = field(text, "FACULTY NOTE") or ""
                if "unless" in note.lower() and "commence" in note.lower() and "commences" not in (field(text, "MODES OF ENTRY") or ""):
                    extra.append(f"COMMENCEMENT BASIS: faculty note \"{note}\".")
    elif src == ROADMAP:
        kind = "SOURCE TYPE: approved 2027 road map."
        cal, sem, act, dates = (field(text, k) for k in ("CALENDAR", "SEMESTER", "ACTIVITY", "DATES"))
        if cal and act and dates:
            extra.insert(0, f"RECORD: {act} | calendar: {cal.split(' – ')[0]} | {sem} | dates: {dates}")
    else:
        kind = "SOURCE TYPE: MSU yearbook (general information and regulations; may be older than the 2027 advert)."
        if re.search(r"\b11/2\s*Y", text):
            extra.append("NOTE: '11/2' in this passage is the PDF rendering of a fraction (e.g. '11/2Years' = 1½ years).")
        rows = table_reading(text)
        if rows:
            extra.append("TABLE READ ROW BY ROW (from the table above; a blank prerequisite cell is shown as 'none listed'):\n"
                         + "\n".join(rows))
    lines = [f"[Evidence {b['n']}]", f"Source: {src}", f"Page: {b['page']}"]
    if b["heading"]:
        lines.append(f"Heading: {b['heading']}")
    lines.append(kind)
    lines += [e for e in extra if e.startswith("RECORD:")]
    lines.append(f"Text:\n{text}")
    lines += [e for e in extra if not e.startswith("RECORD:")]
    return "\n".join(lines)


def format_user_message(question, system, evidence_meta, user):
    blocks, question_part = parse_blocks(user)
    if not blocks:
        return user
    return "Evidence:\n\n" + "\n\n".join(render_block(b) for b in blocks) + question_part
