import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.candidates import router as candidates_router
from app.api.interview import router as interview_router
from app.api.questions import router as questions_router
from app.api.upload_limits import enforce_transcribe_size_limit
from app.services.interview_service import get_interview_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fail fast at start-up if storage is misconfigured, and prepare it (migrated schema check, reference data)."""
    service = get_interview_service()
    service.store.startup()
    logger.info("Storage backend: %s", service.backend_name)
    yield


app = FastAPI(title="AI Interview Simulator", lifespan=lifespan)
import os
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("FRONTEND_ORIGINS", "").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.middleware("http")(enforce_transcribe_size_limit)

app.include_router(interview_router)
app.include_router(questions_router)
app.include_router(candidates_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    """Is storage usable? 503 (no internal detail) if not."""
    try:
        service = get_interview_service()
        service.check_ready()
    except Exception:
        logger.exception("Readiness check failed")
        return JSONResponse(
            status_code=503,
            content={"detail": {"code": "storage_unavailable", "message": "Storage is not available."}},
        )
    return {"status": "ok", "storage": service.backend_name}
