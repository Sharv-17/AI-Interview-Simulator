"""Account-scoped resources: the caller's own candidate and interview history.

These are the only endpoints that read a candidate id from the *session*: a client
never supplies which candidate to read here, which is what makes them safe without
any further ownership check.
"""

from typing import List

from fastapi import APIRouter, Depends

from app.api.auth_deps import require_authenticated_user
from app.api.errors import http_error_for
from app.schemas.candidate import CandidateView, InterviewSummary
from app.services.auth_errors import AccountResourceMissing
from app.services.auth_store import UserRecord
from app.services.interview_service import InterviewService, get_interview_service

router = APIRouter(prefix="/api/v1", tags=["account"])


def _run(operation):
    try:
        return operation()
    except Exception as exc:
        mapped = http_error_for(exc)
        if mapped is None:
            raise
        raise mapped from None


def _candidate_id(user: UserRecord) -> str:
    if not user.candidate_id:
        raise AccountResourceMissing()
    return user.candidate_id


@router.get(
    "/candidates/me",
    response_model=CandidateView,
    summary="My candidate record",
    responses={401: {"description": "No valid session."}},
)
def my_candidate(
    user: UserRecord = Depends(require_authenticated_user),
    interviews: InterviewService = Depends(get_interview_service),
) -> CandidateView:
    """The candidate record owned by the signed-in account.

    It is the same kind of id guest interviews use, so candidate-aware question
    cooldown and competency history keep working unchanged.
    """
    return _run(lambda: interviews.get_candidate(_candidate_id(user)))


@router.get(
    "/interviews/me",
    response_model=List[InterviewSummary],
    summary="My interviews",
    responses={401: {"description": "No valid session."}},
)
def my_interviews(
    user: UserRecord = Depends(require_authenticated_user),
    interviews: InterviewService = Depends(get_interview_service),
) -> List[InterviewSummary]:
    """Interview sessions of the signed-in account's candidate, oldest first."""
    return _run(lambda: interviews.list_interviews(_candidate_id(user)))
