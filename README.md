# COVID Vaccine Slot Alerts

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform: AWS Lambda](https://img.shields.io/badge/platform-AWS%20Lambda-orange.svg)](https://aws.amazon.com/lambda/)

An AWS Lambda function that watches India's [Co-WIN](https://www.cowin.gov.in/home)
public API for open COVID-19 vaccination slots in a district and emails you the
moment they appear.

## What it does

During the vaccine shortage it was very hard to find open slots for the 18–45 age
group — they would appear and fill within minutes. The Government of India
released the [Co-WIN API](https://apisetu.gov.in/public/marketplace/api/cowin/cowin-protected-v2#/Vaccination%20Appointment%20APIs/calendarByDistrict),
which exposes nearly everything the Co-WIN website does.

This project polls that API on a schedule and, whenever a session opens for a
configured minimum age with available capacity, publishes a summary to an
[Amazon SNS](https://aws.amazon.com/sns/) topic. SNS then fans the alert out to
your subscribed email (or SMS), so you can book before the slot fills.

## Architecture

```
┌──────────────┐   every minute   ┌──────────────┐   HTTPS    ┌──────────────┐
│ EventBridge  │ ───────────────▶ │    Lambda    │ ─────────▶ │  Co-WIN API  │
│  (schedule)  │                  │  vaccine.py  │ ◀───────── │              │
└──────────────┘                  └──────┬───────┘  sessions  └──────────────┘
                                         │ slots found?
                                         ▼
                                  ┌──────────────┐   email/SMS   ┌──────────┐
                                  │   SNS topic  │ ────────────▶ │   You    │
                                  └──────────────┘               └──────────┘
```

1. **Amazon EventBridge** triggers the Lambda on a fixed schedule (e.g. every minute).
2. The **Lambda** (`vaccine.py`) queries the Co-WIN calendar-by-district endpoint
   for today's date.
3. It filters sessions by minimum age and available capacity.
4. If any slots are open, it **publishes** a summary to an **SNS topic**, which
   notifies your subscribers.

## Prerequisites

- An AWS account.
- Python 3.9+ (for local development and tests).
- An SNS topic with at least one confirmed subscription (email or SMS).
- The **district ID** you want to monitor (see below).

## Configuration

All configuration is read from environment variables on the Lambda function:

| Variable        | Required | Default            | Description                                              |
| --------------- | -------- | ------------------ | -------------------------------------------------------- |
| `DISTRICT_ID`   | Yes      | —                  | Co-WIN district ID to monitor.                           |
| `SNS_TOPIC_ARN` | Yes      | —                  | ARN of the SNS topic to publish alerts to.              |
| `MIN_AGE`       | No       | `18`               | Minimum age limit of sessions to alert on (`18` or `45`).|
| `COWIN_HOST`    | No       | `cdn-api.co-vin.in`| Co-WIN API host (rarely needs changing).                |

### Finding your district ID

The Co-WIN API exposes the IDs through two public endpoints
(see the [API reference](https://apisetu.gov.in/public/marketplace/api/cowin/)):

1. **List states:** `GET https://cdn-api.co-vin.in/api/v2/admin/location/states`
2. **List districts in a state:** `GET https://cdn-api.co-vin.in/api/v2/admin/location/districts/{state_id}`

Find your district in the second response and use its `district_id`.

## Deployment

### 1. Create and subscribe to an SNS topic

```bash
aws sns create-topic --name vaccine-slot-alerts
aws sns subscribe \
  --topic-arn arn:aws:sns:<region>:<account-id>:vaccine-slot-alerts \
  --protocol email \
  --notification-endpoint you@example.com
```

Confirm the subscription via the email AWS sends you. Note the topic ARN.

### 2. Create the Lambda function

Package the handler and deploy it. `boto3` is already available in the Lambda
Python runtime, so the zip only needs `vaccine.py`:

```bash
zip function.zip vaccine.py

aws lambda create-function \
  --function-name vaccine-slot-alerts \
  --runtime python3.11 \
  --handler vaccine.lambda_handler \
  --role arn:aws:iam::<account-id>:role/<lambda-execution-role> \
  --zip-file fileb://function.zip
```

The execution role needs permission to publish to your SNS topic
(`sns:Publish`) in addition to the basic Lambda logging permissions.

### 3. Set the environment variables

```bash
aws lambda update-function-configuration \
  --function-name vaccine-slot-alerts \
  --environment "Variables={DISTRICT_ID=<id>,SNS_TOPIC_ARN=<topic-arn>,MIN_AGE=18}"
```

### 4. Schedule it with EventBridge

Create a rule that runs the function on a fixed rate (here, every minute) and add
the Lambda as its target:

```bash
aws events put-rule \
  --name vaccine-slot-alerts-schedule \
  --schedule-expression "rate(1 minute)"
```

Then add the Lambda as the rule's target and grant EventBridge permission to
invoke it (via `aws lambda add-permission` and `aws events put-targets`).

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

The core slot-filtering and message-formatting logic is implemented as small,
pure functions in `vaccine.py`, so it is fully unit tested without any AWS calls.

## Example notification

```
City Hospital - 12 Main Road - 560001 - 17-06-2026 - 25 slots
Community Clinic - 9 Park Street - 560002 - 17-06-2026 - 3 slots
```

## License

Released under the [MIT License](LICENSE).
