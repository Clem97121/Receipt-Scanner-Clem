"""Tests for receipt processing (run by the worker Lambda). Sync tests: process_receipt calls asyncio.run itself."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
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
def sent(monkeypatch, storage):
    """Seeds the photo in S3 and stubs Telegram sending; returns the list of messages sent to the user."""
    storage.put_photo(BLOB)
    messages = []

    async def fake_send(chat_id, text, reply_markup=None):
        messages.append(text)

    monkeypatch.setattr(tasks, "_send_telegram_msg", fake_send)
    return messages


def _run(attempt: int = 1):
    """Processes BLOB as the worker Lambda would on the given SQS receive count."""
    return tasks.process_receipt(BLOB, CHAT_ID, attempt=attempt)


def _overloaded():
    return ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})


def test_503_asks_for_a_retry_while_attempts_are_left(monkeypatch, sent, storage):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=_overloaded()))

    with pytest.raises(tasks.RetryLater):
        _run(attempt=1)
    assert len(sent) == 1 and "responding slowly" in sent[0]  # told once, on the first retry
    assert storage.deleted == []  # the photo is still needed for the retry


def test_second_attempt_does_not_repeat_the_slow_notice(monkeypatch, sent):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=_overloaded()))

    with pytest.raises(tasks.RetryLater):
        _run(attempt=2)
    assert sent == []


def test_503_on_last_attempt_notifies_user(monkeypatch, sent, storage):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=_overloaded()))

    result = _run(attempt=tasks.MAX_ATTEMPTS)
    assert result["status"] == "failed"
    assert len(sent) == 1 and "overloaded" in sent[0]
    assert storage.deleted == [BLOB]
    assert BLOB not in storage.keys()


def test_redelivery_beyond_max_attempts_is_still_final(monkeypatch, sent):
    # e.g. a Lambda timeout made SQS deliver the message once more than planned
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=_overloaded()))
    assert _run(attempt=tasks.MAX_ATTEMPTS + 1)["status"] == "failed"


def test_primary_model_503_falls_back_to_secondary(monkeypatch, sent, storage):
    receipt = ReceiptData(is_receipt=False, total_amount=0, items=[])
    analyze = MagicMock(side_effect=[_overloaded(), receipt])
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", analyze)

    _run()
    assert analyze.call_args_list[1].kwargs["model_name"] == tasks.FALLBACK_MODEL
    assert len(sent) == 1 and "doesn't look like a receipt" in sent[0]
    assert storage.deleted == [BLOB]  # non-receipt photos (selfies etc.) are not kept


def test_primary_timeout_falls_back_to_secondary(monkeypatch, sent):
    receipt = ReceiptData(is_receipt=False, total_amount=0, items=[])
    analyze = MagicMock(side_effect=[httpx.ReadTimeout("The read operation timed out"), receipt])
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", analyze)

    _run()
    assert analyze.call_args_list[1].kwargs["model_name"] == tasks.FALLBACK_MODEL
    assert len(sent) == 1 and "doesn't look like a receipt" in sent[0]


def test_photo_is_read_from_s3(monkeypatch, sent, storage):
    storage.put_photo(BLOB, b"real-jpeg-bytes")
    analyze = MagicMock(return_value=ReceiptData(is_receipt=False, total_amount=0, items=[]))
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", analyze)

    _run()
    assert analyze.call_args.args[0] == b"real-jpeg-bytes"


@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("The read operation timed out"),
    httpx.ConnectTimeout("connect timed out"),
    httpx.ConnectError("connection refused"),
    httpx.RemoteProtocolError("server disconnected"),
    ServerError(500, {"error": {"code": 500, "message": "internal", "status": "INTERNAL"}}),
    ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
])
def test_timeouts_and_network_errors_are_retried(monkeypatch, sent, storage, error):
    analyze = MagicMock(side_effect=error)
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", analyze)

    with pytest.raises(tasks.RetryLater):
        _run(attempt=1)
    assert analyze.call_count == 2  # primary + fallback before retrying
    assert all("Something went wrong" not in m for m in sent)
    assert storage.deleted == []


def test_timeouts_on_last_attempt_report_overload(monkeypatch, sent, storage):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=httpx.ReadTimeout("timed out")))
    result = _run(attempt=tasks.MAX_ATTEMPTS)
    assert result["status"] == "failed"
    assert len(sent) == 1 and "overloaded" in sent[0]
    assert storage.deleted == [BLOB]


def test_unexpected_error_does_not_leak_details(monkeypatch, sent, storage):
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini",
                        MagicMock(side_effect=RuntimeError("password=hunter2 at db-host")))
    _run()
    assert len(sent) == 1
    assert "hunter2" not in sent[0] and "db-host" not in sent[0]
    assert storage.deleted == []  # the receipt may already be saved, so the photo is kept


def test_missing_photo_is_reported_without_retry(monkeypatch, storage):
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)
    result = tasks.process_receipt("1/never-uploaded.jpg", CHAT_ID)
    assert result["status"] == "failed"
    assert "Something went wrong" in send.call_args.args[1]


def test_api_error_does_not_leak_details(monkeypatch, sent, storage):
    error = ClientError(400, {"error": {"code": 400, "message": "secret-request-id-42", "status": "INVALID_ARGUMENT"}})
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(side_effect=error))
    _run()
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


def test_group_receipt_is_saved_for_the_sender_and_reply_goes_to_the_group(db, monkeypatch, storage):
    receipt = ReceiptData(store_name="Shop", currency="CZK", total_amount=1, items=[
        {"name": "milk", "total_price": 1, "category": "Groceries"},
    ])
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(return_value=receipt))
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)
    storage.put_photo("1/group-photo.jpg")

    tasks.process_receipt("1/group-photo.jpg", -100500, 1)

    assert send.call_args.args[0] == -100500
    receipt_id = int(send.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[1])
    assert asyncio.run(load_receipt(receipt_id)).user_id == 1


def test_message_without_user_id_falls_back_to_chat_id(db, monkeypatch, storage):
    receipt = ReceiptData(currency="CZK", total_amount=1, items=[])
    monkeypatch.setattr(tasks, "analyze_receipt_with_gemini", MagicMock(return_value=receipt))
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)
    storage.put_photo("1/old-task.jpg")

    tasks.process_receipt("1/old-task.jpg", 1)

    receipt_id = int(send.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[1])
    assert asyncio.run(load_receipt(receipt_id)).user_id == 1


def test_gemini_requests_have_a_timeout():
    assert tasks.ai_client._api_client._http_options.timeout == tasks.GEMINI_TIMEOUT_MS


def test_receipt_with_discount_lines_is_saved_and_counted(db, monkeypatch, storage):
    from datetime import date
    from decimal import Decimal

    from db.crud import get_monthly_stats
    from db.database import AsyncSessionLocal

    receipt = ReceiptData(store_name="Lidl", date=date(2026, 9, 15), currency="CZK", total_amount=17, items=[
        {"name": "Cheese", "total_price": 10, "category": "Groceries"},
        {"name": "Cheese discount", "total_price": -3, "category": "Groceries"},
        {"name": "Wine", "total_price": 30, "category": "Groceries"},
        {"name": "Lidl Plus coupon", "total_price": -20, "category": "Other"},
    ])
    send = AsyncMock()
    monkeypatch.setattr(tasks, "_send_telegram_msg", send)

    asyncio.run(tasks._process_and_notify_pipeline(CHAT_ID, CHAT_ID, "discount-blob", receipt))

    text = send.call_args.args[1]
    assert "Cheese discount" in text and "-3.00 CZK" in text
    assert storage.deleted == []

    async def stats():
        async with AsyncSessionLocal() as session:
            return await get_monthly_stats(session, CHAT_ID, 2026, 9)

    total, categories = asyncio.run(stats())
    assert total == Decimal("17.00")
    assert dict(categories) == {"Groceries": Decimal("37.00"), "Other": Decimal("-20.00")}


def test_gemini_call_disables_function_calling_and_uses_long_timeout(monkeypatch):
    import io

    from PIL import Image

    generate = MagicMock(return_value=MagicMock(text='{"total_amount": 1, "items": [], "currency": "CZK"}'))
    monkeypatch.setattr(tasks.ai_client.models, "generate_content", generate)

    image = io.BytesIO()
    Image.new("RGB", (4, 4)).save(image, format="PNG")
    tasks.analyze_receipt_with_gemini(image.getvalue())

    config = generate.call_args.kwargs["config"]
    assert config.automatic_function_calling.disable is True
    assert tasks.GEMINI_TIMEOUT_MS >= 120_000
    assert "NEGATIVE total_price" in generate.call_args.kwargs["contents"][1]
