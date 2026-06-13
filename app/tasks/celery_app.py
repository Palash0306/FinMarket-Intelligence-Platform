# path: app/tasks/celery_app.py

# =========================================================
# CELERY APPLICATION
# =========================================================
#
# What is Celery in plain English?
#
# Celery is a task runner that works in the background.
#
# Without Celery:
# You'd have to manually run "python fetch_prices.py"
# every 5 minutes. If you close your laptop, it stops.
#
# With Celery:
# You define "run this function every 5 minutes"
# and Celery handles it forever, automatically,
# even when you're not watching.
#
# Celery needs two things:
# 1. A broker: somewhere to store the task queue
#    We use Redis — tasks waiting to run live here
# 2. A backend: somewhere to store task results
#    We also use Redis — results of completed tasks live here
#
# Three processes work together:
# celery beat   → "it's been 5 minutes, time to fetch prices"
#                  (puts a task in Redis queue)
# celery worker → "I see a task in the queue, I'll run it"
#                  (runs the actual Python function)
# Redis         → the shared queue between beat and worker

from celery import Celery
from celery.schedules import crontab
from app.config import settings

# ── Create Celery instance ────────────────────────────────
#
# "app.tasks.celery_app" is the name — used for logging
# broker: where tasks queue up (Redis)
# backend: where results are stored (Redis)
celery_app = Celery(
    "finmarket",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.scheduled"]  # where tasks are defined
)

# ── Celery configuration ──────────────────────────────────
celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,

    # ── Fix: use underscores not hyphens in all keys ──────
    #
    # Celery beat schedule keys must not contain hyphens.
    # Hyphens cause TypeError on startup which silently
    # kills the entire scheduler — no tasks run at all.
    beat_schedule={
        "fetch_stock_prices": {
            "task": "app.tasks.scheduled.fetch_stock_prices",
            "schedule": crontab(minute="*/5"),
        },
        "fetch_news_articles": {
            "task": "app.tasks.scheduled.fetch_news_articles",
            "schedule": crontab(minute="*/30"),
        },
        "fetch_stocktwits_sentiment": {
            "task": "app.tasks.scheduled.fetch_stocktwits_sentiment",
            "schedule": crontab(minute=0, hour="*/1"),
        },
        "run_forecasting": {
            "task": "app.tasks.scheduled.run_forecasting",
            "schedule": crontab(hour=9, minute=0),
        },
        "run_sentiment_nlp": {
            "task": "app.tasks.scheduled.run_sentiment_nlp",
            "schedule": crontab(minute="*/30"),
        },
        "run_anomaly_check": {
            "task": "app.tasks.scheduled.run_anomaly_check",
            "schedule": crontab(minute="*/15"),
        },
        "run_embeddings": {
            "task": "app.tasks.scheduled.run_embeddings",
            "schedule": crontab(minute=0, hour="*/1"),
        },
    }
)