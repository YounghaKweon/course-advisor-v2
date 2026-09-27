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

**Hybrid retrieval:** semantic search alone has no awareness of
structured fields like `Instructors` as literal, filterable data — see
Known Limitations. Instructor-name questions ("What does [instructor]
teach?") are checked against a full-name index built from Chroma metadata
at startup; any exact match is force-included in the result set before the
remaining slots are filled with semantic results. Content/topic questions
are unaffected and use the semantic path exactly as before.

**Course-code hybrid retrieval:** same gap as instructor names,
different field — exact course-code questions (`CHEM 101-A`, `CS 104 lab
sections`) compete on embedding similarity like everything else and can
lose to a more generic semantic match (found by the Week 4 eval harness,
see git history). Fixed the same way: an index built at startup from
`SectionName` metadata, keyed on both the full section name (`cs 104l-a`)
and its base course code with the section letter stripped (`cs 104l`), so
a bare code like "CS 104" correctly returns every section of that course.
The `"lab"` keyword is handled explicitly — a question about "CS 104 lab
sections" never contains the literal string `104L` (that's data-internal
shorthand), so the matcher checks for a `<code>L` family when the question
says "lab" and routes there instead of the bare lecture family. When both
a full section name and its bare code match the same question (e.g.
"CHEM 101-A" contains "CHEM 101"), only the more specific match is kept,
so asking about one section doesn't pull in the whole course. This does
**not** cover title-based lookups like "General Chemistry I are open?" —
that has no literal course code in the question at all, so it's still a
pure semantic-search case, not a hybrid-retrieval one (see Known
Limitations).

**Automated evaluation:** `backend/test_eval.py` runs a 50-entry
golden dataset (`backend/golden_dataset.json`) through the live retrieval +
generation pipeline and scores two separate things: retrieval recall
against known-correct section IDs (deterministic, no LLM call), and answer
quality via LLM-as-judge (`gemini-3.5-flash`, temperature 0), grounded in
the actual retrieved catalog text so the judge can't confuse "extra
correct detail" with "fabrication." 10 of the 50 entries are meeting-time
queries — tracked for visibility but excluded from scoring, since grading
a documented gap as a failure doesn't surface anything new.

Current results (after the Week 6 course-code fix): **99% retrieval
recall@15**, **100% answer-quality pass rate**, across the same 36/38
applicable entries as before. The harness caught a real, previously
undocumented gap in the process — see Known Limitations below.

Run it: `cd backend && python test_eval.py` (writes/resumes
`eval_report.json`) or `pytest test_eval.py -v -s` for full per-entry
output.

**Deployment & CI/CD:** see below.

## Known Limitations

- ~~Exact course-code lookups are unreliable~~ — **fixed in Week 6.**
  Originally found by the Week 4 eval harness ("Who teaches CHEM 101-A?"
  and "Who teaches the CS 104 lab sections?" both missed their expected
  sections under pure semantic search). See "Course-code hybrid
  retrieval" above for the fix. Not covered by this fix:
  **title-based course lookups**, e.g. "What sections of General
  Chemistry I are open?" — there's no literal course code in that
  question, so it's still evaluated purely on semantic similarity to
  the section description, and retrieval can still be incomplete (4/5
  in eval testing). That's a genuinely different problem — matching a
  course's common name to its code isn't a lookup, it's the kind of
  fuzzy-match task semantic search is supposed to handle, and stays
  out of scope for the hybrid-retrieval fix.

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
    name matching and needs its own scoping pass. Still open as of
    Week 5, which focused on deployment rather than retrieval.

## Deployment & CI/CD

### Live demo

> Infrastructure is torn down between active use to conserve Azure student
> credit — see Cost management below. If these links are dead, that's why;
> redeploy takes one command.

- Frontend: `https://lemon-dune-0c50ccc0f.7.azurestaticapps.net`
- Backend API: `https://courseadvisor-api-tpqg65hzxenru.azurewebsites.net`

### Architecture

```
GitHub (main branch)
    │
    ├── push touches backend/**  ──▶ GitHub Actions ──▶ Azure App Service (B1, Linux, Python 3.14)
    │                                                     runs FastAPI via gunicorn + uvicorn workers
    │                                                     loads committed Chroma index at startup
    │                                                     calls Gemini API (embeddings + generation)
    │
    └── push touches frontend/** ──▶ GitHub Actions ──▶ Azure Static Web App (Free tier)
                                                          Vite/React build, VITE_API_BASE_URL
                                                          injected at build time → points at backend
```

All infrastructure is defined in `infra/main.bicep` and provisioned via
Azure CLI — no resources were created by hand through the Portal. The
entire deployment is reproducible from a clean subscription with the two
commands under "Redeploying," below.

### Why App Service + Static Web Apps, not one combined host

Static Web Apps' free tier only serves static assets (plus optional Azure
Functions for an API layer). The backend needs a long-running FastAPI
process holding an in-memory Chroma index and hybrid-retrieval instructor
lookup built at startup — a job for App Service, not a Functions-based
API. Splitting frontend and backend into separate resources also means
they scale, deploy, and fail independently: a broken frontend build
doesn't touch the API, and vice versa.

### Why Python 3.14, not 3.11

Originally targeted 3.11 to match the toolchain at the time. Deployment
surfaced a real version mismatch: local development had drifted to Python
3.14, and `pip freeze` captured `numpy==2.5.1`, which requires Python
≥3.12. Rather than downgrade `numpy` to patch over the symptom, the App
Service runtime was bumped to 3.14 to match local — the more correct fix,
since it keeps local and production environments aligned going forward
instead of papering over one broken dependency.

### CI/CD pipeline

Two independent GitHub Actions workflows, path-filtered so unrelated
changes don't trigger unnecessary redeploys:

- `.github/workflows/backend-deploy.yml` — triggers on `backend/**`,
  deploys via Azure App Service publish profile (GitHub Actions secret,
  never in the repo)
- `.github/workflows/frontend-deploy.yml` — triggers on `frontend/**`,
  builds with Vite and deploys via Static Web Apps deployment token
  (also a GitHub secret)

### Cost management

App Service B1 (Basic) is **not** part of Azure's always-free services —
it draws continuously from the Azure for Students $100 credit at roughly
$13/month regardless of traffic, since billing is for the App Service
Plan itself, not per-request. Static Web Apps' Free tier costs nothing.

Given this project doesn't run production traffic, the working pattern is
**tear down when not actively demoing, redeploy before an interview or
demo**:

```bash
# Tear down (stops all billing for this project)
az group delete --name rg-course-advisor --yes --no-wait

# Redeploy from scratch (recreates identical resource names via
# Bicep's deterministic uniqueString(), so shared links stay valid)
az group create --name rg-course-advisor --location eastus2
az deployment group create --resource-group rg-course-advisor \
  --template-file infra/main.bicep --parameters geminiApiKey='<current key>'
```

After a fresh Bicep deploy, both GitHub Actions workflows must be manually
re-run once (Actions tab → most recent run → Re-run all jobs), since the
new App Service and Static Web App start with no application code — Bicep
only provisions the infrastructure shell.
