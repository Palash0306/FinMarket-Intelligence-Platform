# path: app/db/session.py


# create_engine:
# Creates the actual database connection engine
#
# text:
# Used for writing raw SQL queries like "SELECT 1"
from sqlalchemy import create_engine, text


# sessionmaker:
# Creates DB session factory
#
# Session:
# SQLAlchemy session type for type hinting
from sqlalchemy.orm import sessionmaker, Session


# Generator is used for FastAPI dependency typing
#
# Generator[Session, None, None]
# means:
# this function yields a Session object
from typing import Generator


# Import application settings from config.py
#
# Contains:
# database_url
# debug mode
# etc.
from app.config import settings



# =========================================================
# DATABASE ENGINE
# =========================================================

# The engine is the core SQLAlchemy object responsible for:
#
# - opening DB connections
# - managing connection pool
# - communicating with PostgreSQL
#
# Think of engine as:
#
# Python App ↔ SQLAlchemy Engine ↔ PostgreSQL
#
# settings.database_url comes from .env
#
# Example:
# postgresql://user:password@host:5432/dbname
#
# pool_pre_ping=True:
# Before using a connection,
# SQLAlchemy checks whether the connection is still alive.
#
# This prevents:
# "connection already closed" errors
#
# Very important for:
# AWS RDS
# Supabase
# cloud-hosted databases
#
# pool_size=5:
# Keeps up to 5 persistent DB connections open.
#
# Good for small/medium applications
# and free-tier databases.
#
# max_overflow=10:
# Allows SQLAlchemy to temporarily create
# 10 extra connections during traffic spikes.
#
# Total possible connections:
# 5 + 10 = 15
#
# echo=settings.debug:
# If debug=True,
# all SQL queries are printed in terminal.
#
# Useful during development/debugging.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=settings.debug
)



# =========================================================
# SESSION FACTORY
# =========================================================

# SessionLocal is NOT an actual DB session.
#
# It is a factory that CREATES sessions.
#
# Every request gets its own DB session.
#
# autocommit=False:
# Changes are NOT automatically saved.
#
# You must explicitly call:
# db.commit()
#
# Safer and more controlled transaction handling.
#
# autoflush=False:
# SQLAlchemy will not automatically push pending changes
# to database before queries.
#
# Gives better manual control.
#
# bind=engine:
# Connects this session factory to the DB engine.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)



# =========================================================
# FASTAPI DATABASE DEPENDENCY
# =========================================================

# This function is used as a FastAPI dependency.
#
# Example:
#
# @app.get("/jobs")
# def get_jobs(db: Session = Depends(get_db)):
#
# FastAPI automatically:
# 1. creates DB session
# 2. injects it into route
# 3. closes it after request finishes
#
# Generator[Session, None, None]:
# Means this function yields a Session object.
def get_db() -> Generator[Session, None, None]:

    """
    FastAPI dependency for DB session management.

    Flow:
    Request starts
        ↓
    Create DB session
        ↓
    Route uses DB
        ↓
    Close DB session automatically

    The finally block ensures cleanup happens
    even if an exception occurs.
    """

    # Create new DB session
    db = SessionLocal()

    try:

        # Yield session to FastAPI route
        #
        # Example:
        # db.query(...)
        yield db

    finally:

        # Always close DB session
        #
        # Prevents:
        # connection leaks
        # exhausted connection pools
        db.close()



# =========================================================
# DATABASE HEALTH CHECK
# =========================================================

# Simple utility function to check whether
# PostgreSQL is reachable.
#
# Useful for:
# health endpoints
# Docker health checks
# monitoring systems
#
# Returns:
# True  -> DB reachable
# False -> DB unreachable
def check_db_connection() -> bool:

    """Simple database connectivity test."""

    try:

        # Temporarily open DB connection
        #
        # "with" automatically closes connection afterward
        with engine.connect() as conn:

            # Execute lightweight SQL query
            #
            # SELECT 1 is commonly used for health checks
            conn.execute(text("SELECT 1"))

        # If query succeeds:
        # database is working
        return True

    except Exception:

        # If any error occurs:
        # database connection failed
        return False