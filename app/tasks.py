import asyncio
import io
import logging
import os

import httpx
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from celery import Celery
from dotenv import load_dotenv
from aiogram import Bot
from google import genai
from google.genai import types
from PIL import Image
from google.genai.errors import APIError
from sqlalchemy.exc import IntegrityError

from db.database import AsyncSessionLocal, engine
from db.crud import save_receipt_to_db
from schemas import ReceiptData

from formatting import format_receipt_text
from keyboards import get_receipt_inline_keyboard

load_dotenv()

# The Azure SDK logs every HTTP request with all headers at INFO level
logging.getLogger("azure").setLevel(logging.WARNING)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "receipts")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PRIMARY_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = "gemini-3.5-flash"

celery_app = Celery("receipt_tasks", broker=REDIS_URL, backend=REDIS_URL)

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)
# Without a timeout a hung Gemini request would block the worker forever.
# Successful calls already take up to ~50s when several run in parallel, so leave headroom.
GEMINI_TIMEOUT_MS = 120_000

# HTTP status codes from Gemini that mean "try again later"
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
ai_client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))


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
        "Do not invent new categories. If you are unsure about an item, assign it to 'Other'. "
        "List discounts, coupons and returned bottle deposits as separate items with a NEGATIVE total_price "
        "(use the category of the discounted item, or 'Other'). "
        "total_amount is the final amount actually paid, after all discounts."
    )

    response = ai_client.models.generate_content(
        model=model_name,
        contents=[image, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ReceiptData,
            # We don't use tools; this also silences the SDK's AFC warning on every call
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

    return ReceiptData.model_validate_json(response.text)


def is_transient_ai_error(error: Exception) -> bool:
    """True for Gemini failures worth retrying: overload/server errors, timeouts and network errors."""
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(error, APIError):
        return getattr(error, "code", None) in TRANSIENT_STATUS_CODES or "UNAVAILABLE" in str(error)
    return False


def analyze_with_fallback(image_bytes: bytes) -> ReceiptData:
    """Tries the primary model and, on a transient failure, the fallback model once."""
    try:
        return analyze_receipt_with_gemini(image_bytes, model_name=PRIMARY_MODEL)
    except Exception as error:
        if not is_transient_ai_error(error):
            raise
        logging.warning(
            f"[Gemini] {PRIMARY_MODEL} failed transiently ({type(error).__name__}). Trying fallback {FALLBACK_MODEL}..."
        )
        return analyze_receipt_with_gemini(image_bytes, model_name=FALLBACK_MODEL)


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


def _delete_unsaved_photo(blob_name: str) -> None:
    """Deletes a photo that will never be linked to a saved receipt; failures are logged, not raised."""
    try:
        blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=blob_name).delete_blob()
        logging.info(f"[Celery Worker] Deleted unsaved photo: {blob_name}")
    except ResourceNotFoundError:
        pass
    except Exception:
        logging.exception(f"[Celery Worker] Failed to delete unsaved photo: {blob_name}")


async def _process_and_notify_pipeline(chat_id: int, user_id: int, blob_name: str, receipt: ReceiptData):
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
            await asyncio.to_thread(_delete_unsaved_photo, blob_name)
            return

        # 2. Reject numbers that are impossible or would not fit the DB columns
        problems = receipt.find_problems()
        if problems:
            logging.warning(f"[Celery Worker] Unreliable AI output for blob {blob_name}: {problems}")
            await _send_telegram_msg(
                chat_id,
                "⚠️ <b>I couldn't read the amounts on this receipt reliably.</b>\n\n"
                "Please send a clearer, well-lit photo of the whole receipt."
            )
            await asyncio.to_thread(_delete_unsaved_photo, blob_name)
            return

        # 3. Save to Database
        db_receipt = None
        try:
            async with AsyncSessionLocal() as session:
                db_receipt = await save_receipt_to_db(
                    session=session,
                    user_id=user_id,
                    blob_name=blob_name,
                    receipt_data=receipt,
                )
            logging.info(f"[Celery Worker] Saved receipt to DB for user {user_id}")

        except IntegrityError:
            logging.warning(f"[Celery Worker] Duplicate receipt detected for blob: {blob_name}")
            await _send_telegram_msg(
                chat_id, 
                "⚠️ <b>This receipt has already been processed and saved!</b>"
            )
            return

        # 4. Format result message with numbered items (shared formatter escapes HTML)
        response_text = format_receipt_text(receipt)

        # 5. Attach inline keyboard with Delete/Edit buttons if receipt ID is present
        keyboard = None
        if db_receipt and hasattr(db_receipt, "id"):
            keyboard = get_receipt_inline_keyboard(db_receipt.id)

        # 6. Send response to Telegram with HTML parse mode
        await _send_telegram_msg(chat_id, response_text, reply_markup=keyboard)

    finally:
        await engine.dispose()


RETRY_COUNTDOWN_SECONDS = 10


# Worst case per attempt: two Gemini calls (primary + fallback) at GEMINI_TIMEOUT_MS each, plus download and saving
@celery_app.task(bind=True, max_retries=2, soft_time_limit=300, time_limit=330)
def process_receipt_task(self, blob_name: str, chat_id: int, user_id: int | None = None):
    """Recognizes a receipt photo and saves it for user_id; replies go to chat_id.

    user_id defaults to chat_id for tasks queued by older bot versions (private chats only).
    """
    user_id = user_id or chat_id
    logging.info(f"[Celery Worker] Starting Gemini analysis for: {blob_name}")

    try:
        # 1. Download image from Azure Blob Storage
        blob_client = blob_service_client.get_blob_client(
            container=AZURE_CONTAINER_NAME, blob=blob_name
        )
        download_stream = blob_client.download_blob()
        image_bytes = download_stream.readall()

        # 2. Try the primary model first, the fallback model on overload/timeouts
        receipt = analyze_with_fallback(image_bytes)

        # 3. Run entire DB + Telegram async flow in ONE single event loop
        asyncio.run(_process_and_notify_pipeline(chat_id, user_id, blob_name, receipt))
        
        logging.info(f"[Celery Worker] Task completed for chat {chat_id}")
        return {"status": "completed", "blob_name": blob_name}

    except Exception as e:
        if is_transient_ai_error(e):
            # self.retry() re-raises the original exception once retries are exhausted,
            # so check the retry budget explicitly before scheduling another attempt.
            if self.request.retries >= self.max_retries:
                logging.error(f"[Celery Worker] Retries exhausted, Fast Fail triggered for blob: {blob_name}")
                error_msg = (
                    "⚠️ <b>The AI servers are currently overloaded</b>\n\n"
                    "Unable to recognize the receipt after several attempts. "
                    "Please resubmit the photo in a minute."
                )
                asyncio.run(_send_telegram_msg(chat_id, error_msg))
                _delete_unsaved_photo(blob_name)
                return {"status": "failed", "blob_name": blob_name}

            if self.request.retries == 0:
                asyncio.run(_send_telegram_msg(
                    chat_id, "⏳ The AI is responding slowly right now, still trying to recognize your receipt..."
                ))
            logging.warning(
                f"[Gemini] Both models failed ({type(e).__name__}). "
                f"Retry {self.request.retries + 1}/{self.max_retries} in {RETRY_COUNTDOWN_SECONDS}s..."
            )
            raise self.retry(exc=e, countdown=RETRY_COUNTDOWN_SECONDS)

        if isinstance(e, APIError):
            logging.exception(f"[Celery Worker] Gemini API error for blob: {blob_name}")
            asyncio.run(_send_telegram_msg(
                chat_id, "❌ The AI service failed to process your receipt. Please try again later."
            ))
            _delete_unsaved_photo(blob_name)
            return {"status": "failed", "blob_name": blob_name}

        # The failure may have happened after the receipt was saved, so the photo is kept
        logging.exception(f"[Celery Worker] Unexpected processing error for blob: {blob_name}")
        asyncio.run(_send_telegram_msg(
            chat_id, "❌ Something went wrong while processing your receipt. Please try again later."
        ))