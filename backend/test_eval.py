"""
Week 4 — automated eval harness.

Runs every entry in golden_dataset.json through the real retrieval +
generation pipeline (same functions main.py uses) and scores two
separate things:

  1. Retrieval quality (deterministic, no LLM call): did the sections
     we know are correct actually come back in the top-K? Measured as
     recall against expected_section_ids.

  2. Answer quality (LLM-as-judge, temperature 0): given the generated
     answer text, does it actually satisfy expected_facts? Judged by
     Gemini against a fixed rubric, not vibes.

`known_limitation` and any entry with "graded": false are run and
logged for visibility but excluded from the pass/fail score — grading
them as failures would just be re-stating a documented gap, not
finding a new one.

Run from backend/ (same venv as always):
    pytest test_eval.py -v -s
    python test_eval.py            # runs directly, writes eval_report.json
"""
import json
import os

import chromadb
import pytest
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

EMBED_MODEL = "gemini-embedding-001"
CHAT_MODEL = "gemini-3.5-flash"
JUDGE_MODEL = "gemini-3.5-flash"
INDEX_PATH = "./chroma_index"
COLLECTION_NAME = "sections"
TOP_K = 15

chroma = chromadb.PersistentClient(path=INDEX_PATH)
collection = chroma.get_or_create_collection(name=COLLECTION_NAME, embedding_function=None)

with open("golden_dataset.json", encoding="utf-8") as f:
    GOLDEN = json.load(f)


# --- same instructor-index + hybrid logic as main.py, kept in sync by hand ---
# (imported, not copy-pasted, if you refactor main.py to expose these as a
# module rather than inline in the FastAPI app — worth doing before Week 5)
def build_instructor_index() -> dict:
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
    return list(dict.fromkeys(matched_ids))


import re
import time


