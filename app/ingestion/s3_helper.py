# path: app/ingestion/s3_helper.py

# =========================================================
# S3 HELPER — Raw Data Archival
# =========================================================
#
# What is S3 in this context?
#
# Before processing any data, we save the raw version
# to S3. This is called a "data lake" pattern.
#
# Why save raw data at all?
#
# Imagine your ML model in Phase 3 has a bug that
# corrupts your processed data. Without the raw archive,
# that data is gone forever.
#
# With S3 archive: you can always go back to the raw
# data and reprocess it correctly.
#
# S3 folder structure:
# finmarket-raw-data-palash/
# ├── prices/
# │   └── 2024-01-15/
# │       └── AAPL_093000.json
# ├── news/
# │   └── 2024-01-15/
# │       └── batch_093000.json
# └── reddit/
#     └── 2024-01-15/
#         └── batch_093000.json

import json
import boto3
from datetime import datetime, timezone
from botocore.exceptions import ClientError
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class S3Helper:
    """
    Handles all S3 operations for raw data archival.

    In plain English: a filing clerk that saves every
    piece of raw data to S3 before we process it.
    """

    def __init__(self):
        # boto3.client creates an AWS S3 connection
        # using credentials from your .env file
        self.client = boto3.client(
            "s3",
            region_name=settings.aws_default_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
        self.bucket = settings.s3_bucket_name

    def save_raw_data(
        self,
        data: dict | list,
        data_type: str,
        identifier: str
    ) -> str:
        """
        Saves raw data to S3 and returns the S3 path.

        Args:
            data:       the raw data to save (dict or list)
            data_type:  folder name — "prices", "news", "reddit"
            identifier: file identifier — symbol or batch name

        Returns:
            S3 path like "prices/2024-01-15/AAPL_093000.json"

        In plain English:
            Takes your data, converts it to JSON,
            and files it away in S3 under a dated folder.
        """
        now = datetime.now(timezone.utc)

        # Build the S3 key (path within the bucket)
        # Example: "prices/2024-01-15/AAPL_093000.json"
        s3_key = (
            f"{data_type}/"
            f"{now.strftime('%Y-%m-%d')}/"
            f"{identifier}_{now.strftime('%H%M%S')}.json"
        )

        try:
            # Convert data to JSON string and upload
            # json.dumps: converts Python dict/list → JSON string
            self.client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=json.dumps(data, default=str),
                ContentType="application/json"
            )

            logger.info(
                "s3_upload_success",
                extra={"s3_key": s3_key, "data_type": data_type}
            )
            return s3_key

        except ClientError as e:
            logger.error(
                "s3_upload_error",
                extra={"error": str(e), "s3_key": s3_key}
            )
            raise

    def read_raw_data(self, s3_key: str) -> dict | list:
        """
        Reads raw data back from S3.

        Useful when you need to reprocess historical data.
        """
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=s3_key
            )
            # response["Body"].read() gets the file bytes
            # .decode("utf-8") converts bytes to string
            # json.loads() converts string to Python dict
            return json.loads(response["Body"].read().decode("utf-8"))

        except ClientError as e:
            logger.error(f"s3_read_error: {e}")
            raise


# Single instance used across the app
# Like session.py — created once, shared everywhere
s3_helper = S3Helper()