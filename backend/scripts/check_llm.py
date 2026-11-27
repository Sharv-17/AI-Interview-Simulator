"""Diagnose AI scoring: makes the same request the backend makes and prints the real reason it fails.

Run from the backend folder, with the virtual environment active:
    python scripts/check_llm.py

It reads backend/.env. It never prints your API key.
"""

import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("python-dotenv is missing. Run: pip install -r requirements.txt")

env_file = BACKEND_DIR / ".env"
if not env_file.exists():
    sys.exit(f"No .env file found at {env_file}")
load_dotenv(env_file, override=True)

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.repositories.question_repository import question_repository  # noqa: E402
from app.services.rubric_evaluator import RubricOutput, build_request  # noqa: E402

print("1. Settings read from .env")
print(f"   LLM_PROVIDER    = {config.LLM_PROVIDER or '(empty)'}")
print(f"   OPENAI_BASE_URL = {config.OPENAI_BASE_URL}")
print(f"   OPENAI_MODEL    = {config.OPENAI_MODEL or '(empty)'}")
key = config.OPENAI_API_KEY
print(f"   OPENAI_API_KEY  = {'set, ' + str(len(key)) + ' characters, starts with ' + key[:4] if key else '(empty)'}")
if key != key.strip() or key.startswith(('"', "'")):
    print("   PROBLEM: the key has spaces or quotes around it. Remove them in .env.")

if config.LLM_PROVIDER != "openai_compatible":
    sys.exit("\nPROBLEM: LLM_PROVIDER must be openai_compatible for Groq. Fix .env and run again.")
if not key or not config.OPENAI_MODEL:
    sys.exit("\nPROBLEM: OPENAI_API_KEY or OPENAI_MODEL is empty. Fix .env and run again.")

question = next(q for q in question_repository.get_all() if q.is_servable and q.question_type.value == "conceptual")
request = build_request(question, "An index is a data structure that lets the database find rows quickly without scanning the whole table.")
schema_hint = (
    "Respond with ONE JSON object only, matching exactly this JSON schema "
    f"(no prose, no code fences):\n{json.dumps(request.schema, separators=(',', ':'))}"
)
payload = {
    "model": config.OPENAI_MODEL,
    "messages": [
        {"role": "system", "content": request.system + "\n\n" + schema_hint},
        {"role": "user", "content": request.user},
    ],
    "response_format": {"type": "json_object"},
}

print("\n2. Calling the AI service (same request the backend sends)")
try:
    response = httpx.post(
        config.OPENAI_BASE_URL.rstrip("/") + "/chat/completions",
        headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
        json=payload,
        timeout=config.LLM_TIMEOUT_SECONDS,
    )
except httpx.HTTPError as exc:
    sys.exit(f"   PROBLEM: could not connect: {type(exc).__name__}: {exc}")

print(f"   HTTP status: {response.status_code}")
if response.status_code != 200:
    print("   Service said:", response.text[:1500].replace(key, "[key hidden]"))
    sys.exit("\nPROBLEM: the AI service refused the request. The message above says why.")

content = response.json()["choices"][0]["message"]["content"]
print("\n3. Model reply (first 1500 characters)")
print("  ", content[:1500])

print("\n4. Checking the reply against the backend's rules")
try:
    RubricOutput.model_validate(json.loads(content))
except Exception as exc:  # noqa: BLE001
    print(f"   PROBLEM: the reply does not match what the backend expects:\n{exc}")
    sys.exit(1)
print("   OK. Scoring works. If the website still says 'not scored', restart the backend.")
