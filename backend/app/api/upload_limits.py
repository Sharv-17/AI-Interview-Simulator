"""Early request-size check for audio uploads.

Rejects an upload whose declared Content-Length is clearly over the audio limit
BEFORE the body is read, so an honest oversized upload is refused cheaply.

Limitation: a client can omit or falsify Content-Length (e.g. chunked uploads).
Those still hit the streaming size check in
app/services/audio_validation.read_upload_limited, but the framework may have
spooled the body to temporary storage first. Production deployments should also
enforce a request-body limit at the reverse proxy.
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from app import config

# Room for multipart boundaries and the question_id form field.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


async def enforce_transcribe_size_limit(request: Request, call_next):
    if request.method == "POST" and request.url.path.endswith("/transcribe"):
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit():
            if int(declared) > config.MAX_AUDIO_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": {
                            "code": "audio_too_large",
                            "message": "The uploaded audio is larger than the allowed size.",
                        }
                    },
                )
    return await call_next(request)