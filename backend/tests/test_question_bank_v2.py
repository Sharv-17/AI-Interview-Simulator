"""Tests for the v2 question bank (SWQ-* questions): new question types, the
review-status serving rule, answer-key protection, and the CSV converter."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.question_repository import question_repository
from app.schemas.interview import DifficultyLevel
from app.schemas.question import Question, QuestionType, ReviewStatus
from app.services.answer_evaluator import evaluate_answer
from app.services.interview_engine import interview_engine
from app.services.question_selector import select_next_question

client = TestClient(app)
BACKEND = Path(__file__).resolve().parent.parent
ANSWER_KEY_FIELDS = ["reference_answer", "expected_concepts", "evaluation_criteria"]


def _load_converter():
    spec = importlib.util.spec_from_file_location(
        "convert_question_bank", BACKEND / "scripts" / "convert_question_bank.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _question(question_type=QuestionType.CONCEPTUAL, review_status=None):
    return Question(
        question_id="T-1",
        question_text="What is a test question?",
        topic="Algorithms",
        difficulty=DifficultyLevel.EASY,
        question_type=question_type,
        competency="Algorithms",
        review_status=review_status,
    )


# ---------------------------------------------------------------------------
# The bank itself
# ---------------------------------------------------------------------------


def test_bank_contains_every_supported_question_type():
    types = {q.question_type for q in question_repository.get_all()}
    assert types == set(QuestionType)


def test_json_bank_matches_the_csv_exactly():
    """Guards against a stale JSON: re-run scripts/convert_question_bank.py after editing the CSV."""
    with open(BACKEND / "data" / "question_bank.csv", encoding="utf-8-sig", newline="") as handle:
        csv_ids = [row["question_id"] for row in csv.DictReader(handle)]
    json_ids = [q.question_id for q in question_repository.get_all()]
    assert json_ids == csv_ids


def test_every_question_carries_its_rubric_data():
    for q in question_repository.get_all():
        assert q.reference_answer, q.question_id
        assert q.expected_concepts, q.question_id
        assert q.evaluation_criteria, q.question_id
        assert q.estimated_time_seconds and q.estimated_time_seconds > 0, q.question_id
        assert q.review_status is not None, q.question_id


# ---------------------------------------------------------------------------
# Serving rule: only reviewed questions are ever asked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, expected",
    [
        (None, True),
        (ReviewStatus.REVIEWED, True),
        (ReviewStatus.NEEDS_MANUAL_REVIEW, False),
        (ReviewStatus.REQUIRES_CODING_EVALUATION, False),
    ],
)
def test_is_servable_rules(status, expected):
    assert _question(review_status=status).is_servable is expected


def test_selector_never_serves_an_unreviewed_question_in_any_topic():
    topics = sorted({q.topic for q in question_repository.get_all()})
    assert len(topics) >= 20
    for topic in topics:
        servable_in_topic = [q for q in question_repository.get_by_topic(topic) if q.is_servable]
        asked, served = [], []
        while True:
            q = select_next_question(topic, DifficultyLevel.MEDIUM, asked)
            if q is None:
                break
            assert q.is_servable, f"{q.question_id} ({q.review_status}) was served"
            assert q.question_type != QuestionType.CODING
            asked.append(q.question_id)
            served.append(q)
        # Everything servable is reachable, nothing else.
        assert {q.question_id for q in served} == {q.question_id for q in servable_in_topic}


def test_unreviewed_questions_stay_in_the_bank_and_are_retrievable_by_id():
    unreviewed = next(q for q in question_repository.get_all() if not q.is_servable)
    assert question_repository.get_by_id(unreviewed.question_id) == unreviewed


def test_a_full_interview_only_ever_asks_servable_questions():
    interview = client.post(
        "/interview/start",
        json={"topic": "System Design", "difficulty": "hard", "question_count": 20},
    ).json()
    iid = interview["interview_id"]
    asked = []
    current = interview["current_question_id"]
    while current is not None:
        question = question_repository.get_by_id(current)
        assert question.is_servable
        asked.append(current)
        answer = client.post(
            f"/interview/{iid}/answer",
            json={"question_id": current, "answer_text": "A detailed answer covering the main ideas."},
        )
        assert answer.status_code == 200, (current, question.question_type, answer.text)
        current = client.post(f"/interview/{iid}/next").json()["current_question_id"]
    assert len(asked) == len(set(asked)) == 20
    assert client.get(f"/interview/{iid}").json()["status"] == "completed"


# ---------------------------------------------------------------------------
# Evaluation of every question type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question_type",
    [QuestionType.CONCEPTUAL, QuestionType.SCENARIO, QuestionType.SYSTEM_DESIGN, QuestionType.DEBUGGING],
)
def test_free_text_question_types_are_evaluated_with_the_rubric(question_type):
    evaluation = evaluate_answer(_question(question_type), "A reasonably detailed answer with substance.")
    assert 0 <= evaluation.overall_score <= 10
    assert evaluation.question_type == QuestionType.CONCEPTUAL  # rubric-based evaluation


def test_coding_questions_still_score_zero_without_test_cases():
    """Documents why requires_coding_evaluation questions are never served."""
    evaluation = evaluate_answer(_question(QuestionType.CODING), "def f(): pass")
    assert evaluation.execution_status.value == "skipped"
    assert evaluation.overall_score == 0.0


@pytest.mark.parametrize("question_type", [QuestionType.SCENARIO, QuestionType.SYSTEM_DESIGN, QuestionType.DEBUGGING])
def test_non_conceptual_questions_can_be_answered_through_the_api(question_type):
    target = next(q for q in question_repository.get_all() if q.question_type == question_type and q.is_servable)
    interview = client.post(
        "/interview/start",
        json={"topic": target.topic, "difficulty": target.difficulty.value, "question_count": 3},
    ).json()
    session = interview_engine.get_interview(interview["interview_id"])
    session.current_question_id = target.question_id
    session.asked_question_ids.append(target.question_id)

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": target.question_id, "answer_text": "A reasonably detailed answer with substance."},
    )
    assert response.status_code == 200
    assert response.json()["competency_update"]["questions_attempted"] == 1


# ---------------------------------------------------------------------------
# The answer key must never reach a candidate
# ---------------------------------------------------------------------------


def test_question_list_endpoint_does_not_expose_the_answer_key():
    items = client.get("/questions", params={"topic": "Algorithms"}).json()
    assert items
    for item in items:
        for field in ANSWER_KEY_FIELDS:
            assert field not in item


def test_single_question_endpoint_does_not_expose_the_answer_key():
    question = next(q for q in question_repository.get_all() if q.is_servable)
    body = client.get(f"/questions/{question.question_id}").json()
    assert body["question_text"] == question.question_text
    for field in ANSWER_KEY_FIELDS:
        assert field not in body


# ---------------------------------------------------------------------------
# The converter
# ---------------------------------------------------------------------------

GOOD_ROW = {
    "question_id": "T-0001",
    "question": "What is a greedy algorithm?",
    "reference_answer": "It makes the locally optimal choice at each step.",
    "category": "Algorithms",
    "subcategory": "Algorithmic Techniques",
    "difficulty": "Easy",
    "question_type": "conceptual",
    "expected_concepts": '["locally optimal", "no backtracking"]',
    "evaluation_criteria": '["Accuracy: explains the idea"]',
    "estimated_time_seconds": "60",
    "tags": '["greedy"]',
    "review_status": "reviewed",
    "legacy_category": "Algorithms",
    "source": "original_reviewed",
    "previous_id": "T-0000",
}


def _write_csv(path, rows, columns=None):
    columns = columns or list(GOOD_ROW)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_converter_maps_columns_and_parses_lists(tmp_path):
    converter = _load_converter()
    csv_path, json_path = tmp_path / "bank.csv", tmp_path / "bank.json"
    _write_csv(csv_path, [GOOD_ROW])

    assert converter.convert(csv_path, json_path) == 1
    (entry,) = json.loads(json_path.read_text(encoding="utf-8"))
    assert entry["question_text"] == "What is a greedy algorithm?"
    assert entry["topic"] == "Algorithms" and entry["competency"] == "Algorithms"
    assert entry["subtopic"] == "Algorithmic Techniques"
    assert entry["difficulty"] == "easy"
    assert entry["expected_concepts"] == ["locally optimal", "no backtracking"]
    assert entry["tags"] == ["greedy"]
    assert entry["estimated_time_seconds"] == 60
    Question(**entry)  # the output is a valid Question


@pytest.mark.parametrize(
    "overrides, expected_fragment",
    [
        ({"tags": "not json"}, "tags is not valid JSON"),
        ({"expected_concepts": '{"a": 1}'}, "must be a JSON list of strings"),
        ({"difficulty": "Impossible"}, "difficulty"),
        ({"question_type": "essay"}, "question_type"),
        ({"estimated_time_seconds": "soon"}, "must be a whole number"),
        ({"review_status": "maybe"}, "review_status"),
        ({"question": "   "}, "question_text"),
    ],
)
def test_converter_rejects_bad_rows_and_writes_nothing(tmp_path, overrides, expected_fragment):
    converter = _load_converter()
    csv_path, json_path = tmp_path / "bank.csv", tmp_path / "bank.json"
    _write_csv(csv_path, [{**GOOD_ROW, **overrides}])

    with pytest.raises(converter.ConversionError) as caught:
        converter.convert(csv_path, json_path)
    assert expected_fragment in " ".join(caught.value.problems)
    assert not json_path.exists()


def test_converter_rejects_duplicate_ids_and_reports_every_problem(tmp_path):
    converter = _load_converter()
    csv_path, json_path = tmp_path / "bank.csv", tmp_path / "bank.json"
    _write_csv(csv_path, [GOOD_ROW, GOOD_ROW, {**GOOD_ROW, "question_id": "T-0002", "tags": "bad"}])

    with pytest.raises(converter.ConversionError) as caught:
        converter.convert(csv_path, json_path)
    assert len(caught.value.problems) == 2
    assert any("duplicate" in problem for problem in caught.value.problems)
    assert not json_path.exists()


def test_converter_rejects_missing_columns(tmp_path):
    converter = _load_converter()
    csv_path = tmp_path / "bank.csv"
    _write_csv(csv_path, [{"question_id": "T-1", "question": "x"}], columns=["question_id", "question"])
    with pytest.raises(converter.ConversionError) as caught:
        converter.convert(csv_path, tmp_path / "bank.json")
    assert "missing required column" in caught.value.problems[0]