def call_with_retry(fn, *args, max_retries=8, **kwargs):
    """Retry on 429 RESOURCE_EXHAUSTED, honoring the API's own retryDelay
    when it's present. Per-day quota errors are NOT retried — waiting a
    minute doesn't fix a daily cap, so we bail immediately with a clear
    message instead of burning ~8 minutes doing nothing."""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "503" in msg or "UNAVAILABLE" in msg:
                wait = min(10 * (attempt + 1), 60)
                print(f"  503 (server overloaded), waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait)
                continue
            if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
                raise
            quota_match = re.search(r"quotaId['\"]?:\s*['\"]?([A-Za-z\-]+)", msg)
            quota_id = quota_match.group(1) if quota_match else "unknown"
            print(f"  429 hit -- quotaId: {quota_id}")
            if "PerDay" in quota_id or "PerProjectPerDay" in quota_id:
                raise RuntimeError(
                    f"Daily quota hit ({quota_id}) -- retrying won't help within "
                    f"this run. Prior results already saved; try again after reset."
                )
            match = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)", msg)
            wait = int(match.group(1)) + 3 if match else 20 * (attempt + 1)
            print(f"  Rate limited (per-minute), waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
            time.sleep(wait)
    raise RuntimeError(f"Still rate-limited after {max_retries} retries — giving up for now.")


def embed_question(text: str) -> list:
    result = call_with_retry(client.models.embed_content, model=EMBED_MODEL, contents=text)
    return result.embeddings[0].values


def format_section(metadata: dict) -> str:
    return (
        f"{metadata.get('SectionName', '?')} | {metadata.get('SectionTitle', '?')} | "
        f"{metadata.get('Instructors', 'TBA')} | "
        f"{metadata.get('MeetingPatterns', 'no meeting time listed')}\n"
        f"  Description: {metadata.get('CourseDescription', 'No description available.')}"
    )


def run_pipeline(question: str) -> tuple[list[str], str, str]:
    """Mirrors /ask in main.py. Returns (retrieved_section_ids, answer_text, catalog_text)."""
    instructor_matches = find_instructor_matches(question)
    query_vector = embed_question(question)
    semantic_results = collection.query(query_embeddings=[query_vector], n_results=TOP_K)
    semantic_ids = semantic_results["ids"][0]
    semantic_metadatas = semantic_results["metadatas"][0]

    if instructor_matches:
        exact = collection.get(ids=instructor_matches, include=["metadatas"])
        retrieved_ids = list(exact["ids"])
        retrieved_meta = list(exact["metadatas"])
        exact_id_set = set(instructor_matches)
        for sid, meta in zip(semantic_ids, semantic_metadatas):
            if sid not in exact_id_set and len(retrieved_meta) < TOP_K:
                retrieved_ids.append(sid)
                retrieved_meta.append(meta)
    else:
        retrieved_ids = list(semantic_ids)
        retrieved_meta = semantic_metadatas

    catalog = "\n\n".join(format_section(m) for m in retrieved_meta)
    prompt = (
        "You are a friendly course advisor for Calvin University.\n"
        "Answer the student's question using ONLY the course sections below.\n"
        "Each entry is: section name | title | instructor | meeting time, "
        "followed by its description.\n\n"
        f"RELEVANT SECTIONS:\n{catalog}\n\n"
        f"STUDENT QUESTION: {question}"
    )
    response = call_with_retry(client.models.generate_content, model=CHAT_MODEL, contents=prompt)
    return retrieved_ids, response.text, catalog


def score_retrieval(retrieved_ids: list[str], expected_ids: list[str]) -> dict:
    """Recall against known-correct sections. Deterministic, no LLM call."""
    if not expected_ids:
        return {"applicable": False, "recall": None}
    hit = sum(1 for eid in expected_ids if eid in retrieved_ids)
    return {"applicable": True, "recall": hit / len(expected_ids), "hits": hit, "total": len(expected_ids)}


JUDGE_PROMPT = """You are grading a course-advisor chatbot's answer. Be strict but fair.

The chatbot was told to act as "a friendly course advisor for Calvin
University." It referring to itself that way, greeting the student, or
using friendly framing/tone is NOT a claim that needs support from the
retrieved data below — don't grade that as fabrication. Only fact-check
claims about specific courses, sections, instructors, descriptions, or
meeting times against the retrieved data.

STUDENT QUESTION: {question}

RETRIEVED COURSE DATA (the only source of COURSE FACTS the chatbot was
allowed to use — this is the full context it had access to):
{catalog}

FACTS THE ANSWER MUST AT MINIMUM INCLUDE (the answer may correctly include
additional accurate details pulled from the retrieved data above — that is
expected behavior, NOT fabrication):
{facts}

CHATBOT'S ANSWER:
{answer}

Grade FAIL only if:
- the answer states a COURSE FACT (course number, title, instructor,
  description content, meeting time, etc.) that contradicts or is not
  supported by the RETRIEVED COURSE DATA above (this is real fabrication), OR
- the answer omits one of the required facts listed above.

Do NOT fail the answer for organizational framing (mentioning Calvin
University, greetings, friendly tone) or for including extra correct
course details drawn from the retrieved data that aren't in the
required-facts list — both are normal, expected behavior, not defects.

Respond with EXACTLY one line in this format, nothing else:
VERDICT: PASS or FAIL | REASON: <one short sentence>"""


def judge_answer(question: str, answer: str, expected_facts: list[str], catalog: str) -> dict:
    if not expected_facts:
        return {"applicable": False, "verdict": None, "reason": None}
    facts_str = "\n".join(f"- {f}" for f in expected_facts)
    prompt = JUDGE_PROMPT.format(question=question, catalog=catalog, facts=facts_str, answer=answer)
    response = call_with_retry(
        client.models.generate_content,
        model=JUDGE_MODEL,
        contents=prompt,
        config={"temperature": 0},
    )
    line = response.text.strip()
    verdict = "PASS" if "VERDICT: PASS" in line else "FAIL"
    reason = line.split("REASON:", 1)[-1].strip() if "REASON:" in line else line
    return {"applicable": True, "verdict": verdict, "reason": reason}


@pytest.mark.parametrize("entry", GOLDEN, ids=[e["id"] for e in GOLDEN])
def test_golden_entry(entry):
    retrieved_ids, answer, catalog = run_pipeline(entry["question"])
    retrieval = score_retrieval(retrieved_ids, entry["expected_section_ids"])
    judged = judge_answer(entry["question"], answer, entry["expected_facts"], catalog)

    print(f"\n[{entry['id']}] ({entry['category']}) {entry['question']}")
    print(f"  retrieval: {retrieval}")
    print(f"  judge: {judged}")
    print(f"  answer: {answer[:200]}")

    if not entry["graded"]:
        pytest.skip(f"{entry['id']} tracked but not graded ({entry['notes']})")

    if retrieval["applicable"]:
        assert retrieval["recall"] == 1.0, (
            f"Retrieval missed expected section(s) for '{entry['question']}': "
            f"{retrieval['hits']}/{retrieval['total']} found"
        )
    if judged["applicable"]:
        assert judged["verdict"] == "PASS", (
            f"Judge failed answer for '{entry['question']}': {judged['reason']}"
        )


REPORT_PATH = "eval_report.json"


if __name__ == "__main__":
    # Resume support: a 429 mid-run (daily quota) shouldn't cost you the
    # entries that already succeeded. Load any prior report, skip what's
    # already in it, and only spend quota on what's left.
    results = []
    done_ids = set()
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH, encoding="utf-8") as f:
            results = json.load(f)
        done_ids = {r["id"] for r in results}
        print(f"Resuming: {len(done_ids)} entries already in {REPORT_PATH}, skipping those.")

    remaining = [e for e in GOLDEN if e["id"] not in done_ids]
    for entry in remaining:
        try:
            retrieved_ids, answer, catalog = run_pipeline(entry["question"])
            retrieval = score_retrieval(retrieved_ids, entry["expected_section_ids"])
            judged = judge_answer(entry["question"], answer, entry["expected_facts"], catalog)
        except Exception as e:
            print(f"[{entry['id']}] ERROR: {e} -- stopping, prior results already saved.")
            break

        results.append({
            "id": entry["id"], "category": entry["category"], "graded": entry["graded"],
            "question": entry["question"], "answer": answer,
            "retrieval": retrieval, "judge": judged,
        })
        print(f"[{entry['id']}] retrieval={retrieval.get('recall')} judge={judged.get('verdict')}")

        # Save after every entry, not just at the end, so a crash or 429
        # doesn't lose progress already made this run.
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

    graded = [r for r in results if r["graded"]]
    retrieval_scores = [r["retrieval"]["recall"] for r in graded if r["retrieval"]["applicable"]]
    judge_scores = [r["judge"]["verdict"] == "PASS" for r in graded if r["judge"]["applicable"]]
    print("\n--- SUMMARY (graded entries only) ---")
    print(f"Retrieval recall@{TOP_K}: {sum(retrieval_scores)/len(retrieval_scores):.0%} "
          f"({len(retrieval_scores)} applicable entries)")
    print(f"Answer quality (LLM judge): {sum(judge_scores)/len(judge_scores):.0%} "
          f"({len(judge_scores)} applicable entries)")
    print(f"Tracked-not-graded: {len(results) - len(graded)} "
          f"(known_limitation + explicitly ungraded edge cases)")
