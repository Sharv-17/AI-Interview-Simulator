"""Response model for POST /interview/{interview_id}/transcribe."""

from typing import Optional

from pydantic import BaseModel


class TranscriptionResponse(BaseModel):
    """A transcript for the candidate to review and edit.

    Returning this changes NO interview state: nothing is evaluated, stored as
    an answer, or counted toward competency until the candidate submits text
    through the existing answer endpoint.
    """

    interview_id: str
    question_id: str
    transcript: str
    duration_seconds: Optional[float] = None