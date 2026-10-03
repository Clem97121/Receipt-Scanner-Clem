"""Shared test setup: fake environment, SQLite database and an offline Telegram session.

Environment variables must be set before any app module is imported,
because bot.py, tasks.py and db/database.py read them at import time.
"""
import os
import tempfile
import time
from unittest.mock import MagicMock

_TMP_DIR = tempfile.mkdtemp(prefix="receipt-tests-")
os.environ.update(
    BOT_TOKEN="123456:TEST-TOKEN-TEST-TOKEN-TEST-TOKEN",
    AZURE_STORAGE_CONNECTION_STRING=(
        "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net"
    ),
    GEMINI_API_KEY="test-key",
    REDIS_URL="redis://localhost:6379/0",
    DATABASE_URL="sqlite+aiosqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/"),
)

import pytest
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import SendMessage
from aiogram.types import Message, Update
from sqlalchemy import select
from sqlalchemy.orm import selectinload

import bot as bot_module
from db.database import AsyncSessionLocal, Base, engine
from db.models import Receipt, ReceiptItem, User

OWNER_ID = 1
STRANGER_ID = 2
RECEIPT_ID = 10
ITEM_ID = 100
OTHER_RECEIPT_ID = 20


class FakeSession(BaseSession):
    """Records every Bot API call instead of sending it to Telegram."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message.model_validate({
                "message_id": 999,
                "date": int(time.time()),
                "chat": {"id": method.chat_id, "type": "private"},
                "text": method.text,
            })
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""


class TelegramHarness:
    """Feeds fake updates into the real dispatcher and exposes what the bot sent back."""

    def __init__(self):
        self.bot = bot_module.bot
        self.dp = bot_module.dp
        self.session = FakeSession()
        self.bot.session = self.session
        self._update_id = 0

    def _next_id(self) -> int:
        self._update_id += 1
        return self._update_id

    async def send(self, user_id: int, text: str | None = None, sticker: bool = False,
                   photo_file_id: str | None = None) -> list:
        """Sends a message from the user and returns the Bot API calls it caused."""
        message = {
            "message_id": self._next_id(),
            "date": int(time.time()),
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
        }
        if text is not None:
            message["text"] = text
            if text.startswith("/"):
                message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        if sticker:
            message["sticker"] = {
                "file_id": "s", "file_unique_id": "s", "type": "regular",
                "width": 1, "height": 1, "is_animated": False, "is_video": False,
            }
        if photo_file_id:
            message["photo"] = [{"file_id": photo_file_id, "file_unique_id": photo_file_id, "width": 800, "height": 1200}]
        return await self._feed({"update_id": self._next_id(), "message": message})

    async def click(self, user_id: int, data: str) -> list:
        """Presses an inline button with the given callback data and returns the Bot API calls it caused."""
        callback = {
            "id": str(self._next_id()),
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "chat_instance": "test",
            "data": data,
            "message": {
                "message_id": 50,
                "date": int(time.time()),
                "chat": {"id": user_id, "type": "private"},
                "text": "receipt card",
            },
        }
        return await self._feed({"update_id": self._next_id(), "callback_query": callback})

    async def _feed(self, raw_update: dict) -> list:
        self.session.calls.clear()
        await self.dp.feed_update(self.bot, Update.model_validate(raw_update))
        return list(self.session.calls)

    async def state(self, user_id: int):
        key = StorageKey(bot_id=self.bot.id, chat_id=user_id, user_id=user_id)
        return await self.dp.storage.get_state(key)


def texts(calls) -> list[str]:
    """Returns the text of every message the bot sent or edited."""
    return [method.text for method in calls if getattr(method, "text", None)]


async def load_receipt(receipt_id: int) -> Receipt:
    async with AsyncSessionLocal() as session:
        stmt = select(Receipt).options(selectinload(Receipt.items)).where(Receipt.id == receipt_id)
        return (await session.execute(stmt)).scalar_one()


class FakeStorage:
    """In-memory stand-in for Azure Blob Storage that records uploads and deletions."""

    def __init__(self):
        self.uploaded = []
        self.deleted = []

    def get_blob_client(self, container: str, blob: str):
        client = MagicMock()
        client.download_blob.return_value.readall.return_value = b"image-bytes"
        client.upload_blob.side_effect = lambda *args, **kwargs: self.uploaded.append(blob)
        client.delete_blob.side_effect = lambda *args, **kwargs: self.deleted.append(blob)
        return client


@pytest.fixture(autouse=True)
def storage(monkeypatch):
    """Replaces Azure Blob Storage in the bot and the worker so no test talks to the real service."""
    fake = FakeStorage()
    import storage as storage_module
    import tasks
    for module in (storage_module, tasks):
        monkeypatch.setattr(module.blob_service_client, "get_blob_client", fake.get_blob_client)
    return fake


@pytest.fixture
async def db():
    """Recreates all tables and seeds two users, each with one receipt."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        session.add_all([User(telegram_id=OWNER_ID), User(telegram_id=STRANGER_ID)])
        await session.flush()
        session.add_all([
            Receipt(id=RECEIPT_ID, user_id=OWNER_ID, store_name="Shop", total_amount=3,
                    currency="CZK", blob_name="owner-blob"),
            Receipt(id=OTHER_RECEIPT_ID, user_id=STRANGER_ID, store_name="Other", total_amount=5,
                    currency="CZK", blob_name="stranger-blob"),
        ])
        await session.flush()
        session.add_all([
            ReceiptItem(id=ITEM_ID, receipt_id=RECEIPT_ID, name="milk", quantity=1,
                        total_price=3, category="Groceries"),
            ReceiptItem(id=200, receipt_id=OTHER_RECEIPT_ID, name="tv", quantity=1,
                        total_price=5, category="Shopping"),
        ])
        await session.commit()
    yield


@pytest.fixture
async def tg(db):
    """Telegram harness with a clean FSM storage."""
    harness = TelegramHarness()
    harness.dp.storage.storage.clear()
    yield harness
