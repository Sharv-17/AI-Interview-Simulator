"""Deterministic LLM provider for AUTOMATED TESTS ONLY.

This is NOT an AI evaluator. It does not read or understand the answer: it scores
by answer length (>= 40 characters -> 8/10, otherwise 3/10) and splits the
expected concepts in half. It exists so the real evaluation pipeline (prompt
building, schema validation, retries, scoring, persistence) can run in tests
without a network or an API key.

get_llm_provider() refuses to build it unless ALLOW_MOCK_LLM=true, and every
evaluation it produces is labelled evaluator="mock" so it can never be mistaken
for an AI score in stored data.
"""

import math
from typing import Any, Dict

from app.services.llm_providers import LLMProvider, StructuredRequest

SUBSTANTIVE_MIN_CHARS = 40


class MockProvider(LLMProvider):
    name = "mock"

    def complete_json(self, request: StructuredRequest) -> Dict[str, Any]:
        answer = str(request.metadata.get("answer_text", ""))
        concepts = [str(c) for c in request.metadata.get("expected_concepts", [])]
        substantive = len(answer.strip()) >= SUBSTANTIVE_MIN_CHARS
        score = 8 if substantive else 3
        covered = math.ceil(len(concepts) / 2) if substantive else 0
        return {
            "technical_accuracy": score,
            "relevance": score,
            "completeness": score,
            "depth": score,
            "clarity": score,
            "correct_concepts": concepts[:covered],
            "missing_concepts": concepts[covered:],
            "incorrect_concepts": [],
            "feedback": (
                "Mock evaluation: answer has reasonable substance."
                if substantive
                else "Mock evaluation: answer is too short to demonstrate understanding."
            ),
            "reasoning_summary": "Deterministic length-based test double; not an AI evaluation.",
        }
