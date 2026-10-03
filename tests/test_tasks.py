"""Tests for the Celery receipt-processing task. These are sync tests because the task calls asyncio.run itself."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai.errors import ClientError, ServerError

import tasks
from conftest import load_receipt
from schemas import ReceiptData

CHAT_ID = 1
BLOB = "1/photo.jpg"


@pytest.fixture
def sent(monkeypatch):
    """Stubs Azure download and Telegram sending; returns the list of messages sent to the user."""
    blob_client = MagicMock()
    blob_client.download_blob.return_value.readall.return_value = b"image-bytes"
    monkeypatch.setattr(tasks.blob_service_client, "get_blob_client", MagicMock(return_value=blob_client))

    messages = []

    async def fake_send(chat_id, text, reply_markup=None):
        messages.append(text)

    monkeypatch.setattr(tasks, "_send_telegram_msg", fake_send)
    return messages


def _run_task(retries: int = 0):
    """Runs the task body directly with the given retry counter, as a worker would."""
    tasks.process_receipt_task.push_request(retries=retries)
    try:
        return tasks.process_receipt_task.run(BLOB, CHAT_ID)
    finally:
        tasks.process_receipt_task.pop_request()


def _overloaded():
    return ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})


def test_503_schedules_retry_while_budget_left(monkeypatch, sent):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=_overloaded()))
    retry = MagicMock(side_effect=RuntimeError("retry scheduled"))
    monkeypatch.setattr(tasks.process_receipt_task, "retry", retry)

    with pytest.raises(RuntimeError, match="retry scheduled"):
        _run_task(retries=0)
    assert retry.call_args.kwargs["countdown"] == 3
    assert sent == []


def test_503_after_last_retry_notifies_user(monkeypatch, sent):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=_overloaded()))
    retry = MagicMock()
    monkeypatch.setattr(tasks.process_receipt_task, "retry", retry)

    result = _run_task(retries=tasks.process_receipt_task.max_retries)
    assert result["status"] == "failed"
    retry.assert_not_called()
    assert len(sent) == 1 and "overloaded" in sent[0]


def test_primary_model_503_falls_back_to_secondary(monkeypatch, sent):
    receipt = ReceiptData(is_receipt=False, total_amount=0, items=[])
    analyze = MagicMock(side_effect=[_overloaded(), receipt])
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", analyze)

    _run_task()
    assert analyze.call_args_list[1].kwargs["model_name"] == tasks.FALLBACK_MODEL
    assert len(sent) == 1 and "doesn't look like a receipt" in sent[0]


def test_unexpected_error_does_not_leak_details(monkeypatch, sent):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini",
                        MagicMock(side_effect=RuntimeError("password=hunter2 at db-host")))
    _run_task()
    assert len(sent) == 1
    assert "hunter2" not in sent[0] and "db-host" not in sent[0]


def test_api_error_does_not_leak_details(monkeypatch, sent):
    error = ClientError(400, {"error": {"code": 400, "message": "secret-request-id-42", "status": "INVALID_ARGUMENT"}})
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=error))
    _run_task()
    assert len(sent) == 1 and "secret-request-id-42" not in sent[0]


def test_successful_receipt_is_saved_and_sent_with_keyboard(db, monkeypatch):
    receipt = ReceiptData(store_name="<Shop>", currency="CZK", total_amount=0.3, items=[
        {"name": "milk", "total_price": 0.3, "category": "Groceries"},
    ])
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)

    # The db fixture is async; run the sync pipeline in a fresh loop like the worker does
    asyncio.run(tasks._process_and_notify_pipeline(CHAT_ID, "new-blob", receipt))

    text = send.call_args.args[1]
    keyboard = send.call_args.kwargs["reply_markup"]
    assert "&lt;Shop&gt;" in text and "0.30 CZK" in text
    receipt_id = int(keyboard.inline_keyboard[0][0].callback_data.split(":")[1])
    assert asyncio.run(load_receipt(receipt_id)).store_name == "<Shop>"
