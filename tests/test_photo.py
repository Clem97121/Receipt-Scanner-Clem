from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import handlers.photo as photo_handlers
from conftest import OWNER_ID, texts


@pytest.fixture
def telegram_files(tg, monkeypatch):
    """Fakes downloading the photo from Telegram."""
    async def download_file(file_path, destination):
        destination.write(b"jpeg-bytes")

    monkeypatch.setattr(tg.bot, "get_file", AsyncMock(return_value=SimpleNamespace(file_path="photos/1.jpg")))
    monkeypatch.setattr(tg.bot, "download_file", download_file)


@pytest.fixture
def queue(monkeypatch):
    """Captures receipts queued for the Celery worker."""
    delay = MagicMock()
    monkeypatch.setattr(photo_handlers.process_receipt_task, "delay", delay)
    return delay


async def test_new_photo_is_uploaded_and_queued(tg, telegram_files, queue, storage):
    sent = texts(await tg.send(OWNER_ID, photo_file_id="new-photo"))
    blob_name = f"{OWNER_ID}/new-photo.jpg"
    assert storage.uploaded == [blob_name]
    queue.assert_called_once_with(blob_name, OWNER_ID)
    assert any("Processing with AI" in t for t in sent)


async def test_already_saved_photo_is_not_processed_again(tg, telegram_files, queue, storage):
    # The seeded receipt's blob name is "owner-blob"; make the photo map to an existing receipt
    from db.database import AsyncSessionLocal
    from db.models import Receipt

    async with AsyncSessionLocal() as session:
        receipt = await session.get(Receipt, 10)
        receipt.blob_name = f"{OWNER_ID}/seen-photo.jpg"
        await session.commit()

    sent = texts(await tg.send(OWNER_ID, photo_file_id="seen-photo"))
    assert storage.uploaded == []
    queue.assert_not_called()
    assert any("already been processed" in t for t in sent)


async def test_storage_failure_is_reported(tg, telegram_files, queue, monkeypatch):
    async def broken_upload(blob_name, data):
        raise ConnectionError("azure is down")

    monkeypatch.setattr(photo_handlers, "upload_receipt_photo", broken_upload)
    sent = texts(await tg.send(OWNER_ID, photo_file_id="new-photo"))
    queue.assert_not_called()
    assert any("Failed to process photo" in t for t in sent)
