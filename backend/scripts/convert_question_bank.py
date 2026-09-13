"""One-off dev tool: converts data/question_bank.csv into data/question_bank.json.

This is NOT used by the running app — app/repositories/question_repository.py
only ever reads question_bank.json. Run this manually whenever
question_bank.csv is updated, then commit the regenerated JSON.

Usage:
    cd backend
    python scripts/convert_question_bank.py
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from app.schemas.question import Question

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "question_bank.csv"
JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"

TAG_DELIMITER = "|"


def _row_to_question_dict(row: dict) -> dict:
    tags_raw = (row.get("tags") or "").strip()
    tags = [t.strip() for t in tags_raw.split(TAG_DELIMITER) if t.strip()] if tags_raw else []

    subtopic = (row.get("subtopic") or "").strip() or None

    return {
        "question_id": (row.get("question_id") or "").strip(),
        "question_text": (row.get("question_text") or "").strip(),
        "topic": (row.get("topic") or "").strip(),
        "subtopic": subtopic,
        "difficulty": (row.get("difficulty") or "").strip().lower(),
        "question_type": (row.get("question_type") or "").strip().lower(),
        "competency": (row.get("competency") or "").strip(),
        "tags": tags,
    }


def convert() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV not found at {CSV_PATH}")

    questions: list[dict] = []
    errors: list[str] = []
    seen_ids: set[str] = set()

    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for line_number, row in enumerate(reader, start=2):  # header is line 1
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
        print("Conversion failed. Fix these rows and re-run:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2)
        f.write("\n")

    print(f"Wrote {len(questions)} questions to {JSON_PATH}")


if __name__ == "__main__":
    convert()