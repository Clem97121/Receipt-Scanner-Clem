"""Tests for the Celery receipt-processing task. These are sync tests because the task calls asyncio.run itself."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai.errors import ClientError, ServerError
from sqlalchemy import select

import tasks
from conftest import load_receipt
from db.models import Receipt
from schemas import ReceiptData

CHAT_ID = 1
BLOB = "1/photo.jpg"


@pytest.fixture
def sent(monkeypatch):
    """Stubs Telegram sending; returns the list of messages sent to the user (storage is faked in conftest)."""
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


def test_503_schedules_retry_while_budget_left(monkeypatch, sent, storage):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=_overloaded()))
    retry = MagicMock(side_effect=RuntimeError("retry scheduled"))
    monkeypatch.setattr(tasks.process_receipt_task, "retry", retry)

    with pytest.raises(RuntimeError, match="retry scheduled"):
        _run_task(retries=0)
    assert retry.call_args.kwargs["countdown"] == 3
    assert sent == []
    assert storage.deleted == []  # the photo is still needed for the retry


def test_503_after_last_retry_notifies_user(monkeypatch, sent, storage):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=_overloaded()))
    retry = MagicMock()
    monkeypatch.setattr(tasks.process_receipt_task, "retry", retry)

    result = _run_task(retries=tasks.process_receipt_task.max_retries)
    assert result["status"] == "failed"
    retry.assert_not_called()
    assert len(sent) == 1 and "overloaded" in sent[0]
    assert storage.deleted == [BLOB]


def test_primary_model_503_falls_back_to_secondary(monkeypatch, sent, storage):
    receipt = ReceiptData(is_receipt=False, total_amount=0, items=[])
    analyze = MagicMock(side_effect=[_overloaded(), receipt])
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", analyze)

    _run_task()
    assert analyze.call_args_list[1].kwargs["model_name"] == tasks.FALLBACK_MODEL
    assert len(sent) == 1 and "doesn't look like a receipt" in sent[0]
    assert storage.deleted == [BLOB]  # non-receipt photos (selfies etc.) are not kept


def test_unexpected_error_does_not_leak_details(monkeypatch, sent, storage):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini",
                        MagicMock(side_effect=RuntimeError("password=hunter2 at db-host")))
    _run_task()
    assert len(sent) == 1
    assert "hunter2" not in sent[0] and "db-host" not in sent[0]
    assert storage.deleted == []  # the receipt may already be saved, so the photo is kept


def test_api_error_does_not_leak_details(monkeypatch, sent, storage):
    error = ClientError(400, {"error": {"code": 400, "message": "secret-request-id-42", "status": "INVALID_ARGUMENT"}})
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=error))
    _run_task()
    assert len(sent) == 1 and "secret-request-id-42" not in sent[0]
    assert storage.deleted == [BLOB]


def test_unreliable_ai_numbers_are_not_saved(db, monkeypatch, storage):
    receipt = ReceiptData(store_name="Bad", currency="CZK", total_amount=-5, items=[
        {"name": "milk", "total_price": 1e12, "category": "Groceries"},
    ])
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)

    asyncio.run(tasks._process_and_notify_pipeline(CHAT_ID, CHAT_ID, "bad-blob", receipt))

    assert "couldn't read the amounts" in send.call_args.args[1]
    assert send.call_args.kwargs.get("reply_markup") is None

    async def receipts_with_blob():
        async with tasks.AsyncSessionLocal() as session:
            return (await session.execute(
                select(Receipt).where(Receipt.blob_name == "bad-blob")
            )).scalars().all()

    assert asyncio.run(receipts_with_blob()) == []
    assert storage.deleted == ["bad-blob"]


def test_successful_receipt_is_saved_and_sent_with_keyboard(db, monkeypatch, storage):
    receipt = ReceiptData(store_name="<Shop>", currency="CZK", total_amount=0.3, items=[
        {"name": "milk", "total_price": 0.3, "category": "Groceries"},
    ])
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)

    # The db fixture is async; run the sync pipeline in a fresh loop like the worker does
    asyncio.run(tasks._process_and_notify_pipeline(CHAT_ID, CHAT_ID, "new-blob", receipt))

    text = send.call_args.args[1]
    keyboard = send.call_args.kwargs["reply_markup"]
    assert "&lt;Shop&gt;" in text and "0.30 CZK" in text
    receipt_id = int(keyboard.inline_keyboard[0][0].callback_data.split(":")[1])
    assert asyncio.run(load_receipt(receipt_id)).store_name == "<Shop>"
    assert storage.deleted == []


def test_group_receipt_is_saved_for_the_sender_and_reply_goes_to_the_group(db, monkeypatch):
    receipt = ReceiptData(store_name="Shop", currency="CZK", total_amount=1, items=[
        {"name": "milk", "total_price": 1, "category": "Groceries"},
    ])
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(return_value=receipt))
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)

    tasks.process_receipt_task.push_request(retries=0)
    try:
        tasks.process_receipt_task.run("1/group-photo.jpg", -100500, 1)
    finally:
        tasks.process_receipt_task.pop_request()

    assert send.call_args.args[0] == -100500
    receipt_id = int(send.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[1])
    assert asyncio.run(load_receipt(receipt_id)).user_id == 1


def test_task_queued_by_old_bot_version_falls_back_to_chat_id(db, monkeypatch):
    receipt = ReceiptData(currency="CZK", total_amount=1, items=[])
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(return_value=receipt))
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)

    tasks.process_receipt_task.push_request(retries=0)
    try:
        tasks.process_receipt_task.run("1/old-task.jpg", 1)
    finally:
        tasks.process_receipt_task.pop_request()

    receipt_id = int(send.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[1])
    assert asyncio.run(load_receipt(receipt_id)).user_id == 1


def test_gemini_requests_have_a_timeout():
    assert tasks.ai_client._api_client._http_options.timeout == tasks.GEMINI_TIMEOUT_MS
    assert tasks.process_receipt_task.time_limit and tasks.process_receipt_task.soft_time_limit
