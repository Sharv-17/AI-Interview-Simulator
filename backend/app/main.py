from fastapi import FastAPI

from app.api.interview import router as interview_router
from app.api.questions import router as questions_router

app = FastAPI()

app.include_router(interview_router)
app.include_router(questions_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}