"""Phase 2/3 integration: an answer is saved first and evaluated second.

Failures are injected at the service's evaluator seam, so everything around it
(recording, status, retries, competency, progression) is the real code."""

import threading

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import interview_service as service_module
from app.services.evaluation_errors import EvaluationFailedError, EvaluationUnavailableError
from app.services.interview_engine import interview_engine

client = TestClient(app)
ANSWER = "A reasonably detailed technical answer that is long enough to count."
REAL_EVALUATE = service_module.evaluate_answer


class Evaluator:
    """Scriptable stand-in for evaluate_answer; counts calls; falls through to the real one."""

    def __init__(self, *failures, delay=None, always=None):
        self.failures = list(failures)
        self.always = always  # if set, EVERY call fails with this
        self.calls = 0
        self.delay = delay

    def __call__(self, question, answer_text, llm_client=None, language=None):
        self.calls += 1
        if self.delay is not None:
            self.delay.wait(0.3)
        if self.always is not None:
            raise self.always
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        return REAL_EVALUATE(question, answer_text, llm_client, language)


@pytest.fixture
def evaluator(monkeypatch):
    def install(*failures, delay=None, always=None):
        fake = Evaluator(*failures, delay=delay, always=always)
        monkeypatch.setattr(service_module, "evaluate_answer", fake)
        return fake

    return install


def _start(count=3):
    interview = client.post(
        "/interview/start", json={"topic": "Algorithms", "difficulty": "easy", "question_count": count}
    ).json()
    assert interview["current_question_id"]
    return interview


def _answer(interview, text=ANSWER, **extra):
    return client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": text, **extra},
    )


def _retry(interview):
    return client.post(
        f"/interview/{interview['interview_id']}/answer/retry-evaluation",
        json={"question_id": interview["current_question_id"]},
    )


def _competency(interview):
    return client.get(f"/interview/{interview['interview_id']}/competency").json()


# ---------------------------------------------------------------------------
# A failed evaluation is explicit: saved answer, no score, no competency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure, status, code",
    [
        (EvaluationUnavailableError(code="llm_timeout"), "pending", "llm_timeout"),
        (EvaluationFailedError(code="llm_invalid_response"), "failed", "llm_invalid_response"),
    ],
)
def test_evaluator_failure_saves_the_answer_with_no_score_and_no_competency(evaluator, failure, status, code):
    evaluator(failure)
    interview = _start()
    response = _answer(interview)

    assert response.status_code == 202
    body = response.json()
    assert body["evaluation_status"] == status
    assert body["evaluation"] is None and body["competency_update"] is None
    assert body["retry_allowed"] is True and body["next_action"] == "retry_evaluation"
    assert body["evaluation_error"]["code"] == code
    assert "overall_score" not in response.text  # no score of any kind is returned
    assert body["timing"]["submitted_at"] and body["answer_id"]

    session = interview_engine.get_interview(interview["interview_id"])
    assert len(session.answers) == 1 and session.answers[0]["answer_text"] == ANSWER
    assert session.answers[0]["evaluation"] is None
    assert _competency(interview) == {}


def test_an_unexpected_evaluator_bug_is_contained_and_never_leaked(evaluator):
    evaluator(RuntimeError("internal secret: /srv/keys/llm.pem"))
    interview = _start()
    response = _answer(interview)
    assert response.status_code == 202
    assert response.json()["evaluation_status"] == "failed"
    assert response.json()["evaluation_error"]["code"] == "evaluator_error"
    assert "secret" not in response.text and "/srv" not in response.text
    assert _competency(interview) == {}


def test_retrying_succeeds_and_updates_competency_exactly_once(evaluator):
    fake = evaluator(EvaluationUnavailableError(), None)
    interview = _start()
    assert _answer(interview).status_code == 202
    assert _competency(interview) == {}

    retried = _retry(interview)
    assert retried.status_code == 200
    body = retried.json()
    assert body["evaluation_status"] == "completed" and body["evaluation"]["overall_score"] == 8.0
    assert body["competency_update"]["questions_attempted"] == 1
    assert body["next_action"] == "advance" and fake.calls == 2
    (state,) = _competency(interview).values()
    assert state["questions_attempted"] == 1


def test_retrying_an_already_scored_answer_does_not_evaluate_or_update_again(evaluator):
    fake = evaluator()
    interview = _start()
    first = _answer(interview).json()
    assert fake.calls == 1

    for _ in range(3):
        again = _retry(interview)
        assert again.status_code == 200
        assert again.json()["answer_id"] == first["answer_id"]
        assert again.json()["evaluation"] == first["evaluation"]
    assert fake.calls == 1  # the evaluator was never called again
    (state,) = _competency(interview).values()
    assert state["questions_attempted"] == 1


def test_a_saved_answer_cannot_be_replaced_while_evaluation_is_pending(evaluator):
    evaluator(EvaluationUnavailableError())
    interview = _start()
    assert _answer(interview, "my first answer text").status_code == 202
    second = _answer(interview, "a much better second attempt at it")
    assert second.status_code == 409
    session = interview_engine.get_interview(interview["interview_id"])
    assert [a["answer_text"] for a in session.answers] == ["my first answer text"]


def test_retry_without_a_recorded_answer_is_refused():
    interview = _start()
    response = _retry(interview)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "no_answer_recorded"


