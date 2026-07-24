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
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Loaded once at startup, not per-request — Sections.json itself is no longer
# needed here at all. Everything /ask needs (title, instructor, meeting time,
# description) now lives in the Chroma index built by build_index.py.
chroma = chromadb.PersistentClient(path=INDEX_PATH)
collection = chroma.get_or_create_collection(name=COLLECTION_NAME, embedding_function=None)


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
    # Known limitation: retrieval is pure semantic similarity over
    # title+description text. Structured lookups (exact instructor name,
    # exact meeting day/time) aren't reliable, since those fields aren't
    # part of what's embedded — verified during Week 2 testing (e.g. an
    # instructor-name query missed a section that literally matched).
    # Content/topic questions are unaffected. See README for the planned
    # hybrid-retrieval fix.
    query_vector = embed_question(q.question)
    results = collection.query(query_embeddings=[query_vector], n_results=TOP_K)
    retrieved = results["metadatas"][0]

    catalog = "\n\n".join(format_section(m) for m in retrieved)

    prompt = (
        "You are a friendly course advisor for Calvin University.\n"
        "Answer the student's question using ONLY the course sections below.\n"
        "Each entry is: section name | title | instructor | meeting time, "
        "followed by its description.\n\n"
        f"RELEVANT SECTIONS:\n{catalog}\n\n"
        f"STUDENT QUESTION: {q.question}"
    )

    print(
        f"--- PROMPT SENT TO GEMINI: {len(prompt)} characters, "
        f"{TOP_K} sections retrieved (was ~108,000 chars for the full catalog) ---"
    )

    response = client.models.generate_content(
        model=CHAT_MODEL,
        contents=prompt,
    )
    return {"answer": response.text}
