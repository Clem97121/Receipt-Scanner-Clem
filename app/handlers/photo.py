import asyncio
import io
import logging

from aiogram import F, Router, types

from db.crud import find_receipt_by_photo, photo_blob_name
from db.database import AsyncSessionLocal
from db.family import ensure_user
from handlers.cards import receipt_card
from keyboards import get_receipt_inline_keyboard
from storage import upload_receipt_photo
from tasks import process_receipt_task

router = Router(name="photo")


@router.message(F.photo)
async def handle_photo(message: types.Message):
    """Uploads a receipt photo to storage and queues it for AI recognition."""
    await message.answer("📥 Checking photo and downloading from Telegram...")

    photo = message.photo[-1]
    user_id = message.from_user.id
    blob_name = photo_blob_name(user_id, photo.file_unique_id)

    try:
        async with AsyncSessionLocal() as session:
            # Store the Telegram name so family members can see who added the receipt
            await ensure_user(session, user_id, message.from_user.username, message.from_user.full_name)
            await session.commit()
            existing_receipt = await find_receipt_by_photo(session, photo.file_unique_id, user_id)

        if existing_receipt:
            formatted_text = (
                "⚠️ <b>This receipt has already been processed and saved!</b>\n\n"
                + await receipt_card(existing_receipt, user_id)
            )
            await message.answer(
                text=formatted_text,
                parse_mode="HTML",
                reply_markup=get_receipt_inline_keyboard(existing_receipt.id)
            )
            return

        file_info = await message.bot.get_file(photo.file_id)
        file_bytes = io.BytesIO()
        await message.bot.download_file(file_info.file_path, destination=file_bytes)

        await upload_receipt_photo(blob_name, file_bytes.getvalue())
        await asyncio.to_thread(process_receipt_task.delay, blob_name, message.chat.id, user_id)

        await message.answer(
            "✅ Photo uploaded to Azure Blob Storage successfully!\n"
            "• Processing with AI...",
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"Error handling photo upload: {e}")
        await message.answer("❌ Failed to process photo.")
