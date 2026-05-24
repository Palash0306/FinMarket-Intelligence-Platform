# path: app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.db.session import check_db_connection


# Lifespan context managers handle startup and shutdown logic seamlessly in modern FastAPI.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup and shutdown.
    Startup: verify DB connection before accepting requests.
    Shutdown: clean up resources.
    """
    # Startup Phase: Executes before the application begins accepting incoming network requests.
    print(f"Starting {settings.app_name}...")
    db_ok = check_db_connection()
    if db_ok:
        print("Database connection: OK")
    else:
        # Fails softly with a warning; prevents the server from crashing immediately if the DB is temporarily down.
        print("WARNING: Database connection failed — check your RDS endpoint")
    
    # The yield statement yields control back to FastAPI. The app runs while paused here.
    yield
    
    # Shutdown Phase: Executes when the server process receives a termination signal (e.g., SIGTERM).
    print("Shutting down...")


# Initialize the core FastAPI application instance with metadata and configuration hooks.
app = FastAPI(
    title=settings.app_name,
    description="Real-time financial intelligence platform with ML + AI",
    version="0.1.0",
    docs_url="/docs",       # Swagger UI at /docs
    redoc_url="/redoc",     # ReDoc UI at /redoc
    lifespan=lifespan       # Registers the startup/shutdown lifecycle hook defined above.
)

# CORS (Cross-Origin Resource Sharing) middleware handles security restrictions for web browsers.
# This prevents browsers from blocking requests originating from different domains (e.g., your Streamlit UI).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # Wildcard allows all origins; change to a specific whitelist for production environments.
    allow_credentials=True, # Permits HTTP cookies and authentication headers to be passed across origins.
    allow_methods=["*"],    # Allows all HTTP methods (GET, POST, PUT, DELETE, etc.).
    allow_headers=["*"],    # Allows all custom and standard HTTP request headers.
)


@app.get("/health", tags=["System"])
async def health_check():
    """
    Health check endpoint.
    Load balancers and monitoring tools ping this to verify the app is alive.
    """
    # Dynamic runtime check: Query the database status on every ping rather than caching it.
    db_status = check_db_connection()
    
    # Returns a 200 OK status code but flags 'degraded' if the app is up but missing its database link.
    return {
        "status": "ok" if db_status else "degraded",
        "app": settings.app_name,
        "env": settings.app_env,
        "database": "connected" if db_status else "unreachable"
    }


@app.get("/", tags=["System"])
async def root():
    # Simple landing endpoint providing immediate API confirmation and a quick link to the auto-generated documentation.
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs"
    }



# http://localhost:8000  - {"message": "Welcome to FinMarket Intelligence"}
# http://localhost:8000/health - {"status": "ok", "database": "connected"}
# http://localhost:8000/docs - Swagger UI — interactive API documentation
# http://localhost:8080 - Adminer DB GUI — log in with the Postgres credentials