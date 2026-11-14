from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.interview import router as interview_router
from app.api.questions import router as questions_router
from app.api.upload_limits import enforce_transcribe_size_limit

app = FastAPI()

app.middleware("http")(enforce_transcribe_size_limit)

app.include_router(interview_router)
app.include_router(questions_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health_check():
    return {"status": "ok"}