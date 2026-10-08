# Requirements carried into Stage 7 (answer generation)

## R1. Course codes with more than one meaning (from S6-5)

Some course codes name different modules in different programmes, or the yearbooks give the same code two
different titles. Example: SEMA204 is "Real Analysis" in one programme table (Humanities p. 556) and
"Introduction to Numerical Methods" elsewhere (Humanities pp. 571, 573).

Retrieval does not choose between meanings. `src/ambiguity.py` supplies, for each code in the question,
every title found in the yearbooks, the pages that give it, and whether the retrieved chunks support it
(`ambiguity_note(query, results, ambiguous_codes(code_titles(records)))`).

When the note is not empty, the answer must:
1. Not present one meaning as the only one.
2. Name each meaning with its programme and page, at least for every meaning the retrieved chunks support,
   **or** ask the student which programme they are in, when the meanings differ substantially.
3. Mention a meaning that the retrieved chunks do not support only as "also listed as ... (p. X)", without
   describing its content, because the answer can only use retrieved text.
4. Cite the page for each meaning.

Known limits of the flag (S6-5):
- About 80% of flagged codes (16/20 on a random sample) have genuinely different titles; the rest are
  renamed or respelled versions of the same module (e.g. "Principles of Marketing" / "Introduction to
  Marketing"). The wording above stays correct for those, but may be wordier than necessary.
- Recall was not measured: a code whose second meaning is written in a format the extractor does not read
  will not be flagged.

## R2. Other notes for Stage 7 (from Stage 5 / S6-2, not yet decided)

- Out-of-scope questions: MiniLM reranker scores separated in-scope from out-of-scope questions better than
  cosine similarity (S6-2 side measurement), but one out-of-scope question still scored above 6 in-scope ones.
  Any "I don't know" threshold must be set and tested in Stage 7, not assumed from these numbers.
