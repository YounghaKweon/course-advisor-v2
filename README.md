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

## Known Limitations
- **Exact meeting day/time lookups are unreliable.** Retrieval has no
  awareness of the `MeetingPatterns` field as literal, filterable data —
  a query like "MWF classes before 10am" can silently miss sections that
  plainly match, because meeting time isn't part of what gets embedded.
  Verified during testing: a day/time query missed 103 real matching
  sections in the catalog.
  - Content/topic questions and instructor-name questions are unaffected
    and tested reliably.
  - Fix path: same pattern already used for instructor matching — build a
    day/time index from `MeetingPatterns` and force-include exact matches.
    Deferred because parsing natural-language day/time references
    ("Monday afternoon," "before 10am") is a fuzzier problem than exact
    name matching and needs its own scoping pass.
