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

## Known Limitations
- **Structured lookups (instructor name, exact meeting day/time) are
  unreliable.** Retrieval is pure semantic similarity over course title +
  description text — it has no awareness of the `Instructors` or
  `MeetingPatterns` fields as literal, filterable data. A query like "What
  does [instructor] teach?" or "MWF classes before 10am" can silently miss
  sections that plainly match, because those attributes aren't part of what
  gets embedded. Verified during testing: an instructor-name query missed a
  section that literally matched, and a day/time query missed 103 real
  matching sections in the catalog.
  - Content/topic questions ("courses about X," "is there a Y course") are
    unaffected and tested reliably.
  - Fix path: hybrid retrieval — filter on structured metadata (Chroma's
    `where` clause) for exact-match fields, combined with semantic search
    for content. Planned for a later iteration.
