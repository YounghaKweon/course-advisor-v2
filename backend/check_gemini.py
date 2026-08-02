"""Isolated check: is gemini-3.5-flash actually reachable right now,
independent of the eval harness's prompt size/content?
Run from backend/ with venv active: python check_gemini.py
"""
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Trying a minimal request...")
try:
    r = client.models.generate_content(model="gemini-3.5-flash", contents="Say hi in 3 words.")
    print("SUCCESS:", r.text)
except Exception as e:
    print("FAILED:", e)
