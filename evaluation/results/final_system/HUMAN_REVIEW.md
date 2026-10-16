# MSU AI Admissions Assistant: items for human review

Prepared on 2026-10-16 with AI assistance. **This is not an MSU decision.** Every item below needs an answer from
MSU staff (the Admissions Office or a delegated reviewer). The system shows each open item to applicants as
*conditional* or *please confirm*, and never as a definitive answer. The original source documents are unchanged.

## A. Corrections already applied (please confirm)

The supplied rules file `src/eligibility/MSU_Eligibility_Rules.json` was kept as
`MSU_Eligibility_Rules.supplied.json` (sha256 prefix `3ffb21c60db1dce1`, not modified). The corrected file is built
by `evaluation/eligibility_audit/apply_corrections.py` from `corrections.json`. That script asserts every old value
before it changes anything, and `--check` confirms the built file is up to date. Each correction has a regression
test.

| ID | Programmes | Old value | New value | Advert evidence | Justification |
|---|---|---|---|---|---|
| C1 | 11 Faculty of Agriculture programmes (001, 002, 003, 006, 007, 012, 013, 014, 016, 017, 018) | O Level: English Language only | O Level: English Language **and Mathematics** | pp. 1–3, faculty note "'O' Level Maths required for all programmes" | The faculty note states it for all programmes |
| C2 | 133 | Requirement text split mid-sentence (garbled) | The advert record's three requirement lines | p. 23 | Display text only |
| C3 | 133 | O Level omits Combined Science | Adds Combined Science | p. 23 | Named in the advert |
| C4 | 025 African Languages and Culture | O Level: no African language | O Level: adds "African language" | p. 4 | Named in the advert |
| C5 | Subject taxonomy | Geography = Arts only | Geography = Arts **and** Science | p. 24 lists Geography among science subjects | Geography counts as a science only *conditionally* (the shown question is item B6) |

Rules audit after the corrections (`evaluation/results/eligibility_rules_audit/rules_audit.json`):

- 141 programmes are covered, none missing;
- 12 rules are corrected, 0 confirmed mismatches remain, 27 are consistent, and 102 need human verification (mostly
  undefined "relevant" or "equivalent" wording);
- the single automatic "mismatch" left (054 Applied Accounting) is a reviewed false positive;
- the pre-correction audit is kept in `pre_correction_backup/`.

## B. Open eligibility questions (not decided by the system)

These live in `src/eligibility/rule_overrides.json`. Where the advert can be read two ways, the file records a strict
reading and a lenient reading:

- an applicant who meets the **strict** reading gets "meets the advertised requirements";
- an applicant who meets **only the lenient** reading gets "conditional", with the question shown.

| # | Programme (advert page) | Question for Admissions |
|---|---|---|
| B1 | 126 Electrical and Electronic Eng. (p. 21), 129 Fuels and Energy Eng. (p. 22) | "At least two A Level passes; Mathematics, Physics and any other relevant science subject": is a **third science** required? 132 Mining Engineering, with similar wording, is coded with 3. Should all three engineering programmes be treated the same way? |
| B2 | 147 LLB (p. 26) | Does "with B or better" apply to **all three** A Level subjects, or only to the third? Please also confirm O Level English B and Mathematics B. |
| B3 | 169 Actuarial Science (p. 30) | How are the "10 points at A Level" counted (best three subjects?), and which subjects are "acceptable"? |
| B4 | 006, 012, 016, 017 (Agriculture, pp. 2–3); 025 (p. 4) | Is "preferably Biology/Agriculture …" (or "preferably Arts and Humanities") a **requirement** or only a **preference**? |
| B5 | 001, 002 (p. 1) | Sociology is in the advert's preferred list for "Sciences or Commercial subjects". Does it count as one? |
| B6 | Taxonomy | Do Geography, Statistics and Software Engineering count as **science** subjects, and Business Enterprise Skills as **commercial**? Economics as a **social science** affects 12 programmes: 020, 026, 181, 183, 185, 186, 198, 200, 202, 212, 213, 214. |
| B7 | 155, 156, 157, 165 (p. 28) | Which subjects are "any other relevant science subject"? Today only the subjects the advert names count as verified. |
| B8 | 126, 129, 132, 134, 136, 137, 140, 143 | The "may be considered" (discretionary) routes are shown as other routes and are never decided by grades. Is that correct? |
| B9 | All programmes | The subject categories (science, commercial, arts, languages) are the rules file's assumption. Please confirm the official list. |

## C. Conflicts between documents (shown to users as conflicts)

When the 2027 advert and a yearbook give different durations, the assistant shows both and labels the advert as
the current 2027 information. It never picks one silently. Detected by `src/conflicts.py`:

