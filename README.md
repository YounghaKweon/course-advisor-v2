# course-advisor
AI Course Advisor

## How it works
FastAPI backend + React/TypeScript frontend. Course sections are embedded
(title + description) with Gemini's `gemini-embedding-001` and stored in a
local Chroma vector index (`backend/build_index.py`). Each question to
`/ask` retrieves the 15 most semantically relevant sections from that
index, then sends only those to `gemini-3.5-flash` to generate an answer —
instead of stuffing the full ~1,000-section catalog into every prompt (the
original approach: ~27,000 tokens/request, vs. ~2,000 now).

**Hybrid retrieval (Week 3):** semantic search alone has no awareness of
structured fields like `Instructors` as literal, filterable data — see
Known Limitations. Instructor-name questions ("What does [instructor]
teach?") are checked against a full-name index built from Chroma metadata
at startup; any exact match is force-included in the result set before the
remaining slots are filled with semantic results. Content/topic questions
are unaffected and use the semantic path exactly as before.

**Automated evaluation (Week 4):** `backend/test_eval.py` runs a 50-entry
golden dataset (`backend/golden_dataset.json`) through the live retrieval +
generation pipeline and scores two separate things: retrieval recall
against known-correct section IDs (deterministic, no LLM call), and answer
quality via LLM-as-judge (`gemini-3.5-flash`, temperature 0), grounded in
the actual retrieved catalog text so the judge can't confuse "extra
correct detail" with "fabrication." 10 of the 50 entries are meeting-time
queries — tracked for visibility but excluded from scoring, since grading
a documented gap as a failure doesn't surface anything new.

Current results (38 graded entries): **94% retrieval recall@15**, **97%
answer-quality pass rate**. The harness caught a real, previously
undocumented gap in the process — see Known Limitations below.

Run it: `cd backend && python test_eval.py` (writes/resumes
`eval_report.json`) or `pytest test_eval.py -v -s` for full per-entry
output.

## Known Limitations
- **Exact course-code lookups are unreliable.** Like instructor names,
  a specific course code (`CHEM 101-A`, `CS 104` lab sections) is
  structured, filterable data that semantic search has no special
  awareness of — it competes on embedding similarity like everything
  else, and can lose to a more generic semantic match. Found by the
  Week 4 eval harness, not by manual testing:
  - "Who teaches CHEM 101-A?" — 0/1 expected section retrieved.
  - "Who teaches the CS 104 lab sections?" — 0/4 retrieved; the answer
    substituted unrelated courses (`CS 108L`, `CS 112L`) that happened
    to score higher on semantic similarity.
  - "What sections of General Chemistry I are open?" — 4/5 retrieved.
  - The chatbot itself doesn't hallucinate in these cases — it answers
    honestly from what it retrieved — but what it retrieved was wrong.
  - Content/topic questions and instructor-name questions are unaffected
    and tested reliably (94% retrieval recall@15 overall, see above).
  - Fix path: same pattern as the Week 3 instructor index — build a
    course-code index (`SectionName`/`CourseNumber`) from Chroma
    metadata and force-include exact matches. Scoped as a Week 5 item
    rather than folded into Week 4, to keep "built the eval suite" and
    "fixed what it found" as separate, individually verifiable steps.

- **Exact meeting day/time lookups are unreliable.** Retrieval has no
  awareness of the `MeetingPatterns` field as literal, filterable data —
  a query like "MWF classes before 10am" can silently miss sections that
  plainly match, because meeting time isn't part of what gets embedded.
  Verified during testing: a day/time query missed 103 real matching
  sections in the catalog. The Week 4 eval harness tracks 10 meeting-time
  queries for visibility but doesn't grade them pass/fail, for the same
  reason — this is a known, scoped gap, not a bug to chase.
  - Content/topic questions and instructor-name questions are unaffected
    and tested reliably.
  - Fix path: same pattern already used for instructor matching — build a
    day/time index from `MeetingPatterns` and force-include exact matches.
    Deferred because parsing natural-language day/time references
    ("Monday afternoon," "before 10am") is a fuzzier problem than exact
    name matching and needs its own scoping pass.
