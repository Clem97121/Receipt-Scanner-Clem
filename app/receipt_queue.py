import asyncio
import json
import os

import boto3
from dotenv import load_dotenv

load_dotenv()

RECEIPTS_QUEUE_URL = os.getenv("RECEIPTS_QUEUE_URL")

if not RECEIPTS_QUEUE_URL:
    raise ValueError("ERROR: RECEIPTS_QUEUE_URL not found in .env!")

sqs = boto3.client("sqs")


def enqueue_receipt_sync(blob_name: str, chat_id: int, user_id: int) -> None:
    """Queues an uploaded photo for recognition by the worker Lambda."""
    body = json.dumps({"blob_name": blob_name, "chat_id": chat_id, "user_id": user_id})
    sqs.send_message(QueueUrl=RECEIPTS_QUEUE_URL, MessageBody=body)


async def enqueue_receipt(blob_name: str, chat_id: int, user_id: int) -> None:
    """Async wrapper for enqueue_receipt_sync."""
    await asyncio.to_thread(enqueue_receipt_sync, blob_name, chat_id, user_id)


def retry_later(receipt_handle: str, delay_seconds: int) -> None:
    """Makes a received message visible again after delay_seconds instead of the full visibility timeout."""
    sqs.change_message_visibility(
        QueueUrl=RECEIPTS_QUEUE_URL, ReceiptHandle=receipt_handle, VisibilityTimeout=delay_seconds
    )
