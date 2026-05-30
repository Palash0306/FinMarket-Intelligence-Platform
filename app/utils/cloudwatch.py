# path: app/utils/cloudwatch.py

# =========================================================
# AWS CLOUDWATCH LOGGING INTEGRATION
# =========================================================
#
# What is CloudWatch?
#
# CloudWatch is AWS's monitoring and logging service.
# Instead of logs disappearing when your Docker container
# restarts, CloudWatch stores them permanently in the cloud.
#
# You can:
# - Search logs across all requests
# - Set alerts ("email me if error rate exceeds 5/min")
# - Build dashboards showing API health over time
# - Query logs with CloudWatch Insights SQL-like syntax
#
# How it works:
# Your app sends logs → CloudWatch Log Group → stored forever
#                                             → queryable
#                                             → alertable
#
# This file creates a custom Python logging handler that
# sends each log entry to CloudWatch in addition to
# printing it to the console.

import logging
import boto3
import time
from botocore.exceptions import ClientError
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CloudWatchHandler(logging.Handler):
    """
    Custom logging handler that sends log records to AWS CloudWatch.

    Python's logging system uses "handlers" to decide where
    logs go. Built-in handlers: FileHandler (to file),
    StreamHandler (to console). This is our custom handler
    that sends to CloudWatch.

    CloudWatch concepts:
    - Log Group:  like a folder  → "/finmarket/api"
    - Log Stream: like a file    → "2024-01-15/app"
    - Log Event:  one log entry  → {"timestamp": ..., "message": ...}
    """

    def __init__(self):
        super().__init__()

        # ── Log group and stream names ────────────────────
        #
        # Log group: one per application
        # Log stream: one per day (keeps logs organized by date)
        self.log_group = f"/finmarket/{settings.app_env}"
        self.log_stream = f"api-{time.strftime('%Y-%m-%d')}"

        # ── AWS CloudWatch client ─────────────────────────
        #
        # boto3 is the AWS Python SDK.
        # It reads credentials from your .env via environment variables:
        # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
        self.client = boto3.client(
            "logs",
            region_name=settings.aws_default_region
        )

        # ── Sequence token ────────────────────────────────
        #
        # CloudWatch requires log events to be sent in order.
        # sequence_token tracks position in the stream.
        # None on first send, then AWS returns a new token each time.
        self.sequence_token = None

        # ── Create log group and stream ───────────────────
        self._setup_log_group()
        self._setup_log_stream()

    def _setup_log_group(self) -> None:
        """
        Creates the CloudWatch log group if it doesn't exist.

        A log group is like a folder in CloudWatch.
        We set a retention policy of 30 days — logs older than
        30 days are automatically deleted to control costs.
        """
        try:
            self.client.create_log_group(logGroupName=self.log_group)

            # Set retention: delete logs older than 30 days
            # Prevents unbounded storage costs
            self.client.put_retention_policy(
                logGroupName=self.log_group,
                retentionInDays=30
            )
        except ClientError as e:
            # ResourceAlreadyExistsException is fine — group exists
            if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                print(f"CloudWatch log group error: {e}")

    def _setup_log_stream(self) -> None:
        """
        Creates today's log stream if it doesn't exist.

        A log stream is like a file within the log group folder.
        We create one per day so logs are easy to browse by date.
        """
        try:
            self.client.create_log_stream(
                logGroupName=self.log_group,
                logStreamName=self.log_stream
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                print(f"CloudWatch log stream error: {e}")

    def emit(self, record: logging.LogRecord) -> None:
        """
        Sends a single log record to CloudWatch.

        emit() is called automatically by Python's logging
        system every time a log is written.

        CloudWatch expects:
        - timestamp: milliseconds since epoch (not seconds)
        - message: the log text
        """
        try:
            # ── Format the log record ─────────────────────
            #
            # self.format() calls our JSONFormatter
            # to convert the record to a JSON string
            log_message = self.format(record)

            # ── CloudWatch timestamp ──────────────────────
            #
            # CloudWatch uses milliseconds, Python uses seconds.
            # Multiply by 1000 to convert.
            timestamp_ms = int(record.created * 1000)

            # ── Build the put_log_events call ─────────────
            kwargs = {
                "logGroupName": self.log_group,
                "logStreamName": self.log_stream,
                "logEvents": [
                    {
                        "timestamp": timestamp_ms,
                        "message": log_message
                    }
                ]
            }

            # ── Include sequence token after first send ───
            #
            # First call: no sequence token needed
            # Subsequent calls: must include token from previous response
            if self.sequence_token:
                kwargs["sequenceToken"] = self.sequence_token

            # ── Send to CloudWatch ────────────────────────
            response = self.client.put_log_events(**kwargs)

            # ── Save next sequence token ──────────────────
            self.sequence_token = response.get("nextSequenceToken")

        except Exception as e:
            # Never let CloudWatch errors crash your app
            # If CloudWatch is down, logs still go to console
            print(f"CloudWatch emit error: {e}")


def setup_cloudwatch_logging() -> None:
    """
    Adds CloudWatch handler to the root logger.

    Called once at app startup in main.py lifespan.

    After this call, every logger.info/warning/error
    in the entire app automatically sends to CloudWatch
    in addition to the console.

    Only enables in non-development environments to avoid
    sending dev noise to CloudWatch.
    """
    if settings.app_env == "development":
        logger.info("CloudWatch logging disabled in development mode")
        return

    try:
        # ── Add CloudWatch handler to root logger ─────────
        #
        # The root logger is the parent of all other loggers.
        # Adding a handler here means ALL loggers in the app
        # send to CloudWatch — no need to add it to each one.
        root_logger = logging.getLogger()
        cw_handler = CloudWatchHandler()
        root_logger.addHandler(cw_handler)

        logger.info(
            "cloudwatch_logging_enabled",
            extra={"log_group": f"/finmarket/{settings.app_env}"}
        )

    except Exception as e:
        # CloudWatch failure should never stop the app from starting
        logger.warning(f"CloudWatch setup failed: {e}. Logging to console only.")