import asyncio
import io
import logging
import os
from azure.storage.blob import BlobServiceClient
from celery import Celery
from celery.exceptions import MaxRetriesExceededError
from dotenv import load_dotenv
from aiogram import Bot
from google import genai
from google.genai import types
from PIL import Image
from google.genai.errors import APIError, ServerError
from sqlalchemy.exc import IntegrityError

from db.database import AsyncSessionLocal, engine
from db.crud import save_receipt_to_db, init_db
from schemas import ReceiptData

from keyboards import get_receipt_inline_keyboard

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "receipts")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PRIMARY_MODEL = "Gemini 3.5 Flash Lite"
FALLBACK_MODEL = "gemini-3.5-flash"

celery_app = Celery("receipt_tasks", broker=REDIS_URL, backend=REDIS_URL)

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)
ai_client = genai.Client(api_key=GEMINI_API_KEY)


def analyze_receipt_with_gemini(image_bytes: bytes, model_name: str = PRIMARY_MODEL) -> ReceiptData:
    """Sends image to specified Gemini model and returns parsed ReceiptData object."""
    image = Image.open(io.BytesIO(image_bytes))

    prompt = (
        "You are an automated receipt scanner and document validator. "
        "Analyze the image and determine whether it is a valid purchase receipt, store invoice, or cash register slip. "
        "1. Set `is_receipt` to `true` ONLY if it is an actual purchase receipt or bill. "
        "2. Set `is_receipt` to `false` if it is a selfie, photo of people, animals, landscapes, screenshots of chats, memes, or any non-receipt image. "
        "If it IS a receipt, extract the store name, date, total amount, currency, and a complete list of items. "
        "CRITICAL: For each item's category, you MUST strictly choose one of the following exact string values: "
        "'Groceries', 'Cafe & Dining', 'Transport', 'Household', 'Utilities', 'Entertainment', 'Shopping', or 'Other'. "
        "Do not invent new categories. If you are unsure about an item, assign it to 'Other'."
    )

    response = ai_client.models.generate_content(
        model=model_name,
        contents=[image, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ReceiptData,
        ),
    )

    return ReceiptData.model_validate_json(response.text)


async def _send_telegram_msg(chat_id: int, text: str, reply_markup=None):
    """Helper to send telegram message in its own single loop during error cases or with keyboards."""
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(
            chat_id=chat_id, 
            text=text, 
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    finally:
        await bot.session.close()


async def _process_and_notify_pipeline(chat_id: int, blob_name: str, receipt: ReceiptData):
    """Executes DB saving and Telegram notification in a SINGLE asyncio Event Loop."""
    try:
        # 1. Check if image is actually a receipt
        if not receipt.is_receipt:
            logging.warning(f"[Celery Worker] Image is not a receipt for chat {chat_id}")
            await _send_telegram_msg(
                chat_id, 
                "❌ <b>This doesn't look like a receipt!</b>\n\n"
                "Please send a clear photo of a purchase receipt or store bill."
            )
            return

        # 2. Save to Database
        db_receipt = None
        try:
            await init_db()
            async with AsyncSessionLocal() as session:
                db_receipt = await save_receipt_to_db(
                    session=session,
                    user_id=chat_id,
                    blob_name=blob_name,
                    receipt_data=receipt,
                )
            logging.info(f"[Celery Worker] Saved receipt to DB for user {chat_id}")

        except IntegrityError:
            logging.warning(f"[Celery Worker] Duplicate receipt detected for blob: {blob_name}")
            await _send_telegram_msg(
                chat_id, 
                "⚠️ <b>This receipt has already been processed and saved!</b>"
            )
            return

        # 3. Format result message with numbered items sorted by id (or index order)
        items_formatted = "\n".join(
            [
                f"{i+1}. <b>{item.name}</b> ({item.quantity}x) — <code>{item.total_price} {receipt.currency}</code> <i>[{item.category}]</i>"
                for i, item in enumerate(receipt.items)
            ]
        )

        response_text = (
            f"🏪 <b>Store:</b> {receipt.store_name or 'Not specified'}\n"
            f"📅 <b>Date:</b> {receipt.date or 'Not specified'}\n"
            f"💰 <b>Total:</b> <code>{receipt.total_amount} {receipt.currency}</code>\n\n"
            f"🛒 <b>Items:</b>\n{items_formatted}"
        )

        # 4. Attach inline keyboard with Delete/Edit buttons if receipt ID is present
        keyboard = None
        if db_receipt and hasattr(db_receipt, "id"):
            keyboard = get_receipt_inline_keyboard(db_receipt.id)

        # 5. Send response to Telegram with HTML parse mode
        await _send_telegram_msg(chat_id, response_text, reply_markup=keyboard)

    finally:
        await engine.dispose()


@celery_app.task(bind=True, max_retries=2)
def process_receipt_task(self, blob_name: str, chat_id: int):
    logging.info(f"[Celery Worker] Starting Gemini analysis for: {blob_name}")

    try:
        # 1. Download image from Azure Blob Storage
        blob_client = blob_service_client.get_blob_client(
            container=AZURE_CONTAINER_NAME, blob=blob_name
        )
        download_stream = blob_client.download_blob()
        image_bytes = download_stream.readall()

        # 2. Try Primary Model first, fallback if 503 occurs
        try:
            receipt = analyze_receipt_with_gemini(image_bytes, model_name=PRIMARY_MODEL)
        except (APIError, ServerError) as e:
            if getattr(e, "code", None) == 503 or "UNAVAILABLE" in str(e):
                logging.warning(f"[Gemini 503] {PRIMARY_MODEL} unavailable. Trying fallback {FALLBACK_MODEL}...")
                receipt = analyze_receipt_with_gemini(image_bytes, model_name=FALLBACK_MODEL)
            else:
                raise e

        # 3. Run entire DB + Telegram async flow in ONE single event loop
        asyncio.run(_process_and_notify_pipeline(chat_id, blob_name, receipt))
        
        logging.info(f"[Celery Worker] Task completed for chat {chat_id}")
        return {"status": "completed", "blob_name": blob_name}

    except (APIError, ServerError) as e:
        is_503 = getattr(e, "code", None) == 503 or "UNAVAILABLE" in str(e)

        if is_503:
            logging.warning(f"[Gemini 503] Both models busy. Retry {self.request.retries + 1}/2 in 3s...")
            try:
                raise self.retry(exc=e, countdown=3)
            except MaxRetriesExceededError:
                logging.error(f"[Celery Worker] Fast Fail triggered for blob: {blob_name}")
                error_msg = (
                    "⚠️ <b>The AI servers are currently overloaded</b>\n\n"
                    "Unable to recognize the receipt within 10 seconds. "
                    "Please resubmit the photo in a minute."
                )
                asyncio.run(_send_telegram_msg(chat_id, error_msg))
        else:
            logging.error(f"Gemini API error: {e}")
            asyncio.run(_send_telegram_msg(chat_id, f"❌ AI API error: <code>{e}</code>"))

    except Exception as e:
        logging.error(f"Unexpected processing error: {e}")
        asyncio.run(_send_telegram_msg(chat_id, f"❌ Error processing receipt: <code>{e}</code>"))