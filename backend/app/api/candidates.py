"""Guest candidate records and history, addressed by a candidate id in the path.

These remain unauthenticated on purpose: a guest candidate has no account and its id
is the only handle the existing frontend has. Account-owned candidates are reachable
the same way *for guests*, but a request carrying a session is checked: the interview
endpoints (app/api/auth_deps.py: require_interview_access) refuse another account's
interviews. The account-scoped equivalents are in app/api/account.py.
"""

from typing import List

from fastapi import APIRouter, Depends

from app.api.auth_deps import require_candidate_access
from app.api.errors import http_error_for
from app.schemas.candidate import CandidateCreate, CandidateView, CompetencyHistoryEntry, InterviewSummary
from app.services.interview_service import InterviewService, get_interview_service

router = APIRouter(prefix="/candidates", tags=["candidates"])


def _run(operation):
    try:
        return operation()
    except Exception as exc:
        mapped = http_error_for(exc)
        if mapped is None:
            raise
        raise mapped from None


@router.post("", response_model=CandidateView, status_code=201)
def create_candidate(payload: CandidateCreate, service: InterviewService = Depends(get_interview_service)):
    """Create a candidate record (optional: interviews can also start without one)."""
    try:
        return service.create_candidate(payload)
    except ValueError:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="A candidate with this external_id already exists") from None


@router.get("/{candidate_id}", response_model=CandidateView)
def get_candidate(
    candidate_id: str,
    service: InterviewService = Depends(get_interview_service),
    _access: None = Depends(require_candidate_access),
):
    return _run(lambda: service.get_candidate(candidate_id))


@router.get("/{candidate_id}/interviews", response_model=List[InterviewSummary])
def list_candidate_interviews(
    candidate_id: str,
    service: InterviewService = Depends(get_interview_service),
    _access: None = Depends(require_candidate_access),
):
    """Previous interview sessions of this candidate, oldest first.

    Guest candidates stay readable by id (existing contract). An account-owned
    candidate requires that account's session.
    """
    return _run(lambda: service.list_interviews(candidate_id))


@router.get("/{candidate_id}/competency-history", response_model=List[CompetencyHistoryEntry])
def candidate_competency_history(
    candidate_id: str,
    service: InterviewService = Depends(get_interview_service),
    _access: None = Depends(require_candidate_access),
):
    """Every competency update (one per evaluated answer) across this candidate's interviews."""
    return _run(lambda: service.competency_history(candidate_id))
