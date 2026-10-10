"""Tests for the AWS Lambda entry points. Sync tests: the handlers run asyncio.run themselves, like on Lambda."""
import base64
import json
import os
import time
from unittest.mock import MagicMock

import pytest

import bot as bot_module
import lambda_handlers
import tasks
from conftest import ITEM_ID, OWNER_ID, RECEIPT_ID, load_receipt, queued_receipts, texts

SECRET = os.environ["WEBHOOK_SECRET"]


def telegram_event(update: dict, secret: str | None = SECRET, base64_body: bool = False) -> dict:
    """Builds a Lambda Function URL event like the one Telegram's webhook call produces."""
    body = json.dumps(update)
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    if base64_body:
        body = base64.b64encode(body.encode()).decode()
    return {"headers": headers, "body": body, "isBase64Encoded": base64_body}


def message_update(update_id: int, user_id: int, text: str) -> dict:
    message = {
        "message_id": update_id,
        "date": int(time.time()),
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": f"Name{user_id}"},
        "text": text,
    }
    if text.startswith("/"):
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return {"update_id": update_id, "message": message}


def callback_update(update_id: int, user_id: int, data: str) -> dict:
    return {"update_id": update_id, "callback_query": {
        "id": str(update_id),
        "from": {"id": user_id, "is_bot": False, "first_name": f"Name{user_id}"},
        "chat_instance": "test",
        "data": data,
        "message": {"message_id": 50, "date": int(time.time()),
                    "chat": {"id": user_id, "type": "private"}, "text": "receipt card"},
    }}


@pytest.fixture
def lambda_bot(tg, monkeypatch):
    """Makes the webhook handler use the offline test bot; returns the harness to inspect what was sent."""
    monkeypatch.setattr(bot_module, "create_bot", lambda: tg.bot)
    tg.session.calls.clear()
    return tg


# --- webhook ---

def test_webhook_handles_a_command(lambda_bot):
    response = lambda_handlers.webhook(telegram_event(message_update(1, OWNER_ID, "/start")), None)
    assert response["statusCode"] == 200
    assert any("Hi!" in t for t in texts(lambda_bot.session.calls))


def test_webhook_accepts_base64_bodies(lambda_bot):
    response = lambda_handlers.webhook(telegram_event(message_update(1, OWNER_ID, "/start"), base64_body=True), None)
    assert response["statusCode"] == 200
    assert any("Hi!" in t for t in texts(lambda_bot.session.calls))


@pytest.mark.parametrize("secret", [None, "", "wrong-secret"])
def test_webhook_rejects_requests_without_the_secret(lambda_bot, secret):
    response = lambda_handlers.webhook(telegram_event(message_update(1, OWNER_ID, "/start"), secret=secret), None)
    assert response["statusCode"] == 403
    assert lambda_bot.session.calls == []


def test_webhook_rejects_invalid_json(lambda_bot):
    event = {"headers": {"x-telegram-bot-api-secret-token": SECRET}, "body": "not json"}
    assert lambda_handlers.webhook(event, None)["statusCode"] == 400


