import os

import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from pydantic import BaseModel

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

EMBED_MODEL = "gemini-embedding-001"
CHAT_MODEL = "gemini-3.5-flash"
INDEX_PATH = "./chroma_index"
COLLECTION_NAME = "sections"
TOP_K = 15

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://lemon-dune-0c50ccc0f.7.azurestaticapps.net",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Loaded once at startup, not per-request — Sections.json itself is no longer
# needed here at all. Everything /ask needs (title, instructor, meeting time,
# description) now lives in the Chroma index built by build_index.py.
chroma = chromadb.PersistentClient(path=INDEX_PATH)
collection = chroma.get_or_create_collection(name=COLLECTION_NAME, embedding_function=None)


def build_instructor_index() -> dict:
    # Week 3: exact instructor-name lookup, built once at startup from the
    # metadata already in Chroma. Instructors is stored as a raw ";"-joined
    # string (co-taught sections have 2+ names) — split it into individual
    # names here so each one is independently matchable. Full name only:
    # 24 of 327 instructors share a last name (two Lees, two Mulders, two
    # Smiths, etc.), so last-name-only matching would be ambiguous and is
    # deliberately not supported.
    all_rows = collection.get(include=["metadatas"])
    index: dict[str, list[str]] = {}
    for section_id, metadata in zip(all_rows["ids"], all_rows["metadatas"]):
        raw = metadata.get("Instructors", "")
        if not raw or raw == "TBA":
            continue
        for name in raw.split(";"):
            name = name.strip()
            if name:
                index.setdefault(name.lower(), []).append(section_id)
    return index


INSTRUCTOR_INDEX = build_instructor_index()


def find_instructor_matches(question: str) -> list:
    q_lower = question.lower()
    matched_ids: list[str] = []
    for name, section_ids in INSTRUCTOR_INDEX.items():
        if name in q_lower:
            matched_ids.extend(section_ids)
    return list(dict.fromkeys(matched_ids))  # dedupe, preserve order


def build_course_code_index() -> dict:
    # Week 6: exact course-code lookup, same shape as build_instructor_index —
    # built once at startup from metadata already in Chroma, no re-embedding
    # needed since SectionName was already stored. Two key types per section:
    # the full section name ("cs 104l-a") and its base course code with the
    # section letter stripped ("cs 104l"), so a bare-code question like
    # "CS 104" correctly returns every section of that course, not just one.
    all_rows = collection.get(include=["metadatas"])
    index: dict[str, list[str]] = {}
    for section_id, metadata in zip(all_rows["ids"], all_rows["metadatas"]):
        section_name = metadata.get("SectionName", "")
        if not section_name:
            continue
        full = section_name.lower()
        index.setdefault(full, []).append(section_id)
        if "-" in full:
            base = full.rsplit("-", 1)[0].strip()
            index.setdefault(base, []).append(section_id)
    return index


COURSE_CODE_INDEX = build_course_code_index()


def find_course_code_matches(question: str) -> list:
    q_lower = question.lower()
    candidates = [key for key in COURSE_CODE_INDEX if key in q_lower]

    # Real gap from the golden dataset (edge-06): "CS 104 lab sections"
    # never contains the literal string "104l" — the L suffix is
    # data-internal shorthand for lab sections, not something a student
    # would type. If the question says "lab" and a bare code like "cs 104"
    # matched, also check whether the corresponding "cs 104l" family exists
    # and route there instead.
    if "lab" in q_lower:
        for key in list(candidates):
            lab_key = key + "l"
            if lab_key in COURSE_CODE_INDEX and lab_key not in candidates:
                candidates.append(lab_key)

    # Prefer the most specific match: if both "chem 101-a" and "chem 101"
    # matched, the bare code is just a substring of the full name the
    # student actually typed, not an independent reference to the whole
    # course family — drop it so "CHEM 101-A" doesn't pull in every CHEM 101
    # section.
    candidates.sort(key=len, reverse=True)
    accepted: list[str] = []
    for key in candidates:
        if any(key in longer for longer in accepted):
            continue
        accepted.append(key)

    matched_ids: list[str] = []
    for key in accepted:
        matched_ids.extend(COURSE_CODE_INDEX[key])
    return list(dict.fromkeys(matched_ids))  # dedupe, preserve order


