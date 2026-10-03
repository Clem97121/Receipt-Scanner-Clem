import asyncio
import io
import logging

from aiogram import F, Router, types

from db.crud import get_receipt_by_blob_name
from db.database import AsyncSessionLocal
from formatting import format_receipt_text
from keyboards import get_receipt_inline_keyboard
from storage import upload_receipt_photo
from tasks import process_receipt_task

router = Router(name="photo")


@router.message(F.photo)
async def handle_photo(message: types.Message):
    """Uploads a receipt photo to storage and queues it for AI recognition."""
    await message.answer("📥 Checking photo and downloading from Telegram...")

    photo = message.photo[-1]
    file_info = await message.bot.get_file(photo.file_id)

    file_bytes = io.BytesIO()
    await message.bot.download_file(file_info.file_path, destination=file_bytes)
    raw_bytes = file_bytes.getvalue()

    blob_name = f"{message.from_user.id}/{photo.file_id}.jpg"

    try:
        async with AsyncSessionLocal() as session:
            existing_receipt = await get_receipt_by_blob_name(session, blob_name, message.from_user.id)

        if existing_receipt:
            formatted_text = (
                "⚠️ <b>This receipt has already been processed and saved!</b>\n\n"
                + format_receipt_text(existing_receipt)
            )
            await message.answer(
                text=formatted_text,
                parse_mode="HTML",
                reply_markup=get_receipt_inline_keyboard(existing_receipt.id)
            )
            return

        await upload_receipt_photo(blob_name, raw_bytes)
        await asyncio.to_thread(process_receipt_task.delay, blob_name, message.chat.id)

        await message.answer(
            "✅ Photo uploaded to Azure Blob Storage successfully!\n"
            "• Processing with AI...",
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"Error handling photo upload: {e}")
        await message.answer("❌ Failed to process photo.")