def test_webhook_answers_200_even_if_handling_fails(lambda_bot, monkeypatch):
    async def broken_feed(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(bot_module.dp, "feed_update", broken_feed)
    response = lambda_handlers.webhook(telegram_event(message_update(1, OWNER_ID, "/start")), None)
    assert response["statusCode"] == 200  # otherwise Telegram redelivers the update forever


def test_edit_flow_survives_separate_lambda_invocations(lambda_bot):
    """FSM state is in the DB, so a new invocation (a new process on Lambda) continues the conversation."""
    lambda_handlers.webhook(telegram_event(callback_update(1, OWNER_ID, f"edit_item_field:name:{ITEM_ID}:{RECEIPT_ID}")), None)
    lambda_handlers.webhook(telegram_event(message_update(2, OWNER_ID, "oat milk")), None)

    import asyncio
    assert asyncio.run(load_receipt(RECEIPT_ID)).items[0].name == "oat milk"


def test_manual_expense_flow_across_invocations(lambda_bot):
    lambda_handlers.webhook(telegram_event(message_update(1, OWNER_ID, "➕ Add expense")), None)
    lambda_handlers.webhook(telegram_event(message_update(2, OWNER_ID, "99")), None)
    lambda_handlers.webhook(telegram_event(callback_update(3, OWNER_ID, "manual_cat:Transport")), None)
    lambda_handlers.webhook(telegram_event(callback_update(4, OWNER_ID, "manual_skip_description")), None)
    assert any("Expense saved" in t for t in texts(lambda_bot.session.calls))


# --- photo -> SQS ---

def test_photo_is_uploaded_to_s3_and_queued_in_sqs(lambda_bot, aws, storage, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def download_file(file_path, destination):
        destination.write(b"jpeg-bytes")

    monkeypatch.setattr(lambda_bot.bot, "get_file", AsyncMock(return_value=SimpleNamespace(file_path="p.jpg")))
    monkeypatch.setattr(lambda_bot.bot, "download_file", download_file)

    update = message_update(1, OWNER_ID, "")
    del update["message"]["text"]
    update["message"]["photo"] = [{"file_id": "f1", "file_unique_id": "u1", "width": 800, "height": 1200}]
    lambda_handlers.webhook(telegram_event(update), None)

    assert f"{OWNER_ID}/u1.jpg" in storage.keys()
    assert queued_receipts(aws) == [{"blob_name": f"{OWNER_ID}/u1.jpg", "chat_id": OWNER_ID, "user_id": OWNER_ID}]


# --- worker ---

def sqs_event(body: dict | str, receive_count: int = 1, message_id: str = "m1") -> dict:
    return {"Records": [{
        "messageId": message_id,
        "receiptHandle": "handle-1",
        "body": body if isinstance(body, str) else json.dumps(body),
        "attributes": {"ApproximateReceiveCount": str(receive_count)},
    }]}


def test_worker_processes_a_receipt_with_the_receive_count_as_attempt(monkeypatch):
    process = MagicMock(return_value={"status": "completed"})
    monkeypatch.setattr(tasks, "process_receipt", process)

    result = lambda_handlers.worker(sqs_event({"blob_name": "1/a.jpg", "chat_id": -5, "user_id": 1}, receive_count=2), None)

    assert result == {"batchItemFailures": []}
    process.assert_called_once_with("1/a.jpg", -5, 1, attempt=2)


def test_worker_retries_transient_failures_soon(monkeypatch):
    monkeypatch.setattr(tasks, "process_receipt", MagicMock(side_effect=tasks.RetryLater("busy")))
    retry_later = MagicMock()
    import receipt_queue
    monkeypatch.setattr(receipt_queue, "retry_later", retry_later)

    result = lambda_handlers.worker(sqs_event({"blob_name": "1/a.jpg", "chat_id": 1, "user_id": 1}), None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    retry_later.assert_called_once_with("handle-1", tasks.RETRY_DELAY_SECONDS)


def test_worker_retries_crashes_via_sqs(monkeypatch):
    monkeypatch.setattr(tasks, "process_receipt", MagicMock(side_effect=RuntimeError("boom")))
    result = lambda_handlers.worker(sqs_event({"blob_name": "1/a.jpg", "chat_id": 1}), None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m1"}]}


@pytest.mark.parametrize("body", ["not json", {"chat_id": 1}, {"blob_name": "x"}, {"blob_name": "x", "chat_id": "abc"}])
def test_worker_drops_malformed_messages(monkeypatch, body):
    process = MagicMock()
    monkeypatch.setattr(tasks, "process_receipt", process)
    assert lambda_handlers.worker(sqs_event(body), None) == {"batchItemFailures": []}
    process.assert_not_called()


def test_retry_later_shortens_the_visibility_timeout(aws):
    import receipt_queue

    queue_url = os.environ["RECEIPTS_QUEUE_URL"]
    aws["sqs"].send_message(QueueUrl=queue_url, MessageBody="{}")
    message = aws["sqs"].receive_message(QueueUrl=queue_url, VisibilityTimeout=600)["Messages"][0]

    receipt_queue.retry_later(message["ReceiptHandle"], 0)
    assert aws["sqs"].receive_message(QueueUrl=queue_url).get("Messages")  # visible again right away


def test_max_attempts_leave_room_for_the_final_message():
    # The queue's maxReceiveCount (Terraform) must exceed MAX_ATTEMPTS; the test documents the contract
    assert tasks.MAX_ATTEMPTS >= 2 and tasks.RETRY_DELAY_SECONDS < 60


# --- migrate & config ---

def test_migrate_runs_alembic(monkeypatch):
    import db.migrations

    run = MagicMock()
    monkeypatch.setattr(db.migrations, "run_migrations", run)
    assert lambda_handlers.migrate({}, None) == {"status": "ok"}
    run.assert_called_once()


def test_ssm_parameters_fill_missing_env_vars(aws, monkeypatch):
    import boto3

    from config import load_ssm_parameters

    ssm = boto3.client("ssm")
    ssm.put_parameter(Name="/receipt-scanner/TEST_ONLY_SECRET", Value="from-ssm", Type="SecureString")
    ssm.put_parameter(Name="/receipt-scanner/TEST_ONLY_PRESET", Value="from-ssm", Type="SecureString")
    monkeypatch.setenv("SSM_PARAMETER_PREFIX", "/receipt-scanner")
    monkeypatch.delenv("TEST_ONLY_SECRET", raising=False)
    monkeypatch.setenv("TEST_ONLY_PRESET", "from-env")

    load_ssm_parameters()

    assert os.environ["TEST_ONLY_SECRET"] == "from-ssm"
    assert os.environ["TEST_ONLY_PRESET"] == "from-env"  # explicit env vars win
    monkeypatch.delenv("TEST_ONLY_SECRET")


def test_ssm_is_not_used_without_a_prefix(monkeypatch):
    from config import load_ssm_parameters

    monkeypatch.delenv("SSM_PARAMETER_PREFIX", raising=False)
    load_ssm_parameters()  # must not try to reach AWS
