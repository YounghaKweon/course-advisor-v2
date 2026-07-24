"""
Week 2, Step 2 — build the real Chroma index over all sections.

Embeds title + description for every section in Sections.json (the same
title-prepend fix embedding_demo.py already validated) and stores the
vectors in a local, persistent Chroma collection at ./chroma_index.

Resumable: re-running this script skips sections already in the index, so
hitting the free tier's daily embedding cap partway through and continuing
tomorrow is safe and doesn't re-embed (or re-spend quota on) finished work.
Pass --rebuild to wipe the index and start over from scratch instead.

Run from backend/ (same venv as always):
    python build_index.py
    python build_index.py --rebuild
"""
import argparse
import json
import os
import time

import chromadb
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL = "gemini-embedding-001"
BATCH_SIZE = 20  # texts per embed_content call
SLEEP_BETWEEN_BATCHES = 15  # seconds; keeps us under the free tier's 100/min cap
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 65  # the API itself reports ~50-60s before the quota resets
INDEX_PATH = "./chroma_index"
COLLECTION_NAME = "sections"


def load_sections(path="Sections.json"):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    # Sections.json has real data-quality issues, same category as the AI
    # course description trap: one row is a genuinely malformed record
    # (only a CourseLevel field, nothing else — not a real course), and one
    # section ("CORE 100-37") is listed twice with an identical
    # Section_RefID. Both would break Chroma's add() (ids must be unique
    # per call) if left in, so they're filtered here rather than silently
    # crashing partway through 1,021 rows.
    seen_ids = set()
    sections = []
    malformed = 0
    duplicates = 0
    for row in raw:
        ref_id = row.get("Section_RefID", "")
        title = row.get("SectionTitle", "").strip()
        if not ref_id or not title:
            malformed += 1
            continue
        if ref_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(ref_id)
        sections.append(row)

    print(
        f"Loaded {len(raw)} rows -> {len(sections)} to embed "
        f"({malformed} malformed row(s) skipped, {duplicates} exact duplicate(s) dropped)."
    )
    return sections


def embed_text_for(section: dict) -> str:
    title = section.get("SectionTitle", "").strip()
    description = section.get("CourseDescription", "").strip()
    # Title first: some descriptions (e.g. "Special Topics: Human-Centered
    # AI") are generic boilerplate that never mentions the actual subject.
    return f"{title}. {description}".strip()


def embed_batch(texts: list) -> list:
    for attempt in range(MAX_RETRIES):
        try:
            result = client.models.embed_content(model=MODEL, contents=texts)
            return [e.values for e in result.embeddings]
        except Exception as e:
            print(f"  embed_content failed ({e}); waiting {RETRY_WAIT_SECONDS}s for quota to reset...")
            time.sleep(RETRY_WAIT_SECONDS)
    raise RuntimeError(f"Failed to embed batch after {MAX_RETRIES} attempts.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Wipe the existing index and re-embed everything from scratch.",
    )
    args = parser.parse_args()

    sections = load_sections()

    chroma = chromadb.PersistentClient(path=INDEX_PATH)
    existing_names = [c.name for c in chroma.list_collections()]

    if args.rebuild and COLLECTION_NAME in existing_names:
        chroma.delete_collection(COLLECTION_NAME)
        existing_names.remove(COLLECTION_NAME)

    collection = chroma.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=None,  # we supply embeddings ourselves
        metadata={"hnsw:space": "cosine"},  # matches embedding_demo.py's metric
    )

    # Resume support: skip sections already embedded in a prior run. The free
    # tier's daily embedding cap (1,000 items/day) is lower than our 1,019
    # sections, so a single run may not be able to finish in one day — this
    # is what makes re-running tomorrow pick up where it left off instead of
    # re-spending quota on work that's already done.
    already_done = set(collection.get(include=[])["ids"])
    remaining = [s for s in sections if s["Section_RefID"] not in already_done]
    print(
        f"{len(already_done)} already indexed, {len(remaining)} remaining to embed."
    )

    if not remaining:
        print(f"Nothing to do. {collection.count()} sections indexed at {INDEX_PATH}/")
        return

    for start in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[start : start + BATCH_SIZE]
        texts = [embed_text_for(s) for s in batch]
        vectors = embed_batch(texts)

        collection.add(
            ids=[s["Section_RefID"] for s in batch],
            embeddings=vectors,
            documents=texts,
            metadatas=[
                {
                    "SectionName": s.get("SectionName", ""),
                    "SectionTitle": s.get("SectionTitle", ""),
                    "Instructors": s.get("Instructors", "TBA"),
                    "MeetingPatterns": s.get(
                        "MeetingPatterns", "no meeting time listed"
                    ),
                    "CourseDescription": s.get("CourseDescription", ""),
                }
                for s in batch
            ],
        )
        print(f"  embedded {min(start + BATCH_SIZE, len(remaining))}/{len(remaining)}")

        if start + BATCH_SIZE < len(remaining):
            time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"Done. {collection.count()} sections indexed at {INDEX_PATH}/")


if __name__ == "__main__":
    main()
