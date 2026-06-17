"""AWS Lambda function that alerts on open COVID-19 vaccine slots.

The handler queries India's Co-WIN public API for vaccination sessions in a
configured district, filters for slots that are open to a given minimum age and
have available capacity, and publishes a summary to an Amazon SNS topic (which
typically fans out to email/SMS subscribers).

It is designed to be triggered on a schedule (for example, once a minute) by
Amazon EventBridge. All configuration is supplied through environment variables;
see the README for deployment details.
"""

import http.client
import json
import logging
import os
from datetime import date

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Co-WIN rejects requests that do not send a browser-like User-Agent header.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_CALENDAR_PATH = "/api/v2/appointment/sessions/public/calendarByDistrict"


def get_config():
    """Read and validate configuration from environment variables.

    Returns a dict with ``district_id``, ``topic_arn``, ``min_age`` and
    ``host``. Raises ``ValueError`` if a required variable is missing.
    """
    district_id = os.environ.get("DISTRICT_ID")
    topic_arn = os.environ.get("SNS_TOPIC_ARN")

    missing = [
        name
        for name, value in (("DISTRICT_ID", district_id), ("SNS_TOPIC_ARN", topic_arn))
        if not value
    ]
    if missing:
        raise ValueError(
            "Missing required environment variable(s): " + ", ".join(missing)
        )

    return {
        "district_id": district_id,
        "topic_arn": topic_arn,
        "min_age": int(os.environ.get("MIN_AGE", "18")),
        "host": os.environ.get("COWIN_HOST", "cdn-api.co-vin.in"),
    }


def get_today():
    """Return today's date formatted as ``dd-mm-YYYY`` (the Co-WIN format)."""
    return date.today().strftime("%d-%m-%Y")


def fetch_sessions(host, district_id, on_date):
    """Fetch vaccination sessions for a district on a given date.

    Returns the parsed JSON payload from the Co-WIN calendar-by-district
    endpoint. Raises ``RuntimeError`` on a non-200 response and
    ``json.JSONDecodeError`` if the body is not valid JSON.
    """
    conn = http.client.HTTPSConnection(host)
    try:
        url = f"{_CALENDAR_PATH}?district_id={district_id}&date={on_date}"
        conn.request("GET", url, headers={"User-Agent": _USER_AGENT})
        response = conn.getresponse()
        body = response.read().decode("utf-8")
        if response.status != 200:
            raise RuntimeError(
                f"Co-WIN API returned HTTP {response.status}: {body[:200]}"
            )
        return json.loads(body)
    finally:
        conn.close()


def filter_available_slots(data, min_age):
    """Return a list of open slots from a Co-WIN calendar payload.

    A slot is included when its session is open to ``min_age`` and has
    available capacity. Each returned item is a flat dict describing the
    center and session.
    """
    slots = []
    for center in data.get("centers", []):
        for session in center.get("sessions", []):
            if (
                session.get("min_age_limit") == min_age
                and session.get("available_capacity", 0) > 0
            ):
                slots.append(
                    {
                        "name": center.get("name", ""),
                        "address": center.get("address", ""),
                        "pincode": center.get("pincode", ""),
                        "date": session.get("date", ""),
                        "available_capacity": session.get("available_capacity", 0),
                    }
                )
    return slots


def format_message(slots):
    """Render a human-readable notification body from a list of slots."""
    lines = [
        f"{slot['name']} - {slot['address']} - {slot['pincode']} - "
        f"{slot['date']} - {slot['available_capacity']} slots"
        for slot in slots
    ]
    return "\n".join(lines)


def publish(client, topic_arn, message):
    """Publish the slot summary to the configured SNS topic."""
    return client.publish(
        TopicArn=topic_arn,
        Message=message,
        Subject="Vaccine slots opened",
    )


def lambda_handler(event, context):
    """Entry point for AWS Lambda.

    Returns a dict describing the outcome. When no slots are open it returns
    gracefully without publishing.
    """
    config = get_config()

    data = fetch_sessions(config["host"], config["district_id"], get_today())
    slots = filter_available_slots(data, config["min_age"])

    if not slots:
        logger.info("No open slots found for district %s.", config["district_id"])
        return {"statusCode": 200, "slotsFound": 0, "published": False}

    message = format_message(slots)
    logger.info("Found %d open slot(s); publishing notification.", len(slots))
    publish(boto3.client("sns"), config["topic_arn"], message)

    return {"statusCode": 200, "slotsFound": len(slots), "published": True}
