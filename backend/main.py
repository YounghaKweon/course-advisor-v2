import json
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from pydantic import BaseModel

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

with open("Sections.json", encoding="utf-8") as f:
    courses = json.load(f)

def format_course(c):
    return (
        f"{c.get('SectionName', '?')} | {c.get('SectionTitle', '?')} | "
        f"{c.get('Instructors', 'TBA')} | {c.get('MeetingPatterns', 'no meeting time listed')}"
    )

CATALOG = "\n".join(format_course(c) for c in courses)

class Question(BaseModel):
    question: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ask")
def ask(q: Question):
    prompt = (
        "You are a friendly course advisor for Calvin University.\n"
        "Answer the student's question using ONLY the course catalog below.\n"
        "Each catalog line is: section name | title | instructor | meeting time.\n\n"
        f"CATALOG:\n{CATALOG}\n\n"
        f"STUDENT QUESTION: {q.question}"
    )

    print(f"--- PROMPT SENT TO GEMINI: {len(prompt)} characters ---")
    print(prompt[:500])
    print("--- (rest hidden, but ALL of it was sent) ---")

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
    )
    return {"answer": response.text}
