"""One-off dev tool: converts data/question_bank.csv into data/question_bank.json.

This is NOT used by the running app -- app/repositories/question_repository.py
only ever reads question_bank.json. Run it whenever question_bank.csv changes,
then commit both files.

Expected CSV columns (exact header names):
    question_id, question, reference_answer, category, subcategory, difficulty,
    question_type, expected_concepts, evaluation_criteria,
    estimated_time_seconds, tags, review_status, legacy_category, source,
    previous_id

expected_concepts, evaluation_criteria and tags are JSON lists stored in one
CSV cell, e.g.  ["greedy", "no backtracking"].

Mapping:
    question_id            <- question_id (kept as-is, e.g. "SWQ-0001")
    question_text          <- question
    topic                  <- category
    subtopic               <- subcategory
    competency             <- category   (the CSV has no separate competency;
                                          competency state is tracked per category)
    difficulty             <- difficulty, lowercased ("Easy" -> "easy")
    question_type          <- question_type, lowercased
    everything else        <- copied (lists parsed, estimated_time_seconds -> int)

ALL-OR-NOTHING: if any row is invalid the JSON is NOT written, and every
problem is reported so they can be fixed in one pass.

Usage:
    cd backend
    python scripts/convert_question_bank.py
"""

import csv
import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from app.schemas.question import Question

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "question_bank.csv"
JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "question_bank.json"

REQUIRED_COLUMNS = {
    "question_id",
    "question",
    "reference_answer",
    "category",
    "subcategory",
    "difficulty",
    "question_type",
    "expected_concepts",
    "evaluation_criteria",
    "estimated_time_seconds",
    "tags",
    "review_status",
    "legacy_category",
    "source",
    "previous_id",
}


class ConversionError(Exception):
    """Raised with a list of human-readable problems; nothing is written."""

    def __init__(self, problems: List[str]) -> None:
        super().__init__(f"{len(problems)} problem(s) found")
        self.problems = problems


def _text(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def _optional(row: dict, key: str) -> Optional[str]:
    return _text(row, key) or None


def _json_list(row: dict, key: str) -> List[str]:
    raw = _text(row, key)
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{key} is not valid JSON ({exc.msg})") from None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a JSON list of strings")
    return [item.strip() for item in value if item.strip()]


def _optional_int(row: dict, key: str) -> Optional[int]:
    raw = _text(row, key)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{key} must be a whole number, got {raw!r}") from None


def _row_to_question_dict(row: dict) -> dict:
    category = _text(row, "category")
    return {
        "question_id": _text(row, "question_id"),
        "question_text": _text(row, "question"),
        "topic": category,
        "subtopic": _optional(row, "subcategory"),
        "difficulty": _text(row, "difficulty").lower(),
        "question_type": _text(row, "question_type").lower(),
        "competency": category,
        "tags": _json_list(row, "tags"),
        "reference_answer": _optional(row, "reference_answer"),
        "expected_concepts": _json_list(row, "expected_concepts"),
        "evaluation_criteria": _json_list(row, "evaluation_criteria"),
        "estimated_time_seconds": _optional_int(row, "estimated_time_seconds"),
        "review_status": _optional(row, "review_status"),
        "source": _optional(row, "source"),
        "legacy_category": _optional(row, "legacy_category"),
        "previous_id": _optional(row, "previous_id"),
    }


def convert(csv_path: Path = CSV_PATH, json_path: Path = JSON_PATH) -> int:
    """Convert the CSV to JSON. Returns the number of questions written.

    Raises ConversionError (and writes nothing) if the file or any row is invalid.
    """
    if not Path(csv_path).exists():
        raise ConversionError([f"CSV not found at {csv_path}"])

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ConversionError([f"CSV is missing required column(s): {sorted(missing)}"])
        rows = list(reader)

    questions: List[dict] = []
    problems: List[str] = []
    seen_ids = set()

    for line_number, row in enumerate(rows, start=2):  # header is line 1
        label = f"Row {line_number} ({_text(row, 'question_id') or '?'})"
        try:
            question_dict = _row_to_question_dict(row)
            Question(**question_dict)
        except ValueError as exc:  # includes pydantic ValidationError
            detail = str(exc).replace("\n", " ") if isinstance(exc, ValidationError) else str(exc)
            problems.append(f"{label}: {detail}")
            continue

        if question_dict["question_id"] in seen_ids:
            problems.append(f"{label}: duplicate question_id")
            continue
        seen_ids.add(question_dict["question_id"])
        questions.append(question_dict)

    if problems:
        raise ConversionError(problems)

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(questions, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return len(questions)


def main() -> None:
    try:
        count = convert()
    except ConversionError as error:
        print(f"Conversion failed -- nothing was written. {len(error.problems)} problem(s):")
        for problem in error.problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    print(f"Wrote {count} questions to {JSON_PATH}")


if __name__ == "__main__":
    main()