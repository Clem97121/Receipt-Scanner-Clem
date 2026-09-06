import asyncio
import io
import logging
import os
from azure.storage.blob import BlobServiceClient
from celery import Celery
from dotenv import load_dotenv
from aiogram import Bot
from google import genai
from google.genai import types
from PIL import Image
from google.genai.errors import APIError

from schemas import ReceiptData

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "receipts")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

celery_app = Celery("receipt_tasks", broker=REDIS_URL, backend=REDIS_URL)

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)
ai_client = genai.Client(api_key=GEMINI_API_KEY)


async def send_telegram_notification(chat_id: int, text: str):
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    finally:
        await bot.session.close()


def analyze_receipt_with_gemini(image_bytes: bytes) -> ReceiptData:
    """Sends image to Gemini Vision model and returns parsed ReceiptData object."""
    image = Image.open(io.BytesIO(image_bytes))

    prompt = (
        "You are an automated receipt scanner. Analyze the receipt image "
        "and extract the store name, date, total amount, currency, "
        "and a complete list of items with their categories."
    )

    # Use Structured Outputs (response_schema)
    response = ai_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=[image, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ReceiptData,
        ),
    )

    # Validate retrieved JSON with Pydantic
    return ReceiptData.model_validate_json(response.text)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def process_receipt_task(self, blob_name: str, chat_id: int):
    logging.info(f"[Celery Worker] Starting Gemini analysis for: {blob_name}")

    try:
        # 1. Download image from Azure Blob Storage
        blob_client = blob_service_client.get_blob_client(
            container=AZURE_CONTAINER_NAME, blob=blob_name
        )
        download_stream = blob_client.download_blob()
        image_bytes = download_stream.readall()

        # 2. Send to Gemini
        receipt = analyze_receipt_with_gemini(image_bytes)

        # 3. Format result for user
        items_formatted = "\n".join(
            [
                f"• *{item.name}* ({item.quantity}x) — `{item.total_price} {receipt.currency}` _[{item.category}]_"
                for item in receipt.items
            ]
        )

        response_text = (
            f"🏪 *Store:* {receipt.store_name or 'Not specified'}\n"
            f"📅 *Date:* {receipt.date or 'Not specified'}\n"
            f"💰 *Total:* `{receipt.total_amount} {receipt.currency}`\n\n"
            f"🛒 *Items:*\n{items_formatted}"
        )

    except APIError as e:
        # Retry up to 3 times if API returns 503 or is temporarily unavailable
        if e.code == 503 or "UNAVAILABLE" in str(e):
            logging.warning(
                f"[Gemini 503] API high demand peak. Retrying {self.request.retries + 1}/3..."
            )
            raise self.retry(exc=e, countdown=5)

        logging.error(f"Gemini API error: {e}")
        response_text = f"❌ AI API error: `{e.message}`"

    except Exception as e:
        logging.error(f"Unexpected processing error: {e}")
        response_text = f"❌ Error processing receipt: `{e}`"

    # 4. Send response to Telegram
    asyncio.run(send_telegram_notification(chat_id, response_text))
    logging.info(f"[Celery Worker] Task completed for chat {chat_id}")
    return {"status": "completed", "blob_name": blob_name}