class Question(BaseModel):
    question: str


def embed_question(text: str) -> list:
    result = client.models.embed_content(model=EMBED_MODEL, contents=text)
    return result.embeddings[0].values


def format_section(metadata: dict) -> str:
    return (
        f"{metadata.get('SectionName', '?')} | {metadata.get('SectionTitle', '?')} | "
        f"{metadata.get('Instructors', 'TBA')} | "
        f"{metadata.get('MeetingPatterns', 'no meeting time listed')}\n"
        f"  Description: {metadata.get('CourseDescription', 'No description available.')}"
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(q: Question):
    # Week 2: pure semantic similarity over title+description text.
    # Week 3: instructor-name queries are now handled correctly (see
    # find_instructor_matches) since exact instructor strings aren't part
    # of the embedded text and semantic search alone missed them.
    # Week 6: same gap, different field — exact course-code queries
    # ("CHEM 101-A", "CS 104 lab sections") competed on embedding
    # similarity like everything else and could lose to a more generic
    # semantic match (see find_course_code_matches).
    # Still open: exact meeting-day/time queries ("classes on Monday
    # afternoon") — parsing natural-language day/time references is a
    # fuzzier problem than exact-string matching and is deliberately out
    # of scope for this pass.
    instructor_matches = find_instructor_matches(q.question)
    course_code_matches = find_course_code_matches(q.question)
    exact_matches = list(dict.fromkeys(instructor_matches + course_code_matches))

    query_vector = embed_question(q.question)
    semantic_results = collection.query(query_embeddings=[query_vector], n_results=TOP_K)
    semantic_ids = semantic_results["ids"][0]
    semantic_metadatas = semantic_results["metadatas"][0]

    if exact_matches:
        exact = collection.get(ids=exact_matches, include=["metadatas"])
        retrieved = list(exact["metadatas"])
        exact_id_set = set(exact_matches)
        for section_id, metadata in zip(semantic_ids, semantic_metadatas):
            if section_id not in exact_id_set and len(retrieved) < TOP_K:
                retrieved.append(metadata)
        print(
            f"--- HYBRID: {len(instructor_matches)} instructor match(es), "
            f"{len(course_code_matches)} course-code match(es), "
            f"{len(retrieved)} total sections ---"
        )
    else:
        retrieved = semantic_metadatas

    catalog = "\n\n".join(format_section(m) for m in retrieved)

    prompt = (
        "You are a friendly course advisor for Calvin University.\n"
        "Answer the student's question using ONLY the course sections below.\n"
        "Each entry is: section name | title | instructor | meeting time, "
        "followed by its description.\n\n"
        "Respond in plain conversational text only. Do not use markdown — "
        "no asterisks, no bold, no headers, no bullet points. Write course "
        "listings as plain sentences or simple dashed lines instead.\n\n"
        "Respond in plain conversational text with one exception: wrap ONLY "
        "the course code and title (e.g. **CS 106-A | Introduction to "
        "Scientific Computation**) in double asterisks for bold. Do not bold "
        "or apply any markdown to the instructor, meeting time, description, "
        "or any other text. Do not use markdown headers or bullet points.\n\n"
        f"RELEVANT SECTIONS:\n{catalog}\n\n"
        f"STUDENT QUESTION: {q.question}"
    )

    print(
        f"--- PROMPT SENT TO GEMINI: {len(prompt)} characters, "
        f"{len(retrieved)} sections retrieved ---"
    )

    response = client.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
    )
    return {"answer": response.text}
