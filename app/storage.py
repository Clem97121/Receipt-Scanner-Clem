import asyncio
import logging
import os

import boto3
from dotenv import load_dotenv

load_dotenv()

PHOTOS_BUCKET = os.getenv("PHOTOS_BUCKET")

if not PHOTOS_BUCKET:
    raise ValueError("ERROR: PHOTOS_BUCKET not found in .env!")

s3 = boto3.client("s3")


def upload_photo_sync(blob_name: str, data: bytes) -> None:
    """Uploads a receipt photo to S3, overwriting an existing object with the same key."""
    s3.put_object(Bucket=PHOTOS_BUCKET, Key=blob_name, Body=data, ContentType="image/jpeg")


def download_photo_sync(blob_name: str) -> bytes:
    """Downloads a receipt photo from S3."""
    return s3.get_object(Bucket=PHOTOS_BUCKET, Key=blob_name)["Body"].read()


def delete_photo_sync(blob_name: str) -> None:
    """Deletes a receipt photo from S3; failures are logged, not raised. Missing objects are not an error in S3."""
    try:
        s3.delete_object(Bucket=PHOTOS_BUCKET, Key=blob_name)
    except Exception:
        logging.exception(f"Failed to delete receipt photo from storage: {blob_name}")


async def upload_receipt_photo(blob_name: str, data: bytes) -> None:
    """Async wrapper for upload_photo_sync."""
    await asyncio.to_thread(upload_photo_sync, blob_name, data)


async def delete_receipt_photo(blob_name: str) -> None:
    """Async wrapper for delete_photo_sync; failures are logged, not raised."""
    await asyncio.to_thread(delete_photo_sync, blob_name)