| Programme | 2027 advert | Yearbook |
|---|---|---|
| MSc Crop Protection | 2 years (p. 2) | 2.5 years (Sciences Vol. 2, p. 265) |
| MA Cultural Heritage Studies | 1.5 years (p. 7) | 2 years (Humanities, p. 177) |
| MA Museum Studies | 1.5 years (p. 7) | Block Release 2 years (Humanities, p. 180) |
| MA Archaeology | 1.5 years (p. 7) | 2 years (Humanities, p. 169) |
| PG Diploma in Tertiary Education | 1 year (p. 16) | 1½ years (Humanities, p. 469) |

**Policy to confirm:** for the 2027 intake, does the advert take precedence over the yearbooks for durations, entry
requirements and modes? The system currently presents the advert as the current 2027 information and the
yearbooks as older regulations, and it shows both.

## D. Decisions for the project owner

1. **Admissions phone number.** The fixed out-of-scope reply uses the wording you specified:
   "admissions@admin.msu.ac.zw or (054) 2260496".
   - The 2027 advert's enquiries section (p. 37) gives **Phone 054 2260029, WhatsApp 0716626820**, and the same email.
   - 2260496 appears only as one of about 15 university main lines in the Humanities Yearbook (p. 6).
   - The reply has not been changed. Should it use the advert's admissions number?
2. **Deadlines.** Fees, payments, scholarships and cut-off points always get the fixed reply. For deadlines:
   - if the advert itself prints a deadline for the named programme (126 and 132: "31 March 2027", pp. 21 and 23),
     the assistant quotes that sentence with its page and refers everything else to the Admissions Office;
   - all other deadline questions get the fixed reply.

   Should the advert deadline still be quoted this way, or should every deadline question get the fixed reply?
3. **Publication.** The knowledge base 0006 (with the advert) is still **staging**, and the public profile is 0005.
   The app runs on localhost with the intake profile. Publishing 0006 needs your authorisation; it was not done.
4. **Sealed evaluation.** The 60-item sealed set is frozen (`evaluation/admissions_eval/sealed/SEALED.json`) and
   has **not been run**. It is reserved for your independent review.

## E. Admissions adviser (added 2026-10-16): policy points to confirm

The conversational adviser (`src/admissions_adviser.py`, `src/entry_routes.py`) evaluates normal, special and mature
entry. Where the documents leave a point open, it shows "possible" or "could be possible" and names what the Admissions
Office decides. It never shows these routes as confirmed eligibility.

| # | Point | What the adviser does now | Evidence |
|---|---|---|---|
| E1 | **Mature entry for programmes the advert does not list.** The general regulation describes mature entry for undergraduate degrees in general, but the 2027 advert lists it for only 18 programmes. | It evaluates only the 18 listed programmes. For any other programme it says "the 2027 advert does not mention mature entry for this programme; ask the Admissions Office". | Humanities Yearbook 3.3, p. 129; advert pp. 4–30 |
| E2 | Mature entry for 026 and 027 (age only in the advert) and 100 (no age in the advert). | For 026 and 027 it applies the general regulation's 5 O Levels including English. For 100 it applies the general regulation's age (25 for men, 23 for women). Both are labelled as coming from the general regulations. | advert pp. 4, 5, 17; Yearbook 3.3 |
| E3 | Mature-entry age is measured "on the first day of the academic year". | It asks "How old will you be in January 2027?". Engineering programmes start in August 2027, so the age there is at the start of that programme. | Yearbook 3.3; advert p. 21 |
| E4 | The mature-entry age differs by sex in the advert (23 for women, 25 for men). | It asks which applies **only** to applicants aged 23 or 24, offers **Skip**, and never asks anyone else. | advert pp. 4–30 |
| E5 | "Relevant field" or "relevant work experience" is not defined. | It uses word overlap with the programme name for **ranking only**. It always says "the Admissions Office decides whether your experience is relevant". | advert pp. 26–30 |
| E6 | Special entry for degree holders. | Any degree holder is shown as "possible" for bachelor's programmes under the general Special Entry rule, ranked by how related the degree is. | Yearbook 3.2.1, p. 129 |
| E7 | An O Level "pass" without a grade ("5 passes including Maths"). | It records the subject as passed at grade C or better, matching the advert's "passes at grade C or better", and labels this "my assumption: please check". A grade-B requirement stays "to confirm". | advert general requirement, every page |
| E8 | Programmes that ask for O Levels only: 092 Diploma in Adult and Continuing Education, 107 BEd Science and Applied Technologies, 108 BEd Mathematics and Applied Statistics, 220 Undergraduate Diploma in Social Work. | It shows "meets the advertised requirements" when the stated O Levels are met. Please confirm that 107 and 108 really need no teaching qualification or A Levels. The advert entry lists only O Levels. | advert pp. 15, 18, 36 |
