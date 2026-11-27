import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.account import router as account_router
from app.api.auth import router as auth_router
from app.api.candidates import router as candidates_router
from app.api.interview import router as interview_router
from app.api.questions import router as questions_router
from app.api.errors import http_error_for
from app.api.upload_limits import enforce_transcribe_size_limit
from app.services.auth_errors import AuthError
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

app.middleware("http")(enforce_transcribe_size_limit)


@app.middleware("http")
async def no_store_account_responses(request, call_next):
    """Account responses must never be cached by a browser or an edge proxy.

    The account API is served through a CDN-backed reverse proxy in production, so
    every /api/v1 response (including 401s from the exception handlers) carries
    no-store rather than relying on the proxy's cache configuration.
    """
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response

app.include_router(interview_router)
app.include_router(questions_router)
app.include_router(candidates_router)
# Account API. Authentication is opt-in: no existing router requires a session.
app.include_router(auth_router)
app.include_router(account_router)


@app.exception_handler(AuthError)
async def auth_error_handler(request, exc: AuthError):
    """Authentication domain errors become their documented status/code/message.

    Needed because dependencies (not just route bodies) raise them; nothing about the
    exception itself reaches the client beyond the safe fields.
    """
    mapped = http_error_for(exc)
    return JSONResponse(
        status_code=mapped.status_code,
        content={"detail": mapped.detail},
        headers=mapped.headers,
    )


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
