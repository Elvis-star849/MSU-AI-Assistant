# Eligibility rules verification report

**Date:** 2026-10-15
**Audited file:** `src/eligibility/MSU_Eligibility_Rules.json` (sha256 `3ffb21c6…`). It was **not changed** by this audit.

**Sources:**
- the original advert PDF, `data/source_pdfs/MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf` (sha256 `c6c76718…`, 37 pages);
- the approved structured advert records used for knowledge base 0006, `MSU_2027_Intake_Corrected_v2.json` (sha256 `a91f01d6…`).

**Method:**
- `evaluation/eligibility_audit/audit_rules.py` checks automatically:
  - every rule field against the advert record;
  - the requirement words against the PDF page;
  - each coded rule element against the advert wording;
  - ambiguity markers.
- An AI-assisted review (`manual_review.json`) gives a verdict on the findings.

**Full per-programme results:** `rules_audit.csv` / `rules_audit.json` (141 rows). Each row holds:
- programme name;
- faculty;
- source page;
- the advert requirements as printed;
- the rule as coded;
- mismatches;
- ambiguities;
- the review verdict.

> This is an engineering audit, not an MSU decision. Every item marked "needs human verification" requires a person with authority from MSU Admissions.

## 1. Coverage

| Check | Result |
|---|---|
| Undergraduate and diploma programmes in the advert | 141 |
| Programmes in the rules file | 141, the same IDs. None missing, none extra. |
| Name, faculty, duration, modes and source page vs advert record | identical for all 141 |
| Requirement text vs advert record | identical for 140; **1 garbled** (MSU-JF2027-133) |
| Requirement words found on the original PDF page (±1 page) | ≥ 80 % for all 141 |

## 2. Results

| Route | Consistent | Confirmed mismatch | Needs human verification | Total |
|---|---|---|---|---|
| A Level (decided by the checker) | 12 | **7** | 68 | 87 |
| O Level only | 4 | 0 | 0 | 4 |
| Other qualification (not decided by grades) | 11 | 5 | 34 | 50 |
| **Total** | **27** | **12** | **102** | **141** |

"Consistent" means every coded element was found in the advert wording and no ambiguity marker was found. It is not a human sign-off.

## 3. Confirmed mismatches (12)

| ID | Programme | Page | Advert says | Rule says | Impact |
|---|---|---|---|---|---|
| MSU-JF2027-001, -002, -006, -012, -013, -016, -017 | Agricultural Economics and Development; Agricultural Value Chain and Marketing; Agronomy; Animal and Wildlife Sciences; Fisheries and Aquaculture Sciences; Environmental Science and Technology; Water and Sanitation Technology | 1–3 | Faculty note: "'O' Level Maths required for all programmes" | O Level: English Language only | **High.** An applicant without O Level Maths can be told they meet the requirements. |
| MSU-JF2027-003, -007, -014, -018 | Agricultural Economics; Crop Science; Animal Science; Land and Water Resources Management (diploma routes) | 1–3 | same faculty note | O Level: English only | Low. Not decided by grades; only the "to confirm" text is affected. |
| MSU-JF2027-133 | Mining Engineering (diploma/employment route) | 23 | "…including Mathematics, English and Combined Science or equivalent. National Diploma…" | Requirement text split mid-sentence ("…including i."); O Level omits Combined Science | Low. The text shown to users is garbled. |

**Proposed fixes. These were not applied; they need your approval.**
1. Add `"Mathematics": null` to `o_level_rule.required_subjects` for all 11 Faculty of Agriculture programmes.
2. For MSU-JF2027-133:
   - replace `requirements_as_advertised` with the advert record's three lines;
   - add `"Combined Science": null`.

After a fix: re-run `audit_rules.py`, `test_checker.py`, and the unit tests. `test_checker.py` has no Agriculture case, so add one.

**Interim safeguard (implemented, rules unchanged):** the 7 high-impact programmes carry a user-facing warning from `src/eligibility/rule_warnings.json`. A programme with a warning is **never** shown as "meets the advertised requirements". It appears as a conditional match, with "You need O Level Mathematics; check with the Admissions Office".

## 4. Ambiguities that need human verification (questions for MSU Admissions)

**Highest impact first.** These are also shown to users as "Rule under review" warnings.

| ID | Programme | Advert wording | Rule | Question |
|---|---|---|---|---|
| MSU-JF2027-126 | Electrical and Electronic Engineering | "At least two Advanced Level passes; Mathematics, Physics and any other relevant science subject" | 2 subjects (Maths, Physics) | Is a third science A Level required? |
| MSU-JF2027-129 | Fuels and Energy Engineering | "…Mathematics, Physics or Chemistry and any other relevant science subject" | 2 subjects | Is a third science A Level required? |
| MSU-JF2027-132 | Mining Engineering | "A Level passes in Mathematics, Physics and any other science subject" | **3** subjects | Inconsistent with -126/-129. Confirm. |
| MSU-JF2027-147 | Bachelor of Laws | "…and any other A level subject from Arts/Humanities with B or better" | B applied to the third subject only | Does "B or better" apply to all three subjects? |
| MSU-JF2027-212, -213, -214 | Peace, Human Rights and Social Justice; Peace and Security Studies; Peace, Leadership and Governance | "two Advanced level passes in Humanities/Social Sciences" | Assumed ARTS category | Which subjects count (Sociology? Geography? Economics?) |

**Recurring patterns** (A Level programmes; one programme can have several):

| Pattern | Programmes | What a human must decide |
|---|---|---|
| Subject categories (science / commercial / arts / language) | most A Level rules | The taxonomy in the rules file is an assumption (stated in its `meta.assumptions`). The Admissions Office should confirm the subject lists. |
| "relevant" subject or qualification, undefined | 41 | What counts as relevant |
| "/" or "and/or" alternatives | 37 | The scope of each alternative |
| Diploma/certificate route also allowed but not modelled | 35 | Fine for now: these applicants are not decided by grades. Should the checker mention the alternative route? |
| "any other" subject | 34 | Whether "any other" is restricted to a category |
| Number of A Levels not stated as a number | 27 (23 coded as 2, 4 as 3) | Confirm the number |
| Employment wording vs the rule's employment flag | 19 | Usually an alternative route; confirm |
| "equivalent" qualification | 10 | What counts as equivalent |
| "preferably" | 8 | Coded as a preference, not a requirement (modeller's note). Confirm. |
| "may be considered" (discretionary) | 8 | Discretionary entry cannot be decided by rules |

The audit's "grade mentioned but not used by the A Level rule" heuristic (21 programmes) was reviewed. In these cases the grade belongs to an O Level condition that the rule does encode, such as "O Level Mathematics C or better". This was not counted as an issue, but the items remain in the CSV for review.

## 5. Audit false positives

- **MSU-JF2027-054 (Applied Accounting):** "Accounting plus any two Commercial subject" means 3 subjects, so the 3-slot rule is correct. The automatic check had matched "two (2) passes" in the alternative employment route.

## 6. How to re-run

```
python evaluation/eligibility_audit/audit_rules.py      # regenerates rules_audit.json/.csv and src/eligibility/rule_warnings.json
```

Review verdicts and user-facing warning texts live in `evaluation/eligibility_audit/manual_review.json`. Once MSU confirms or corrects a rule:
- edit the rules file (with approval);
- update or remove its verdict;
- re-run the audit: the warning disappears when the verdict is removed.
