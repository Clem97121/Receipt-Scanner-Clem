import math

from aiogram import F, Router, types
from aiogram.filters import Command

from db.crud import (
    delete_receipt_by_id,
    get_receipt_by_id,
    get_user_receipts_count,
    get_user_receipts_paginated,
)
from db.database import AsyncSessionLocal
from formatting import format_receipt_text
from keyboards import BTN_MY_RECEIPTS, get_receipt_inline_keyboard, get_receipts_list_keyboard
from storage import delete_receipt_photo

router = Router(name="receipts")


# --- Receipts List & Pagination Handlers ---

async def send_or_edit_receipts_list(target, user_id: int, page: int, is_callback: bool = False, callback_query = None):
    """Helper to display a page of saved receipts."""
    limit = 5
    offset = (page - 1) * limit

    async with AsyncSessionLocal() as session:
        total_count = await get_user_receipts_count(session, user_id)
        receipts = await get_user_receipts_paginated(session, user_id, offset, limit)

    total_pages = math.ceil(total_count / limit) if total_count > 0 else 1

    if page > total_pages:
        page = total_pages
        offset = (page - 1) * limit
        async with AsyncSessionLocal() as session:
            receipts = await get_user_receipts_paginated(session, user_id, offset, limit)

    if total_count == 0:
        text = "📜 <b>My Receipts</b>\n\nYou don't have any saved receipts yet. Send me a photo of a receipt to get started!"
        keyboard = None
    else:
        text = f"📜 <b>My Receipts (Total: {total_count})</b>\nSelect a receipt to view details, edit, or delete:"
        keyboard = get_receipts_list_keyboard(receipts, page, total_pages)

    if is_callback:
        try:
            await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
        await callback_query.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.message(F.text == BTN_MY_RECEIPTS)
@router.message(Command("receipts"))
async def cmd_receipts(message: types.Message):
    """Handler for the '📜 My Receipts' button or /receipts command."""
    await send_or_edit_receipts_list(message, message.from_user.id, page=1, is_callback=False)


@router.callback_query(F.data.startswith("receipts_page:"))
async def receipts_pagination_handler(callback: types.CallbackQuery):
    """Pagination handler for receipts list."""
    page = int(callback.data.split(":")[1])
    await send_or_edit_receipts_list(callback.message, callback.from_user.id, page=page, is_callback=True, callback_query=callback)


@router.callback_query(F.data == "ignore_receipts_title")
async def ignore_receipts_title_handler(callback: types.CallbackQuery):
    """Stub handler for receipts list page title button."""
    await callback.answer()


@router.callback_query(F.data.startswith("view_receipt_from_list:"))
async def view_receipt_from_list_handler(callback: types.CallbackQuery):
    """Opens a detailed card of a selected receipt from the list, with a back button."""
    _, receipt_id_str, page_str = callback.data.split(":")
    receipt_id, page = int(receipt_id_str), int(page_str)

    async with AsyncSessionLocal() as session:
        receipt = await get_receipt_by_id(session, receipt_id, callback.from_user.id)

    if not receipt:
        await callback.answer("❌ Receipt not found.", show_alert=True)
        return

    formatted_text = format_receipt_text(receipt)
    keyboard = get_receipt_inline_keyboard(receipt_id, back_page=page)

    await callback.message.edit_text(
        text=formatted_text,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


# --- Deleting Receipts ---

@router.callback_query(F.data.startswith("delete_receipt:"))
async def delete_receipt_handler(callback: types.CallbackQuery):
    """Handler for the inline '🗑 Delete Receipt' button."""
    receipt_id = int(callback.data.split(":")[1])

    async with AsyncSessionLocal() as session:
        deleted_blob_name = await delete_receipt_by_id(session, receipt_id, callback.from_user.id)

    if deleted_blob_name is not None:
        await delete_receipt_photo(deleted_blob_name)
        await callback.answer("Receipt deleted successfully!")
        await callback.message.edit_text("🗑 <b>This receipt has been deleted from the system.</b>", parse_mode="HTML")
    else:
        await callback.answer("Could not find receipt or permission denied.", show_alert=True)
