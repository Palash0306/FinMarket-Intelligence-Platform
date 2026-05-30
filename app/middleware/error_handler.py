# path: app/middleware/error_handler.py

# =========================================================
# GLOBAL ERROR HANDLER MIDDLEWARE
# =========================================================
#
# What is middleware?
#
# Middleware sits between the incoming request and your
# route handlers. Every request passes through it going in,
# and every response passes through it going out.
#
# Think of it like airport security — every passenger
# (request) goes through the same checkpoint regardless
# of their destination (which route they're hitting).
#
# This specific middleware catches ALL unhandled exceptions
# and returns a clean JSON response instead of a raw
# Python traceback.

import time
import uuid
import traceback
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

# Import our logger (built in Step 2)
from app.utils.logger import get_logger

logger = get_logger(__name__)


# =========================================================
# REQUEST TIMING + ID MIDDLEWARE
# =========================================================
#
# This middleware does two things for EVERY request:
#
# 1. Generates a unique request_id (like a tracking number)
#    so you can trace a specific request through all your logs
#
# 2. Measures how long the request took (response time)
#    so you can identify slow endpoints
#
# async def dispatch() is called for every single request.
# await call_next(request) passes the request to the next
# handler (your route function) and waits for the response.
async def request_middleware(request: Request, call_next):
    """
    Adds request ID and timing to every request.

    Attaches to every response:
    - X-Request-ID: unique ID for this request
    - X-Process-Time: how long the request took in ms
    """

    # ── Generate unique request ID ────────────────────────
    #
    # uuid4() generates a random unique identifier.
    # Example: "a3f8c2d1-4e5b-6789-abcd-ef0123456789"
    #
    # This ID appears in logs so you can grep for it
    # and see the complete lifecycle of one request.
    request_id = str(uuid.uuid4())[:8]  # short version for readability

    # ── Start timer ───────────────────────────────────────
    start_time = time.time()

    # ── Log incoming request ──────────────────────────────
    logger.info(
        "request_started",
        extra={
            "request_id": request_id,
            "method": request.method,       # GET, POST, PATCH...
            "path": request.url.path,       # /api/stocks/AAPL
            "client_ip": request.client.host if request.client else "unknown"
        }
    )

    # ── Pass to route handler ─────────────────────────────
    #
    # call_next() hands the request to your actual route function.
    # Everything above runs BEFORE your route.
    # Everything below runs AFTER your route.
    try:
        response = await call_next(request)

        # ── Calculate response time ───────────────────────
        process_time = round((time.time() - start_time) * 1000, 2)

        # ── Log completed request ─────────────────────────
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration_ms": process_time
            }
        )

        # ── Add headers to response ───────────────────────
        #
        # These headers are visible in browser dev tools
        # and useful for debugging and monitoring.
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time}ms"

        return response

    except Exception as exc:
        # ── Catch unexpected errors ───────────────────────
        process_time = round((time.time() - start_time) * 1000, 2)

        logger.error(
            "request_failed",
            extra={
                "request_id": request_id,
                "duration_ms": process_time,
                "error": str(exc),
                # traceback gives full stack trace for debugging
                "traceback": traceback.format_exc()
            }
        )

        # Return clean JSON — never expose the raw traceback
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred",
                "request_id": request_id
            }
        )


# =========================================================
# HTTP EXCEPTION HANDLER
# =========================================================
#
# FastAPI raises HTTPException for expected errors like
# 404 Not Found, 409 Conflict, 401 Unauthorized.
#
# This handler catches them all and returns a consistent
# JSON shape instead of FastAPI's default format.
#
# Why consistent shape?
# Your frontend (Streamlit in Phase 5) and your tests
# can always expect the same error structure:
# { "error": "...", "message": "...", "status_code": ... }
async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException
) -> JSONResponse:
    """
    Handles all HTTPExceptions with a consistent JSON shape.

    Example:
        raise HTTPException(404, "Stock not found")
        →
        {"error": "not_found", "message": "Stock not found", "status_code": 404}
    """

    # Map status codes to readable error names
    # These match standard HTTP error naming conventions
    error_names = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "too_many_requests",
        500: "internal_server_error",
        503: "service_unavailable",
    }

    error_name = error_names.get(exc.status_code, "error")

    logger.warning(
        "http_exception",
        extra={
            "status_code": exc.status_code,
            "error": error_name,
            "path": request.url.path
        }
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_name,
            "message": exc.detail,
            "status_code": exc.status_code
        }
    )


# =========================================================
# VALIDATION ERROR HANDLER
# =========================================================
#
# When a request body fails Pydantic validation
# (missing field, wrong type, value too long etc.),
# FastAPI raises RequestValidationError.
#
# By default it returns a 422 with a complex nested structure.
# This handler flattens it into a readable format.
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
) -> JSONResponse:
    """
    Formats Pydantic validation errors into readable messages.

    Default FastAPI validation error:
    {"detail": [{"loc": ["body", "symbol"], "msg": "...", "type": "..."}]}

    Our format:
    {"error": "validation_error", "fields": [{"field": "symbol", "message": "..."}]}
    """

    # ── Extract field-level errors ────────────────────────
    #
    # exc.errors() returns a list of dicts, one per failed field.
    # We simplify each to just field name + human message.
    errors = []
    for error in exc.errors():
        # loc is a tuple like ("body", "symbol") or ("query", "sector")
        # We take the last element as the field name
        field = ".".join(str(loc) for loc in error["loc"] if loc != "body")
        errors.append({
            "field": field,
            "message": error["msg"]
        })

    logger.warning(
        "validation_error",
        extra={
            "path": request.url.path,
            "errors": errors
        }
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Request validation failed",
            "fields": errors
        }
    )