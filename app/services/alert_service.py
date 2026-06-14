# =========================================================
# EMAIL ALERT SERVICE
# =========================================================
#
# What does this do in plain English?
#
# When the anomaly detector finds an unusual price move,
# this service sends an email notification via AWS SES.
#
# AWS SES (Simple Email Service):
# - Free tier: 3,000 emails per month forever
# - Requires verified email address in AWS console
# - We already set up SES credentials in Phase 1 (.env)
#
# ─────────────────────────────────────────────────────────
# HOW THIS FILE CONNECTS TO OTHER SCRIPTS:
#
# RDS anomalies table
#       ↓ anomalies where is_alerted = False
#       ↓ read by run_alert_check()
# AWS SES
#       ↓ sends email notification
# RDS anomalies.is_alerted = True
#       ↓ prevents duplicate alerts
# Celery scheduled task
#       ↓ runs every 15 minutes
# ─────────────────────────────────────────────────────────

import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.anomaly import Anomaly
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def send_anomaly_email(anomaly: Anomaly) -> bool:
    """
    Sends one anomaly alert email via AWS SES.

    Returns True if sent successfully, False if failed.

    Connection chain:
    Anomaly object (from RDS)
        ↓ formats into HTML email
        ↓ AWS SES client (boto3)
        ↓ delivers to SES_TO_EMAIL
    """
    if not settings.ses_from_email or not settings.ses_to_email:
        logger.warning("SES emails not configured in .env")
        return False

    # ── Build email content ───────────────────────────────
    severity_emoji = "🚨" if anomaly.severity == "high" else "⚠️"
    severity_color = "#E24B4A" if anomaly.severity == "high" else "#EF9F27"

    subject = (
        f"{severity_emoji} FinMarket Alert: "
        f"{anomaly.symbol} {anomaly.anomaly_type.replace('_', ' ').title()}"
    )

    # ── HTML email body ───────────────────────────────────
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">

        <div style="background: #0E1117; padding: 20px; border-radius: 8px;">
            <h2 style="color: {severity_color}; margin: 0;">
                {severity_emoji} Market Anomaly Detected
            </h2>
        </div>

        <div style="padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px; margin-top: 10px;">

            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px; font-weight: bold; color: #666;">Stock</td>
                    <td style="padding: 8px; font-size: 18px; font-weight: bold;">
                        {anomaly.symbol}
                    </td>
                </tr>
                <tr style="background: #f9f9f9;">
                    <td style="padding: 8px; font-weight: bold; color: #666;">Type</td>
                    <td style="padding: 8px;">
                        {anomaly.anomaly_type.replace('_', ' ').title()}
                    </td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold; color: #666;">Severity</td>
                    <td style="padding: 8px;">
                        <span style="
                            background: {severity_color};
                            color: white;
                            padding: 2px 8px;
                            border-radius: 4px;
                            font-size: 12px;
                            font-weight: bold;
                        ">
                            {anomaly.severity.upper()}
                        </span>
                    </td>
                </tr>
                <tr style="background: #f9f9f9;">
                    <td style="padding: 8px; font-weight: bold; color: #666;">Z-Score</td>
                    <td style="padding: 8px;">{anomaly.z_score:.2f}σ</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold; color: #666;">
                        Actual Value
                    </td>
                    <td style="padding: 8px;">${anomaly.actual_value:,.2f}</td>
                </tr>
                <tr style="background: #f9f9f9;">
                    <td style="padding: 8px; font-weight: bold; color: #666;">
                        Expected Value
                    </td>
                    <td style="padding: 8px;">${anomaly.expected_value:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold; color: #666;">
                        Detected At
                    </td>
                    <td style="padding: 8px;">{anomaly.detected_at[:19]} UTC</td>
                </tr>
            </table>

            <div style="
                background: #f5f5f5;
                padding: 12px;
                border-radius: 6px;
                margin-top: 16px;
            ">
                <strong>Description:</strong><br>
                {anomaly.description}
            </div>

            <div style="margin-top: 20px; text-align: center;">
                <a href="http://localhost:8501"
                   style="
                    background: #1D9E75;
                    color: white;
                    padding: 10px 20px;
                    border-radius: 6px;
                    text-decoration: none;
                    font-weight: bold;
                   ">
                    View Dashboard →
                </a>
            </div>
        </div>

        <p style="color: #999; font-size: 12px; text-align: center; margin-top: 16px;">
            FinMarket Intelligence Platform •
            Powered by AWS SES •
            <a href="#" style="color: #999;">Unsubscribe</a>
        </p>

    </body>
    </html>
    """

    # ── Plain text fallback ───────────────────────────────
    text_body = (
        f"FinMarket Alert: {anomaly.symbol}\n\n"
        f"Type: {anomaly.anomaly_type}\n"
        f"Severity: {anomaly.severity}\n"
        f"Z-Score: {anomaly.z_score:.2f}\n"
        f"Description: {anomaly.description}\n"
        f"Detected: {anomaly.detected_at[:19]} UTC\n"
    )

    try:
        # ── Send via AWS SES ──────────────────────────────
        #
        # boto3 SES client uses credentials from .env:
        # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
        # Same credentials set up in Phase 1
        ses_client = boto3.client(
            "ses",
            region_name=settings.aws_default_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )

        ses_client.send_email(
            Source=settings.ses_from_email,
            Destination={"ToAddresses": [settings.ses_to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body,  "Charset": "UTF-8"}
                }
            }
        )

        logger.info(
            "alert_email_sent",
            extra={
                "symbol":   anomaly.symbol,
                "type":     anomaly.anomaly_type,
                "severity": anomaly.severity
            }
        )
        return True

    except ClientError as e:
        logger.error(
            "ses_send_error",
            extra={"error": str(e)}
        )
        return False


def run_alert_check() -> dict:
    """
    Checks for unalerted anomalies and sends emails.

    Flow:
    ┌──────────────────────────────────────────────────┐
    │ 1. Query RDS for anomalies where is_alerted=False│
    │ 2. Send email for each via AWS SES               │
    │ 3. Set is_alerted=True to prevent duplicates     │
    └──────────────────────────────────────────────────┘

    Called by Celery every 15 minutes.
    Only sends HIGH severity alerts by default.
    """
    db = SessionLocal()
    sent = 0
    failed = 0

    try:
        # ── Get unalerted HIGH severity anomalies ─────────
        #
        # We only alert on HIGH severity to avoid
        # flooding your inbox with medium alerts.
        # Change severity filter to include "medium" if desired.
        unalerted = db.query(Anomaly).filter(
            Anomaly.is_alerted == False,
            Anomaly.severity   == "high"
        ).order_by(Anomaly.detected_at.desc()).all()

        if not unalerted:
            logger.info("no_unalerted_anomalies")
            return {"status": "no_alerts", "sent": 0}

        for anomaly in unalerted:
            success = send_anomaly_email(anomaly)

            if success:
                # ── Mark as alerted ───────────────────────
                anomaly.is_alerted = True
                sent += 1
            else:
                failed += 1

        db.commit()

        return {
            "status": "completed",
            "sent":   sent,
            "failed": failed
        }

    except Exception as e:
        db.rollback()
        logger.error(f"alert_check_error: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()