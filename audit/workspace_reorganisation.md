# Workspace reorganisation: 2026-10-13

**Process note:** these moves were carried out right after the project owner chose Option 1 ("source PDFs inside MSU-AI-Assistant"). That was before the later request for a movement plan to approve first. This file is therefore the complete record of what was moved, not a plan. Nothing was deleted. Every move can be reversed with the commands at the end.

## Result

```
RAG\
├── msu docs\                      document datasets
│   ├── HUMANITIES … final done (1).pdf          (never moved)
│   ├── SCIENCES … VOLUME2 final done (1).pdf    (never moved)
│   └── 2027\  *_v2.json  +  originals\
├── MSU-AI-Assistant\              application + all project work
│   ├── data\source_pdfs\  audit\  stage2\  eval\test_questions\   (new, untracked)
│   └── (everything else unchanged)
└── unrelated\                     not needed; kept, not deleted
```

## Complete move record (source → destination)

All paths are relative to `C:\Users\donal\OneDrive\Desktop\RAG\` unless they start with `C:\`.

| # | Source | Destination | Action |
|---|---|---|---|
| 1 | `msu docs\MSU_2027_Intake_Corrected.json` | `msu docs\2027\originals\` | move |
| 2 | `msu docs\2027_ROADMAP_RAG_Ready.json` | `msu docs\2027\originals\` | move |
| 3 | `stage2_corrected\MSU_2027_Intake_Corrected_v2.json` | `msu docs\2027\` | move |
| 4 | `stage2_corrected\2027_ROADMAP_RAG_Ready_v2.json` | `msu docs\2027\` | move |
| 5 | `stage2_corrected\build_corrected.py` | `MSU-AI-Assistant\stage2\` | move (paths updated) |
| 6 | `stage2_corrected\validate_corrected.py` | `MSU-AI-Assistant\stage2\` | move (paths updated) |
| 7 | `stage2_corrected\CHANGES.md` | `MSU-AI-Assistant\stage2\` | move (paths updated) |
| 8 | `stage2_corrected\validation_report.md` | `MSU-AI-Assistant\stage2\` | move (regenerated) |
| 9 | `stage2_corrected\validation_report.json` | `MSU-AI-Assistant\stage2\` | move (regenerated) |
| 10 | `unrelated\New folder (2)\MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf` | `MSU-AI-Assistant\data\source_pdfs\` | move |
| 11 | `C:\Users\donal\Downloads\2027 DRAFT ROADMAP fin (1).pdf` | `MSU-AI-Assistant\data\source_pdfs\` | **copy** (original left in Downloads) |
| 12 | `audit\architecture_report.md` | `MSU-AI-Assistant\audit\` | move |
| 13 | `audit\step2_proposal.md` | `MSU-AI-Assistant\audit\` | move |
| 14 | `audit\stage2_json_review.md` | `MSU-AI-Assistant\audit\` | move |
| 15 | `eval\msu_rag_test_questions.md` / `.csv` / `.json` | `MSU-AI-Assistant\eval\test_questions\` | move |
| 16 | `eval\msu_rag_test_questions_mixed.md` | `MSU-AI-Assistant\eval\test_questions\` | move |
| 17 | `msu-assistant\` (separate Chroma/Ollama project) | `unrelated\msu-assistant\` | move (whole folder) |

The emptied folders `stage2_corrected\`, `audit\` and `eval\` were removed once empty.

The following were already in `unrelated\` before this step and were left there:
- `New folder\`: older intake conversions, `msu-admissions-chatbot`, the tutorials zip.
- The rest of `New folder (2)\`: the `.csv`, `.md` and `.pdf` intake conversions.

## Reference updates

| File | Change |
|---|---|
| `stage2/build_corrected.py`, `stage2/validate_corrected.py` | Input and output paths now point to `msu docs/2027/` and `msu docs/2027/originals/`; PDF paths default to `data/source_pdfs/` |
| `msu docs/2027/*_v2.json` | Rebuilt. The only difference is the report paths stored in the `verification` metadata. 60/60 checks pass. |

No application file references any moved item. `src/data_loader.py` still points at `RAG\msu docs`, which still holds exactly the two yearbook PDFs; JSON files are not loaded.

## Not moved (needs approval if wanted)

The following are tracked in git and unused by the application. They were left in place, because notebooks and git history are to be preserved:
- `1-rag_evaluation.ipynb`
- `PageIndex_Vectorless_RAG_CrashCourse (1).ipynb`
- `typesense.ipynb`
- `books.jsonl`
- `agenticrag/`

`bash.exe.stackdump` is untracked and git-ignored.

## Verification (after the moves)

| Check | Result |
|---|---|
| Moved files byte-identical (SHA-256 before/after) | 18/18 |
| Project + yearbook files unchanged (SHA-256), incl. indexes, eval/stage5-7, notebooks, src, app.py, config | 135/135 |
| Corpus fingerprint **rebuilt from the source PDFs** in `msu docs` (10,732 chunks, no embeddings) | `sha256:545d0dab…41f5`, matches `s6_6_freeze.json` and `src/evidence.py` |
| `faiss_store` and `faiss_store_v2` load with the frozen fingerprint check | Pass (10,732 records each) |
| `Assistant.create(offline=True)`: real Stage 6 retrieval, no LLM call | Pass. The Council question returned Sciences p.19 and Humanities p.18 as its top results; the HAWS 433 question was sent to code-aware search (code_hybrid). |
| Unit tests (`python -m unittest discover -s tests -t .`) | 75/75 OK |
| `streamlit run app.py` (headless) | Server healthy, page HTTP 200; stopped afterwards |
| FAISS / BM25 / embeddings rebuilt | No |
| `git status` | Only untracked `audit/`, `data/`, `eval/test_questions/`, `stage2/`; HEAD `eb9ccff` unchanged; nothing committed |

## Rollback

Run from `RAG\` in Git Bash:

```
mv "msu docs/2027/originals/"*.json "msu docs/"
mkdir stage2_corrected && mv "msu docs/2027/"*_v2.json MSU-AI-Assistant/stage2/* stage2_corrected/
rmdir "msu docs/2027/originals" "msu docs/2027" MSU-AI-Assistant/stage2
mv "MSU-AI-Assistant/data/source_pdfs/MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf" "unrelated/New folder (2)/"
rm "MSU-AI-Assistant/data/source_pdfs/2027 DRAFT ROADMAP fin (1).pdf"   # a copy; the original is still in Downloads
mv MSU-AI-Assistant/audit audit
mkdir eval && mv MSU-AI-Assistant/eval/test_questions/* eval/ && rmdir MSU-AI-Assistant/eval/test_questions
mv unrelated/msu-assistant msu-assistant
```

After a rollback, the stage2 scripts' paths would need reverting too.

---

## Follow-up move (approved 2026-10-13)

**Reference check.** None of the five items is imported, opened or referenced by `src/`, `app.py`, `tests/`, `eval/` or the main notebook. They are generic tutorial material:
- RAG evaluation, PageIndex, Typesense and agentic-RAG notebooks;
- `books.jsonl`, a Goodreads book list used only by `typesense.ipynb`.

The only other mention is the `typesense` package line in `requirements.txt`. It is used only by that notebook and was left unchanged.

| # | Source (in `MSU-AI-Assistant\`) | Destination | SHA-256 (unchanged) |
|---|---|---|---|
| 18 | `1-rag_evaluation.ipynb` | `unrelated\from_MSU-AI-Assistant\` | `ad0070d4…` |
| 19 | `PageIndex_Vectorless_RAG_CrashCourse (1).ipynb` | `unrelated\from_MSU-AI-Assistant\` | `bbefe415…` |
| 20 | `typesense.ipynb` | `unrelated\from_MSU-AI-Assistant\` | `f375c58c…` |
| 21 | `books.jsonl` | `unrelated\from_MSU-AI-Assistant\` | `3a2ba544…` |
| 22 | `agenticrag\1-agenticrag.ipynb` (whole folder) | `unrelated\from_MSU-AI-Assistant\agenticrag\` | `11861b16…` |

**Verification after the move:**
- The other 130 project and yearbook files are byte-identical.
- The corpus fingerprint rebuilt from source is `545d…41f5`, a match.
- Both indexes load with the fingerprint check.
- The offline app search returned the same top pages as before.
- 75/75 tests pass.
- The Streamlit server came up healthy.

**Git.** These five files are tracked. Git now shows them as unstaged deletions (` D`), because they are no longer inside the repository; nothing is committed. Their history stays in git. To restore them, run `git checkout -- <file>` or move them back.
