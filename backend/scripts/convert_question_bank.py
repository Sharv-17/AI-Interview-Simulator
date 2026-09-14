"""One-off dev tool: converts data/question_bank.csv into data/question_bank.json.

This is NOT used by the running app — app/repositories/question_repository.py
only ever reads question_bank.json. Run this manually whenever
question_bank.csv is updated, then commit the regenerated JSON.

Expected CSV columns (exact header names):
    Question Number, Question, Answer, Category, Difficulty

Mapping decisions (the source CSV doesn't have separate columns for
these, so they're derived):
    - question_id      <- "q-{Question Number, zero-padded to 4 digits}"
    - question_text    <- Question
    - topic             <- Category
    - competency        <- Category (no finer-grained competency exists in the source)
    - difficulty        <- Difficulty, lowercased ("Medium" -> "medium")
    - question_type     <- always "conceptual" (the source has no field
                            distinguishing conceptual vs. coding questions;
                            change this manually per-row later if needed)
    - tags               <- a single tag: the slugified Category
                            (e.g. "General Programming" -> "general-programming")
    - subtopic          <- always None (no source column)
    - reference_answer  <- Answer

Usage:
    cd backend
    python scripts/convert_question_bank.py
"""

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from app.schemas.question import Question

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "question_bank.csv"
JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"

REQUIRED_COLUMNS = {"Question Number", "Question", "Answer", "Category", "Difficulty"}


def _slugify(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _row_to_question_dict(row: dict) -> dict:
    number = (row.get("Question Number") or "").strip()
    question_id = f"q-{int(number):04d}" if number.isdigit() else f"q-{number}"

    category = (row.get("Category") or "").strip()
    difficulty = (row.get("Difficulty") or "").strip().lower()
    answer = (row.get("Answer") or "").strip() or None

    return {
        "question_id": question_id,
        "question_text": (row.get("Question") or "").strip(),
        "topic": category,
        "subtopic": None,
        "difficulty": difficulty,
        "question_type": "conceptual",
        "competency": category,
        "tags": [_slugify(category)] if category else [],
        "reference_answer": answer,
    }


def convert() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV not found at {CSV_PATH}")

    with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"CSV is missing required column(s): {sorted(missing)}")
        rows = list(reader)

    questions: list[dict] = []
    errors: list[str] = []
    seen_ids: set[str] = set()

    for line_number, row in enumerate(rows, start=2):  # header is line 1
        question_dict = _row_to_question_dict(row)
        try:
            Question(**question_dict)  # validates; raises on bad data
        except ValidationError as exc:
            errors.append(f"Row {line_number} ({question_dict.get('question_id') or '?'}): {exc}")
            continue

        if question_dict["question_id"] in seen_ids:
            errors.append(f"Row {line_number}: duplicate question_id '{question_dict['question_id']}'")
            continue

        seen_ids.add(question_dict["question_id"])
        questions.append(question_dict)

    if errors:
        print(f"Conversion found {len(errors)} problem row(s):")
        for error in errors:
            print(f"  - {error}")
        if not questions:
            raise SystemExit(1)
        print(f"Continuing with the {len(questions)} valid row(s).")

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2)
        f.write("\n")

    print(f"Wrote {len(questions)} questions to {JSON_PATH}")


if __name__ == "__main__":
    convert()