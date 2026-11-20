"""Trace ID & request timing middleware for end-to-end observability (TKT-012)."""

import time
import uuid
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

TRACE_HEADER = "X-Trace-ID"
REQUEST_ID_HEADER = "X-Request-ID"
RESPONSE_TIME_HEADER = "X-Response-Time"


class TraceIDMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns a unique trace_id to each incoming request.

    - Reuses inbound X-Trace-ID or X-Request-ID if provided by caller/proxy.
    - Generates a UUIDv4 if no trace header is present.
    - Attaches trace_id to request.state.trace_id for downstream logging and audit records.
    - Injects X-Trace-ID and X-Response-Time headers into the outgoing HTTP response.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = (
            request.headers.get(TRACE_HEADER)
            or request.headers.get(REQUEST_ID_HEADER)
            or str(uuid.uuid4())
        )
        request.state.trace_id = trace_id

        start_time = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        response.headers[TRACE_HEADER] = trace_id
        response.headers[RESPONSE_TIME_HEADER] = f"{duration_ms}ms"
        return response


def get_request_trace_id(request: Request | None) -> str:
    """Helper to extract trace_id from request state or fallback to a new UUID."""
    if request and hasattr(request, "state") and getattr(request.state, "trace_id", None):
        return request.state.trace_id
    return str(uuid.uuid4())