def test_retries_are_bounded_and_an_exhausted_answer_no_longer_blocks_progress(evaluator, monkeypatch):
    monkeypatch.setattr(config, "MAX_EVALUATION_RETRIES", 1)
    evaluator(always=EvaluationUnavailableError())  # fails every time
    interview = _start()
    first = _answer(interview).json()
    assert first["retry_allowed"] is True
    second = _retry(interview)
    assert second.status_code == 202 and second.json()["retry_allowed"] is False
    assert second.json()["next_action"] == "advance"

    exhausted = _retry(interview)
    assert exhausted.status_code == 409 and exhausted.json()["detail"]["code"] == "evaluation_retries_exhausted"

    moved = client.post(f"/interview/{interview['interview_id']}/next")
    assert moved.status_code == 200 and moved.json()["current_question"] == 2
    assert _competency(interview) == {}  # never scored, never counted


def test_progress_is_blocked_until_the_pending_answer_is_scored(evaluator):
    evaluator(EvaluationUnavailableError(), None)
    interview = _start()
    _answer(interview)
    blocked = client.post(f"/interview/{interview['interview_id']}/next")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "evaluation_pending"
    assert _retry(interview).status_code == 200
    assert client.post(f"/interview/{interview['interview_id']}/next").status_code == 200


def test_the_interview_state_tells_the_frontend_what_to_do_next(evaluator):
    evaluator(EvaluationUnavailableError(), None)
    interview = _start()
    state = lambda: client.get(f"/interview/{interview['interview_id']}").json()  # noqa: E731
    assert (state()["question_state"], state()["next_action"]) == ("active", "answer")
    _answer(interview)
    assert (state()["question_state"], state()["next_action"]) == ("evaluation_pending", "retry_evaluation")
    _retry(interview)
    assert (state()["question_state"], state()["next_action"]) == ("evaluated", "advance")


def test_a_normal_submission_evaluates_once_and_duplicates_never_evaluate(evaluator):
    fake = evaluator()
    interview = _start()
    assert _answer(interview).status_code == 200
    for _ in range(3):
        assert _answer(interview).status_code == 409
    assert fake.calls == 1
    (state,) = _competency(interview).values()
    assert state["questions_attempted"] == 1


def test_a_failed_evaluation_does_not_count_as_a_second_competency_update_later(evaluator):
    evaluator(EvaluationFailedError(), EvaluationFailedError(), None)
    interview = _start()
    _answer(interview)
    _retry(interview)
    assert _competency(interview) == {}
    assert _retry(interview).status_code == 200
    (state,) = _competency(interview).values()
    assert state["questions_attempted"] == 1


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def _race(call, workers=2):
    barrier, results = threading.Barrier(workers), []

    def worker():
        barrier.wait()
        results.append(call())

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results


def test_two_simultaneous_identical_submissions_score_exactly_once(evaluator):
    fake = evaluator(delay=threading.Event())  # the first one is slow, so they genuinely overlap
    interview = _start()
    statuses = sorted(r.status_code for r in _race(lambda: _answer(interview)))
    assert statuses == [200, 409]
    assert fake.calls == 1
    (state,) = _competency(interview).values()
    assert state["questions_attempted"] == 1
    assert len(interview_engine.get_interview(interview["interview_id"]).answers) == 1


def test_simultaneous_retries_never_evaluate_or_update_twice(evaluator):
    fake = evaluator(EvaluationUnavailableError(), None, delay=threading.Event())
    interview = _start()
    assert _answer(interview).status_code == 202
    fake.calls = 0
    results = _race(lambda: _retry(interview), workers=3)
    assert {r.status_code for r in results} <= {200, 409}
    assert any(r.status_code == 200 for r in results)
    assert fake.calls == 1
    (state,) = _competency(interview).values()
    assert state["questions_attempted"] == 1


# ---------------------------------------------------------------------------
# Candidate-facing responses never reveal the answer key
# ---------------------------------------------------------------------------


def test_candidate_responses_never_contain_the_reference_answer_or_rubric():
    from app.repositories.question_repository import question_repository

    interview = _start()
    question = question_repository.get_by_id(interview["current_question_id"])
    answered = _answer(interview)
    texts = [
        client.get(f"/interview/{interview['interview_id']}").text,
        client.get(f"/questions/{question.question_id}").text,
        answered.text,
        client.get(f"/interview/{interview['interview_id']}/competency").text,
    ]
    secrets = [question.reference_answer, *question.evaluation_criteria, "reference_answer", "evaluation_criteria",
               "expected_concepts", "reasoning_summary"]
    for text in texts:
        for secret in secrets:
            assert secret not in text, secret


# ---------------------------------------------------------------------------
# Input validation and unknown sessions
# ---------------------------------------------------------------------------


def test_empty_blank_and_oversized_answers_are_rejected():
    interview = _start()
    for text in ("", "   \n\t"):
        assert _answer(interview, text).status_code == 422
    assert _answer(interview, "x" * (config.MAX_ANSWER_CHARS + 1)).status_code == 422
    assert _answer(interview, "x" * config.MAX_ANSWER_CHARS).status_code == 200  # the limit itself is fine


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/interview/nope", None),
        ("post", "/interview/nope/answer", {"question_id": "q", "answer_text": "a"}),
        ("post", "/interview/nope/answer/retry-evaluation", {"question_id": "q"}),
        ("post", "/interview/nope/next", None),
        ("post", "/interview/nope/integrity-events", {"events": [{"event_type": "copy"}]}),
        ("get", "/interview/nope/competency", None),
        ("get", "/interview/nope/report", None),
    ],
)
def test_unknown_interview_ids_return_404_everywhere(method, path, body):
    response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert response.status_code == 404
