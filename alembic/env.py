# path: alembic/env.py

# =========================================================
# ALEMBIC ENVIRONMENT CONFIGURATION
# =========================================================
#
# This file is the bridge between Alembic and your app.
#
# It tells Alembic:
# 1. Which database URL to use
# 2. Which SQLAlchemy models to track for migrations
#
# Alembic runs in two modes:
#
# - offline mode: generates SQL scripts without connecting
# - online mode:  connects to DB and runs migrations directly
#
# We use online mode (run_migrations_online) in this project.

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
# ── Import ALL models here ────────────────────────────────
from app.models.base import Base, TimestampMixin
from app.models.stock import Stock

# ── Import your app's settings and Base ──────────────────
#
# settings provides the DATABASE_URL from your .env file
# Base.metadata contains all your SQLAlchemy model definitions
# Alembic compares Base.metadata against the live DB
# to detect what changed and generate migrations automatically
from app.config import settings
from app.models.base import Base

# ── Import ALL models here ────────────────────────────────
#
# IMPORTANT: every model file must be imported here.
# If a model is not imported, Alembic cannot see it
# and will not generate migrations for it.
#
# We will add more imports here as we build more models
# in later phases. For now, base is enough.
# Example for later:
# from app.models.stock import Stock
# from app.models.news import NewsArticle
# Phase 1:
from app.models.stock import Stock

# Phase 2 Day 2 — new:
from app.models.news import NewsArticle          # → news_articles table
from app.models.stocktwits_post import StocktwitsPost  # → stocktwits_posts table

# ── Alembic Config object ─────────────────────────────────
#
# config gives access to values in alembic.ini
# fileConfig sets up Python logging using alembic.ini settings
config = context.config

# Set up logging as defined in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Point Alembic at your models ─────────────────────────
#
# target_metadata tells Alembic which models to track.
#
# When you run:
#   alembic revision --autogenerate -m "add stock table"
#
# Alembic compares Base.metadata (your Python models)
# against the live database schema and generates the diff.
target_metadata = Base.metadata

# ── Inject DATABASE_URL from .env ────────────────────────
#
# Instead of hardcoding the DB URL in alembic.ini,
# we pull it from pydantic settings (which reads .env).
#
# This means one source of truth for the DB URL —
# your .env file — used by both FastAPI and Alembic.
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """
    Offline mode: generate SQL script without DB connection.

    Useful for:
    - reviewing what SQL will be executed
    - generating scripts for a DBA to run manually

    Run with:
        alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Online mode: connect to DB and run migrations directly.

    This is the mode used in normal development.

    Run with:
        alembic upgrade head
    """
    # Create a real DB engine using the URL from settings
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",

        # NullPool means no connection pooling during migrations
        # Migrations are one-off operations, not ongoing connections
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


# ── Run the appropriate mode ──────────────────────────────
#
# context.is_offline_mode() returns True only when
# --sql flag is passed to alembic commands.
# Otherwise we always run in online mode.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()