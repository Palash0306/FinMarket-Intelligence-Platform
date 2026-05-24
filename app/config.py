# path: app/config.py

# BaseSettings automatically reads environment variables from .env
# and maps them into Python variables
from pydantic_settings import BaseSettings

# lru_cache caches function results
# Here it ensures Settings() is created only once
from functools import lru_cache


# Settings class stores all application configuration
# This is the central config object for the entire backend
class Settings(BaseSettings):

    # =========================
    # APPLICATION CONFIG
    # =========================

    # Name of the application
    # Used in API docs, logs, monitoring, etc.
    app_name: str = "FinMarket Intelligence"

    # Current environment
    # Usually: development / staging / production
    app_env: str = "development"

    # Enables debug mode
    # True → detailed logs/errors
    # False → production-safe behavior
    debug: bool = True

    # Secret key used for:
    # JWT tokens
    # authentication
    # cryptographic signing
    secret_key: str = "change-this"


    # =========================
    # DATABASE CONFIG
    # =========================

    # PostgreSQL connection string
    # Example:
    # postgresql://user:password@host:5432/dbname
    #
    # No default value means:
    # this MUST exist inside .env
    database_url: str


    # =========================
    # REDIS CONFIG
    # =========================

    # Redis connection URL
    # Used for:
    # caching
    # background jobs
    # rate limiting
    #
    # Example:
    # redis://localhost:6379
    redis_url: str


    # =========================
    # AWS CONFIG
    # =========================

    # AWS access key for authentication
    # Used to connect to AWS services
    aws_access_key_id: str = ""

    # AWS secret key
    # Never commit real values to GitHub
    aws_secret_access_key: str = ""

    # AWS region
    # us-east-1 is one of the default AWS regions
    aws_default_region: str = "us-east-1"

    # Name of S3 bucket used for raw data storage
    # Example:
    # scraped CSVs
    # raw JSON files
    # uploaded datasets
    s3_bucket_name: str = "finmarket-raw-data"


    # =========================
    # EXTERNAL API CONFIG
    # =========================

    # API key for Alpha Vantage
    # Used for financial market data
    alpha_vantage_api_key: str = ""

    # API key for News API
    # Used to fetch financial news/articles
    news_api_key: str = ""


    # =========================
    # AI / LLM CONFIG
    # =========================

    # API key for Groq LLM services
    # Used for:
    # AI analysis
    # summarization
    # chatbot
    groq_api_key: str = ""


    # =========================
    # PYDANTIC CONFIGURATION
    # =========================

    class Config:

        # Tells Pydantic to load variables from .env file
        env_file = ".env"

        # Makes environment variable matching case-insensitive
        #
        # Example:
        # DATABASE_URL
        # database_url
        #
        # both will work
        case_sensitive = False


# =========================
# SETTINGS CACHING
# =========================

# lru_cache ensures this function runs only once
#
# Without this:
# every import would recreate Settings()
#
# With cache:
# config loads once and is reused everywhere
@lru_cache()
def get_settings() -> Settings:

    # Creates and returns Settings object
    # Automatically reads .env values
    return Settings()


# Global settings object
#
# Import this anywhere:
#
# from app.config import settings
#
# Then use:
# settings.database_url
# settings.debug
# etc.
settings = get_settings()