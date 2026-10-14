# Stage 2 corrected files: validation report

Run: 2026-10-13  |  checks: 60  |  passed: 60  |  failed: 0

| Group | Check | Result | Detail |
|---|---|---|---|
| intake | every programme record has the same keys | PASS |  |
| intake | every information record has the same keys | PASS |  |
| intake | record ids unique | PASS |  |
| intake | 222 programme records (same as original) | PASS |  |
| intake | 4 information records | PASS |  |
| intake | programme_count per faculty matches records | PASS |  |
| intake | source PDF sha256 matches recorded hash | PASS |  |
| intake | source filename matches the real file | PASS |  |
| intake | every record carries the PDF filename and sha256 | PASS |  |
| intake | derived_from hash matches the untouched original JSON | PASS |  |
| intake | every source_page within 1..37 | PASS |  |
| intake | no programme word absent from the PDF | PASS |  |
| intake | no PDF table word missing from programme records (pp.1-36) | PASS |  |
| intake | rag_text agrees with structured fields (programme, duration, requirements, faculty, commencement, modes, page) | PASS |  |
| intake | commencement follows explicit row notes, then faculty banners | PASS |  |
| intake | exactly the 4 'commences February 2027' programmes are February | PASS |  |
| intake | PDF contains exactly 4 'commences February' notes | PASS |  |
| intake | no entry requirement ends with a dangling list marker | PASS |  |
| intake | MSU-JF2027-INFO-01 source_text is verbatim from p.1 (1 excerpt) | PASS |  |
| intake | MSU-JF2027-INFO-01 rag_text contains the full source_text | PASS |  |
| intake | MSU-JF2027-INFO-01 every number/code/email in rag_text and facts exists on the page | PASS |  |
| intake | MSU-JF2027-INFO-01 rag_text cites page 1 | PASS |  |
| intake | MSU-JF2027-INFO-02 source_text is verbatim from p.36 (2 excerpts) | PASS |  |
| intake | MSU-JF2027-INFO-02 rag_text contains the full source_text | PASS |  |
| intake | MSU-JF2027-INFO-02 every number/code/email in rag_text and facts exists on the page | PASS |  |
| intake | MSU-JF2027-INFO-02 rag_text cites page 36 | PASS |  |
| intake | MSU-JF2027-INFO-03 source_text is verbatim from p.36 (1 excerpt) | PASS |  |
| intake | MSU-JF2027-INFO-03 rag_text contains the full source_text | PASS |  |
| intake | MSU-JF2027-INFO-03 every number/code/email in rag_text and facts exists on the page | PASS |  |
| intake | MSU-JF2027-INFO-03 rag_text cites page 36 | PASS |  |
| intake | MSU-JF2027-INFO-04 source_text is verbatim from p.37 (1 excerpt) | PASS |  |
| intake | MSU-JF2027-INFO-04 rag_text contains the full source_text | PASS |  |
| intake | MSU-JF2027-INFO-04 every number/code/email in rag_text and facts exists on the page | PASS |  |
| intake | MSU-JF2027-INFO-04 rag_text cites page 37 | PASS |  |
| intake | automated verification recorded on every record | PASS |  |
| intake | human approval kept separate and pending on every record | PASS |  |
| intake | old verification_status/verification_note fields removed (history kept only under verification.prior_check) | PASS |  |
| intake | content changed only in -099, -100, -107, -108, -133 | PASS |  |
| intake | top-level text fields unchanged | PASS |  |
| roadmap | 21 events | PASS |  |
| roadmap | every event has the same keys | PASS |  |
| roadmap | event ids unique and sequential | PASS |  |
| roadmap | source PDF sha256 matches | PASS |  |
| roadmap | source filename preserved (contains DRAFT) | PASS |  |
| roadmap | every event and summary carries filename, sha256 and page 1 | PASS |  |
| roadmap | derived_from hash matches the untouched original JSON | PASS |  |
| roadmap | status is 'approved' at top level and on every event/summary | PASS |  |
| roadmap | status basis cites the project owner's confirmation | PASS |  |
| roadmap | status basis disclaims independent Registry verification | PASS |  |
| roadmap | corrections not described as 'inferred' | PASS |  |
| roadmap | no claim of Registry verification | PASS |  |
| roadmap | every dates_in_source is verbatim in the PDF | PASS |  |
| roadmap | date tokens in PDF == date tokens in dates_in_source (both directions) | PASS |  |
| roadmap | exactly RM2027-11 and RM2027-13 corrected, with the approved values | PASS |  |
| roadmap | uncorrected events: dates == dates_in_source | PASS |  |
| roadmap | approved dates equal the original JSON's dates | PASS |  |
| roadmap | approved dates: valid, 2027, ISO match, end>=start, span<=120d, in order | PASS |  |
| roadmap | event rag_text: DATES, STATUS, DATE CORRECTION lines consistent | PASS |  |
| roadmap | semester summaries agree with events (dates, source dates, notes, status) | PASS |  |
| roadmap | every corrections_applied entry keeps dates_in_source and corrected_to | PASS |  |

Validated files:

- `MSU_2027_Intake_Corrected_v2.json` sha256 `a91f01d6c67f3f90e21d99f03408eed7d01a18d9dcd8def1ea3d76898a470cbc`
- `2027_ROADMAP_RAG_Ready_v2.json` sha256 `27f98ef3c0f4df82874f2db495dc7ca3fd4d3838ad396db004accb3d07f4ed17`
