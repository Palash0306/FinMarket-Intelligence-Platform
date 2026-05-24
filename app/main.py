# path: app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.db.session import check_db_connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup and shutdown.
    Startup: verify DB connection before accepting requests.
    Shutdown: clean up resources.
    """
    # Startup
    print(f"Starting {settings.app_name}...")
    db_ok = check_db_connection()
    if db_ok:
        print("Database connection: OK")
    else:
        print("WARNING: Database connection failed — check your RDS endpoint")
    yield
    # Shutdown
    print("Shutting down...")


app = FastAPI(
    title=settings.app_name,
    description="Real-time financial intelligence platform with ML + AI",
    version="0.1.0",
    docs_url="/docs",       # Swagger UI at /docs
    redoc_url="/redoc",     # ReDoc UI at /redoc
    lifespan=lifespan
)

# CORS — allows your Streamlit dashboard to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
async def health_check():
    """
    Health check endpoint.
    Load balancers and monitoring tools ping this to verify the app is alive.
    """
    db_status = check_db_connection()
    return {
        "status": "ok" if db_status else "degraded",
        "app": settings.app_name,
        "env": settings.app_env,
        "database": "connected" if db_status else "unreachable"
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs"
    }