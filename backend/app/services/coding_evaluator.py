"""Coding-answer evaluation.

IMPORTANT / SECURITY: this module does NOT execute candidate code.
There is no eval(), exec(), or subprocess call anywhere here, and none
should be added without a real, isolated sandbox (a container with no
network, filesystem, or environment-variable access). Building that
sandbox is out of scope for Stage 3.4.

Instead, this is a deterministic, safe placeholder: a candidate's
submission is checked for the presence of expected keywords/substrings
per test case. This is NOT a claim that the candidate's code is
correct — only that it demonstrates the expected approach — and it
stands in for real test execution until a secure sandbox exists.

TEST_CASE_REGISTRY below is a temporary, hand-written mapping of
question_id -> test cases for the few coding questions that currently
exist in the seed question bank. It does not scale to hundreds of
questions — a future stage should move test cases into the question
bank data itself once a real execution/sandbox strategy is decided.
"""

from typing import Dict, List

from pydantic import BaseModel

from app.schemas.evaluation import CodingEvaluation, ExecutionStatus
from app.schemas.question import Question, QuestionType


class CodeCheck(BaseModel):
    """One safe, non-executing check against a candidate's submission.

    `keyword` is a substring expected to appear (case-insensitive) in
    the candidate's submitted code. This stands in for a real test case
    (input/expected-output) until secure execution exists.
    """

    name: str
    keyword: str

TEST_CASE_REGISTRY: Dict[str, List[CodeCheck]] = {}
"""
Currently empty: the live question bank (converted from
data/question_bank.csv) has no "coding"-type questions — the source
CSV had no column distinguishing conceptual from coding questions, so
every row converted as "conceptual" (see scripts/convert_question_bank.py).
When coding questions are added to the bank, add their test cases here,
keyed by question_id, e.g.:

    TEST_CASE_REGISTRY = {
        "some-coding-question-id": [
            CodeCheck(name="defines a function", keyword="def"),
        ],
    }
"""


def get_test_cases_for_question(question_id: str) -> List[CodeCheck]:
    """Return the configured test cases for a question, or an empty list."""
    return TEST_CASE_REGISTRY.get(question_id, [])


def evaluate_coding_answer(
    question: Question,
    answer_text: str,
    test_cases: List[CodeCheck],
) -> CodingEvaluation:
    """Evaluate a candidate's code submission against safe keyword checks.

    overall_score = (tests_passed / tests_total) * 10, documented and
    deterministic. Passing these checks does not certify the code is
    correct or optimal — only that expected keywords are present.
    """
    if not test_cases:
        return CodingEvaluation(
            question_id=question.question_id,
            question_type=QuestionType.CODING,
            tests_total=0,
            tests_passed=0,
            tests_failed=0,
            execution_status=ExecutionStatus.SKIPPED,
            overall_score=0.0,
            feedback=(
                "No automated test cases are configured for this question yet. "
                "Coding evaluation requires a secure execution sandbox, which is "
                "not implemented at this stage."
            ),
            strengths=[],
            weaknesses=[],
        )

    submission = answer_text.lower()
    results = [tc.keyword.lower() in submission for tc in test_cases]
    tests_passed = sum(results)
    tests_total = len(test_cases)
    tests_failed = tests_total - tests_passed
    overall_score = round((tests_passed / tests_total) * 10, 1)

    passed_names = [tc.name for tc, ok in zip(test_cases, results) if ok]
    failed_names = [tc.name for tc, ok in zip(test_cases, results) if not ok]

    return CodingEvaluation(
        question_id=question.question_id,
        question_type=QuestionType.CODING,
        tests_total=tests_total,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        execution_status=ExecutionStatus.COMPLETED,
        overall_score=overall_score,
        feedback=f"{tests_passed}/{tests_total} keyword checks passed.",
        strengths=passed_names,
        weaknesses=failed_names,
    )