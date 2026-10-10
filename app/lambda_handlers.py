"""AWS Lambda entry points. One container image, three functions selected by the image command:

- lambda_handlers.webhook  — Telegram webhook behind a Lambda Function URL
- lambda_handlers.worker   — SQS-triggered receipt recognition (replaces the Celery worker)
- lambda_handlers.migrate  — runs Alembic migrations; invoked once per deploy, before switching traffic
"""
import asyncio
import base64
import hmac
import json
import logging
import os

from config import load_ssm_parameters

# Secrets must be in os.environ before importing modules that read them at import time
load_ssm_parameters()

logging.getLogger().setLevel(logging.INFO)

TELEGRAM_SECRET_HEADER = "x-telegram-bot-api-secret-token"


def _response(status_code: int, body: str = "") -> dict:
    return {"statusCode": status_code, "body": body}


def webhook(event, context):
    """Handles one Telegram update delivered to the Function URL.

    Always answers 200 for authentic updates, even if handling failed: otherwise Telegram keeps
    redelivering the same update and blocks the ones behind it.
    """
    headers = {name.lower(): value for name, value in (event.get("headers") or {}).items()}
    expected_secret = os.environ.get("WEBHOOK_SECRET", "")
    received_secret = headers.get(TELEGRAM_SECRET_HEADER, "")
    if not expected_secret or not hmac.compare_digest(received_secret, expected_secret):
        logging.warning("[Webhook] Rejected a request without a valid secret token")
        return _response(403, "forbidden")

    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    try:
        update = json.loads(body)
    except json.JSONDecodeError:
        logging.warning("[Webhook] Request body is not valid JSON")
        return _response(400, "bad request")

    asyncio.run(_feed_update(update))
    return _response(200, "ok")


async def _feed_update(update: dict) -> None:
    from aiogram.types import Update

    from bot import create_bot, dp

    bot = create_bot()
    try:
        await dp.feed_update(bot, Update.model_validate(update, context={"bot": bot}))
    except Exception:
        logging.exception(f"[Webhook] Failed to handle update {update.get('update_id')}")
    finally:
        await bot.session.close()


def worker(event, context):
    """Processes receipts from SQS (batch size 1 in production).

    Returns partial batch failures: a message is retried when the AI failed transiently
    (after RETRY_DELAY_SECONDS) or when processing crashed; malformed messages are dropped.
    """
    from receipt_queue import retry_later
    from tasks import RETRY_DELAY_SECONDS, RetryLater, process_receipt

    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            payload = json.loads(record["body"])
            blob_name, chat_id = payload["blob_name"], int(payload["chat_id"])
            user_id = int(payload["user_id"]) if payload.get("user_id") else None
        except (KeyError, TypeError, ValueError):
            logging.exception(f"[Worker] Dropping malformed SQS message {message_id}")
            continue

        attempt = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
        try:
            process_receipt(blob_name, chat_id, user_id, attempt=attempt)
        except RetryLater:
            try:
                retry_later(record["receiptHandle"], RETRY_DELAY_SECONDS)
            except Exception:
                logging.exception(f"[Worker] Could not shorten the retry delay for message {message_id}")
            failures.append({"itemIdentifier": message_id})
        except Exception:
            logging.exception(f"[Worker] Crashed while processing message {message_id}; SQS will redeliver it")
            failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failures}


def migrate(event, context):
    """Upgrades the database schema to the latest Alembic revision."""
    from db.migrations import run_migrations

    run_migrations()
    return {"status": "ok"}
