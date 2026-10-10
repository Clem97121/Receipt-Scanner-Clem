"""Shared test setup: fake environment, SQLite database, in-memory AWS (moto) and an offline Telegram session.

Environment variables must be set before any app module is imported,
because bot.py, tasks.py and db/database.py read them at import time.
"""
import os
import tempfile
import time

_TMP_DIR = tempfile.mkdtemp(prefix="receipt-tests-")
AWS_REGION = "eu-central-1"
PHOTOS_BUCKET = "test-receipt-photos"
QUEUE_NAME = "test-receipts"
os.environ.update(
    BOT_TOKEN="123456:TEST-TOKEN-TEST-TOKEN-TEST-TOKEN",
    GEMINI_API_KEY="test-key",
    DATABASE_URL="sqlite+aiosqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/"),
    WEBHOOK_SECRET="test-webhook-secret",
    PHOTOS_BUCKET=PHOTOS_BUCKET,
    # moto's default account id is 123456789012
    RECEIPTS_QUEUE_URL=f"https://sqs.{AWS_REGION}.amazonaws.com/123456789012/{QUEUE_NAME}",
    AWS_DEFAULT_REGION=AWS_REGION,
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
)
os.environ.pop("SSM_PARAMETER_PREFIX", None)

# moto must be imported before boto3 clients are created (storage.py and receipt_queue.py create them at import)
import boto3
import pytest
from moto import mock_aws
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import GetMe, SendMessage
from aiogram.types import Message, Update, User as TelegramUser
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
        if isinstance(method, GetMe):
            return TelegramUser(id=bot.id, is_bot=True, first_name="Receipt Bot", username="test_receipt_bot")
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
                   photo_file_id: str | None = None, photo_unique_id: str | None = None,
                   chat_id: int | None = None) -> list:
        """Sends a message from the user (in a private chat unless chat_id is given) and returns the Bot API calls it caused."""
        chat = {"id": user_id, "type": "private"} if chat_id is None else {"id": chat_id, "type": "group", "title": "Group"}
        message = {
            "message_id": self._next_id(),
            "date": int(time.time()),
            "chat": chat,
            "from": {"id": user_id, "is_bot": False, "first_name": f"Name{user_id}"},
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
            message["photo"] = [{
                "file_id": photo_file_id, "file_unique_id": photo_unique_id or photo_file_id,
                "width": 800, "height": 1200,
            }]
        return await self._feed({"update_id": self._next_id(), "message": message})

    async def click(self, user_id: int, data: str) -> list:
        """Presses an inline button with the given callback data and returns the Bot API calls it caused."""
        callback = {
            "id": str(self._next_id()),
            "from": {"id": user_id, "is_bot": False, "first_name": f"Name{user_id}"},
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


class RecordingS3:
    """Wraps the moto S3 client and records which photo keys were uploaded and deleted."""

    def __init__(self, client):
        self.client = client
        self.uploaded = []
        self.deleted = []

    def put_object(self, **kwargs):
        self.uploaded.append(kwargs["Key"])
        return self.client.put_object(**kwargs)

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs["Key"])
        return self.client.delete_object(**kwargs)

    def __getattr__(self, name):
        return getattr(self.client, name)

    def put_photo(self, key: str, data: bytes = b"image-bytes") -> None:
        """Seeds a photo without recording it as an upload made by the app."""
        self.client.put_object(Bucket=PHOTOS_BUCKET, Key=key, Body=data)

    def keys(self) -> list[str]:
        return [obj["Key"] for obj in self.client.list_objects_v2(Bucket=PHOTOS_BUCKET).get("Contents", [])]


@pytest.fixture(scope="session")
def _aws_session():
    """In-memory AWS for the whole run (starting moto per test is slow); no test talks to real AWS."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.create_bucket(Bucket=PHOTOS_BUCKET, CreateBucketConfiguration={"LocationConstraint": AWS_REGION})
        sqs = boto3.client("sqs", region_name=AWS_REGION)
        sqs.create_queue(QueueName=QUEUE_NAME)
        yield {"s3": s3, "sqs": sqs, "ssm": boto3.client("ssm", region_name=AWS_REGION)}


@pytest.fixture(autouse=True)
def aws(_aws_session):
    """Empty S3 bucket, SQS queue and SSM parameters for every test."""
    yield _aws_session
    s3, sqs, ssm = _aws_session["s3"], _aws_session["sqs"], _aws_session["ssm"]
    for obj in s3.list_objects_v2(Bucket=PHOTOS_BUCKET).get("Contents", []):
        s3.delete_object(Bucket=PHOTOS_BUCKET, Key=obj["Key"])
    sqs.purge_queue(QueueUrl=os.environ["RECEIPTS_QUEUE_URL"])
    names = [p["Name"] for p in ssm.describe_parameters().get("Parameters", [])]
    if names:
        ssm.delete_parameters(Names=names)


@pytest.fixture(autouse=True)
def storage(aws, monkeypatch):
    """The app's S3 client, recording uploads and deletions."""
    import storage as storage_module

    recorder = RecordingS3(aws["s3"])
    monkeypatch.setattr(storage_module, "s3", recorder)
    return recorder


def queued_receipts(aws) -> list[dict]:
    """Returns the bodies of all messages waiting in the receipts queue."""
    import json

    response = aws["sqs"].receive_message(QueueUrl=os.environ["RECEIPTS_QUEUE_URL"], MaxNumberOfMessages=10)
    return [json.loads(message["Body"]) for message in response.get("Messages", [])]


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
    """Telegram harness; FSM state lives in the DB, which the db fixture recreates for every test."""
    harness = TelegramHarness()
    yield harness
