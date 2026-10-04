import re
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import get_logger
from app.metrics import observe_request

logger = get_logger("http")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

# One year. Applies to this host and its subdomains. preload is left off
# because joining the browser preload list is public and hard to undo.
HSTS_VALUE = "max-age=31536000; includeSubDomains"
# Matches X-Frame-Options: DENY for browsers that honor CSP over the older header.
FRAME_ANCESTORS_VALUE = "frame-ancestors 'none'"

# A client id is logged separately. Newlines and other characters are dropped
# so the value cannot forge a log line.
_CLIENT_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def client_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if _CLIENT_REQUEST_ID.fullmatch(cleaned):
        return cleaned
    return None


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a server request id to every log line and response, and time the request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid.uuid4().hex
        supplied = client_request_id(request.headers.get("x-request-id"))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        if supplied is not None:
            structlog.contextvars.bind_contextvars(client_request_id=supplied)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            observe_request(request.url.path, 500, time.perf_counter() - started)
            raise
        duration_seconds = time.perf_counter() - started
        observe_request(request.url.path, response.status_code, duration_seconds)
        duration_ms = round(duration_seconds * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        # TLS ends at the platform proxy, so the app itself often sees HTTP.
        # Browsers still receive these headers on the HTTPS response.
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
            response.headers.setdefault("Content-Security-Policy", FRAME_ANCESTORS_VALUE)
        return response
