# path: app/main.py

# =========================================================
# FINMARKET INTELLIGENCE — FASTAPI APPLICATION
# =========================================================
#
# This is the fully updated main.py with:
# - Error handling middleware
# - Request timing middleware
# - Structured logging
# - CloudWatch integration
# - All routers registered

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager

from app.config import settings
from app.db.session import check_db_connection
from app.utils.logger import get_logger
from app.utils.cloudwatch import setup_cloudwatch_logging

# ── Import error handlers ─────────────────────────────────
from app.middleware.error_handler import (
    request_middleware,
    http_exception_handler,
    validation_exception_handler
)

# ── Import routers ────────────────────────────────────────
from app.api.stocks import router as stocks_router

# ── Module logger ─────────────────────────────────────────
#
# __name__ here is "app.main" — useful for filtering logs
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs startup and shutdown logic.

    Startup order matters:
    1. CloudWatch first — so all startup logs are captured
    2. DB check — verify RDS is reachable
    3. Ready to serve requests
    """

    # ── Startup ───────────────────────────────────────────
    logger.info(
        "app_starting",
        extra={
            "app_name": settings.app_name,
            "env": settings.app_env,
            "region": settings.aws_default_region
        }
    )

    # Enable CloudWatch in non-dev environments
    setup_cloudwatch_logging()

    # Check RDS connection
    db_ok = check_db_connection()
    if db_ok:
        logger.info("database_connected", extra={"host": settings.database_url.split("@")[-1]})
    else:
        logger.error("database_unreachable")

    yield

    # ── Shutdown ──────────────────────────────────────────
    logger.info("app_shutting_down")


# ── Create FastAPI app ────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    description="Real-time financial intelligence platform with ML + AI",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# ── Register exception handlers ───────────────────────────
#
# These run for every request that raises these exceptions.
# Order doesn't matter here — each handles a different type.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# ── Register middleware ───────────────────────────────────
#
# Middleware order DOES matter — they stack like layers.
# Last added = outermost layer (runs first on request,
#                               last on response)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request timing + ID middleware
# Wraps every request with timing and a unique ID
app.middleware("http")(request_middleware)

# ── Register routers ──────────────────────────────────────
app.include_router(stocks_router)


# ── System endpoints ──────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    """
    Health check endpoint.

    Called by:
    - Load balancers (to know if app is alive)
    - Monitoring tools (to track uptime)
    - Your own sanity (to verify RDS is connected)
    """
    db_status = check_db_connection()

    logger.info(
        "health_check",
        extra={"db_status": "connected" if db_status else "unreachable"}
    )

    return {
        "status": "ok" if db_status else "degraded",
        "app": settings.app_name,
        "version": "0.1.0",
        "env": settings.app_env,
        "region": settings.aws_default_region,
        "database": "connected" if db_status else "unreachable"
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs",
        "health": "/health"
    }



# http://localhost:8000  - {"message": "Welcome to FinMarket Intelligence"}
# http://localhost:8000/health - {"status": "ok", "database": "connected"}
# http://localhost:8000/docs - Swagger UI — interactive API documentation
# http://localhost:8080 - Adminer DB GUI — log in with the Postgres credentials