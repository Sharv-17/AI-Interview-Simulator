import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.repositories.question_repository import question_repository
from app.schemas.evaluation import CodingEvaluation, ConceptualEvaluation, ExecutionStatus
from app.schemas.question import QuestionType
from app.services.coding_evaluator import CodeCheck, evaluate_coding_answer
from app.services.conceptual_evaluator import evaluate_conceptual_answer
from app.services.evaluation_errors import EvaluationError
from app.services.llm_client import LLMClient, LLMConceptualScores, MockLLMClient

client = TestClient(app)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_conceptual_evaluation_schema_accepts_valid_scores():
    evaluation = ConceptualEvaluation(
        question_id="python-001",
        overall_score=8.0,
        technical_score=8,
        relevance_score=9,
        completeness_score=7,
        clarity_score=8,
        conceptual_understanding_score=8,
        feedback="Solid answer.",
    )
    assert evaluation.question_type == QuestionType.CONCEPTUAL


def test_conceptual_evaluation_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        ConceptualEvaluation(
            question_id="python-001",
            overall_score=8.0,
            technical_score=11,  # out of 0-10 range
            relevance_score=9,
            completeness_score=7,
            clarity_score=8,
            conceptual_understanding_score=8,
            feedback="Invalid.",
        )


def test_coding_evaluation_rejects_inconsistent_test_counts():
    with pytest.raises(ValidationError):
        CodingEvaluation(
            question_id="python-004",
            overall_score=5.0,
            tests_total=5,
            tests_passed=2,
            tests_failed=2,  # 2 + 2 != 5
            execution_status=ExecutionStatus.COMPLETED,
            feedback="Inconsistent.",
        )


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------


def test_mock_llm_client_returns_deterministic_results():
    mock = MockLLMClient()
    first = mock.evaluate_conceptual_answer(
        question_text="What is a list?",
        candidate_answer="A list is a mutable, ordered collection of items in Python.",
    )
    second = mock.evaluate_conceptual_answer(
        question_text="What is a list?",
        candidate_answer="A list is a mutable, ordered collection of items in Python.",
    )
    assert first == second


# ---------------------------------------------------------------------------
# Conceptual evaluator
# ---------------------------------------------------------------------------


def test_conceptual_evaluator_computes_overall_score_as_mean():
    question = question_repository.get_by_id("python-001")
    assert question is not None

    evaluation = evaluate_conceptual_answer(
        question=question,
        answer_text="A list is mutable and ordered; a tuple is immutable and ordered.",
        llm_client=MockLLMClient(),
    )

    expected_scores = [
        evaluation.technical_score,
        evaluation.relevance_score,
        evaluation.completeness_score,
        evaluation.clarity_score,
        evaluation.conceptual_understanding_score,
    ]
    assert evaluation.overall_score == round(sum(expected_scores) / len(expected_scores), 1)


class _BrokenLLMClient(LLMClient):
    """Test double that always fails, to exercise the error path safely."""

    def evaluate_conceptual_answer(self, question_text, candidate_answer, reference_answer=None):
        raise RuntimeError("simulated provider failure")


def test_conceptual_evaluator_wraps_llm_failures_safely():
    question = question_repository.get_by_id("python-001")
    assert question is not None

    with pytest.raises(EvaluationError):
        evaluate_conceptual_answer(
            question=question,
            answer_text="Some answer.",
            llm_client=_BrokenLLMClient(),
        )


# ---------------------------------------------------------------------------
# Coding evaluator
# ---------------------------------------------------------------------------


def test_coding_evaluator_scores_based_on_test_cases_passed():
    question = question_repository.get_by_id("python-004")
    assert question is not None

    test_cases = [
        CodeCheck(name="defines a function", keyword="def"),
        CodeCheck(name="uses a loop", keyword="for"),
    ]
    evaluation = evaluate_coding_answer(
        question=question,
        answer_text="def flatten(items):\n    for item in items:\n        pass",
        test_cases=test_cases,
    )

    assert evaluation.tests_total == 2
    assert evaluation.tests_passed == 2
    assert evaluation.tests_failed == 0
    assert evaluation.overall_score == 10.0
    assert evaluation.execution_status == ExecutionStatus.COMPLETED


def test_coding_evaluator_with_no_test_cases_is_skipped_not_faked():
    question = question_repository.get_by_id("python-004")
    assert question is not None

    evaluation = evaluate_coding_answer(question=question, answer_text="def flatten(x): pass", test_cases=[])

    assert evaluation.tests_total == 0
    assert evaluation.overall_score == 0.0
    assert evaluation.execution_status == ExecutionStatus.SKIPPED


# ---------------------------------------------------------------------------
# Answer submission API
# ---------------------------------------------------------------------------


def test_answer_submission_succeeds_for_a_conceptual_question():
    start_response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "easy", "question_count": 3},
    )
    interview = start_response.json()
    question_id = interview["current_question_id"]
    assert question_id is not None

    answer_response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": question_id,
            "answer_text": "A list is mutable and ordered; a tuple is immutable and ordered.",
        },
    )

    assert answer_response.status_code == 200
    body = answer_response.json()
    assert body["question_id"] == question_id
    assert body["evaluation"]["question_type"] == "conceptual"
    assert 0 <= body["evaluation"]["overall_score"] <= 10


def test_answer_submission_succeeds_for_a_coding_question():
    # topic=Python, difficulty=hard deterministically selects python-003 (coding, hard).
    start_response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "hard", "question_count": 3},
    )
    interview = start_response.json()
    question_id = interview["current_question_id"]
    assert question_id == "python-003"

    answer_response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": question_id,
            "answer_text": "def memoize(fn):\n    cache = {}\n    return fn",
        },
    )

    assert answer_response.status_code == 200
    body = answer_response.json()
    assert body["evaluation"]["question_type"] == "coding"
    assert body["evaluation"]["execution_status"] == "completed"
    assert body["evaluation"]["tests_total"] > 0


def test_answer_submission_for_unknown_interview_returns_404():
    response = client.post(
        "/interview/does-not-exist/answer",
        json={"question_id": "python-001", "answer_text": "Some answer."},
    )
    assert response.status_code == 404


def test_answer_submission_for_inactive_interview_is_rejected():
    from app.schemas.interview import InterviewStatus
    from app.services.interview_engine import interview_engine

    start_response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "easy", "question_count": 3},
    )
    interview = start_response.json()

    session = interview_engine.get_interview(interview["interview_id"])
    session.status = InterviewStatus.COMPLETED

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": "Some answer."},
    )
    assert response.status_code == 409


def test_answer_submission_for_unknown_question_is_rejected():
    start_response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "easy", "question_count": 3},
    )
    interview = start_response.json()

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": "not-a-real-question-id", "answer_text": "Some answer."},
    )
    assert response.status_code == 400


def test_answer_cannot_be_submitted_for_a_question_that_was_not_asked():
    start_response = client.post(
        "/interview/start",
        json={"topic": "Python", "difficulty": "easy", "question_count": 3},
    )
    interview = start_response.json()

    # python-002 is a real question in the bank, but not this interview's current one.
    other_question_id = "python-002"
    assert other_question_id != interview["current_question_id"]

    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": other_question_id, "answer_text": "Some answer."},
    )
    assert response.status_code == 400


def test_malformed_llm_output_is_handled_safely_not_as_a_crash():
    with pytest.raises(ValidationError):
        LLMConceptualScores(
            technical_score=8,
            relevance_score=9,
            completeness_score=7,
            clarity_score=8,
            conceptual_understanding_score=15,  # malformed: out of range
            feedback="Malformed.",
        )


def test_health_check_still_works():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}