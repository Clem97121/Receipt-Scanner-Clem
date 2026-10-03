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
    sent = texts(await tg.send(OWNER_ID, photo_file_id="file-id-1", photo_unique_id="unique-1"))
    blob_name = f"{OWNER_ID}/unique-1.jpg"
    assert storage.uploaded == [blob_name]
    queue.assert_called_once_with(blob_name, OWNER_ID, OWNER_ID)
    assert any("Processing with AI" in t for t in sent)


async def test_photo_in_group_is_saved_for_the_sender(tg, telegram_files, queue):
    await tg.send(OWNER_ID, photo_file_id="file-id-1", photo_unique_id="unique-1", chat_id=-100500)
    queue.assert_called_once_with(f"{OWNER_ID}/unique-1.jpg", -100500, OWNER_ID)


async def test_resent_photo_with_new_file_id_is_detected_as_duplicate(tg, telegram_files, queue, storage):
    # Telegram may give the same picture a new file_id; file_unique_id stays the same
    from db.database import AsyncSessionLocal
    from db.models import Receipt

    async with AsyncSessionLocal() as session:
        receipt = await session.get(Receipt, 10)
        receipt.blob_name = f"{OWNER_ID}/same-picture.jpg"
        await session.commit()

    sent = texts(await tg.send(OWNER_ID, photo_file_id="brand-new-file-id", photo_unique_id="same-picture"))
    assert storage.uploaded == []
    queue.assert_not_called()
    assert any("already been processed" in t for t in sent)


async def test_unique_ids_with_like_wildcards_do_not_match_other_photos(tg, telegram_files, queue):
    from db.database import AsyncSessionLocal
    from db.models import Receipt

    async with AsyncSessionLocal() as session:
        receipt = await session.get(Receipt, 10)
        receipt.blob_name = f"{OWNER_ID}/abXcd.jpg"
        await session.commit()

    await tg.send(OWNER_ID, photo_file_id="f", photo_unique_id="ab_cd")  # "_" is a LIKE wildcard
    queue.assert_called_once()


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
