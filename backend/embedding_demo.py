"""
Week 2, Step 1 — see embeddings do their thing before we touch the real pipeline.

Takes 4 real rows from your Sections.json, embeds them with Gemini's
gemini-embedding-001, and prints a similarity matrix so you can see which
courses land close together in vector space.

Run from backend/ (same venv, same .env you already have):
    python embedding_demo.py
"""
import os

import numpy as np
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Title + full CourseDescription, pulled straight from your Sections.json.
# Two CS courses that should cluster, one unrelated course (Nutrition) as
# the control, and one deliberately tricky case (see note in the printout).
SAMPLES = {
    "Data Structures": (
        "Introduction to Data Structures. A continuation of CS 108, CS 106, "
        "or CS 104, using C++ classes to introduce and implement the "
        "elementary data structures including lists, stacks, queues and "
        "trees. Advanced programming techniques such as indirection, "
        "inheritance, and templates are introduced, along with an emphasis "
        "on algorithm analysis, efficiency, and good programming style."
    ),
    "Senior Project in Computing": (
        "Senior Project in Computing. This is the first course of a "
        "two-semester sequence, in which the student will complete a "
        "department-approved computing project. This capstone experience "
        "will give students the opportunity to apply concepts and "
        "techniques learned in the classroom by developing a significant "
        "computing application."
    ),
    "Human-Centered AI": (
        "Special Topics: Human-Centered AI. Advanced study of selected "
        "topics of current interest in computer science. Topics vary by "
        "year. Consult the instructor or the department website for the "
        "specific topic of the current offering."
    ),
    "Nutrition": (
        "Nutrition. This course will provide the student with a basic "
        "understanding of human nutrition. Special emphasis will be placed "
        "on the role of food and nutrients in sustaining optimal health."
    ),
}


def embed(text: str) -> np.ndarray:
    result = client.models.embed_content(model="gemini-embedding-001", contents=text)
    return np.array(result.embeddings[0].values)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


vectors = {name: embed(text) for name, text in SAMPLES.items()}

names = list(vectors)
header = "".join(f"{n[:16]:>18}" for n in names)
print(f"{'':28}{header}")
for a in names:
    row = "".join(f"{cosine(vectors[a], vectors[b]):>18.3f}" for b in names)
    print(f"{a:28}{row}")

print(
    "\nNote: 'Special Topics: Human-Centered AI' is a real trap in your data — "
    "the CourseDescription field is generic special-topics boilerplate and "
    "never actually says 'AI'. If Step 2 embeds CourseDescription alone, this "
    "course won't retrieve for an AI-related question. That's why the text "
    "above prepends the title to the description — worth confirming this "
    "script backs up that fix before we build the real index."
)
