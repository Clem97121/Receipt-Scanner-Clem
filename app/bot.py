import asyncio
import io
import logging
import os
from datetime import datetime
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from tasks import process_receipt_task
from db.database import AsyncSessionLocal
from db.crud import (
    get_monthly_stats, 
    delete_receipt_by_id, 
    get_receipt_by_id, 
    update_receipt_field,
    get_receipt_item_by_id,
    update_receipt_item_field,
    get_receipt_by_blob_name
)
from keyboards import (
    get_main_reply_keyboard, 
    get_receipt_inline_keyboard, 
    get_edit_fields_keyboard,
    get_items_selection_keyboard,
    get_single_item_edit_keyboard,
    get_item_categories_keyboard
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "receipts")

if not BOT_TOKEN:
    raise ValueError("ERROR: Bot token not found! Check your .env file")

if not AZURE_STORAGE_CONNECTION_STRING:
    raise ValueError("ERROR: AZURE_STORAGE_CONNECTION_STRING not found in .env!")

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)


class EditReceiptState(StatesGroup):
    waiting_for_value = State()


class EditItemState(StatesGroup):
    waiting_for_value = State()


def ensure_container_exists():
    """Ensure Azure Blob Storage container exists, create if not."""
    try:
        container_client = blob_service_client.get_container_client(
            AZURE_CONTAINER_NAME
        )
        container_client.create_container()
        logging.info(f"Container '{AZURE_CONTAINER_NAME}' created successfully.")
    except ResourceExistsError:
        logging.info(f"Container '{AZURE_CONTAINER_NAME}' already exists.")
    except Exception as e:
        logging.error(f"Error creating container: {e}")


def format_receipt_text(receipt) -> str:
    """Helper to format a Receipt DB entity into an HTML text string with numbered items."""

    sorted_items = sorted(receipt.items, key=lambda x: x.id)

    items_formatted = "\n".join(
        [
            f"{i+1}. <b>{item.name}</b> ({item.quantity}x) — <code>{item.total_price} {receipt.currency}</code> <i>[{item.category}]</i>"
            for i, item in enumerate(sorted_items)
        ]
    )
    return (
        f"🏪 <b>Store:</b> {receipt.store_name or 'Not specified'}\n"
        f"📅 <b>Date:</b> {receipt.date or 'Not specified'}\n"
        f"💰 <b>Total:</b> <code>{receipt.total_amount} {receipt.currency}</code>\n\n"
        f"🛒 <b>Items:</b>\n{items_formatted}"
    )


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Greeting handler that attaches the main reply keyboard."""
    await message.answer(
        "👋 Hi! I'm an expense tracking bot.\n\n"
        "• Send me a photo of a receipt, and I'll process it.\n"
        "• Click «📊 Monthly Expenses» to view your statistics.",
        reply_markup=get_main_reply_keyboard(),
    )


@dp.message(F.text == "📊 Monthly Expenses")
@dp.message(Command("stats"))
async def show_stats_handler(message: types.Message):
    """Handler for the '📊 Monthly Expenses' button or /stats command."""
    async with AsyncSessionLocal() as session:
        total, categories = await get_monthly_stats(session, message.from_user.id)

    if total == 0:
        await message.answer("📊 No saved expenses found for this month.")
        return

    cat_text = "\n".join([f"• <b>{cat or 'Uncategorized'}</b>: <code>{amount:.2f}</code>" for cat, amount in categories])

    text = (
        f"📊 <b>Expense Statistics for Current Month</b>\n\n"
        f"💰 <b>Total Spent:</b> <code>{total:.2f}</code>\n\n"
        f"🏷 <b>By Category:</b>\n{cat_text}"
    )
    await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data.startswith("delete_receipt:"))
async def delete_receipt_handler(callback: types.CallbackQuery):
    """Handler for the inline '🗑 Delete Receipt' button."""
    receipt_id = int(callback.data.split(":")[1])

    async with AsyncSessionLocal() as session:
        success = await delete_receipt_by_id(session, receipt_id, callback.from_user.id)

    if success:
        await callback.answer("Receipt deleted successfully!")
        await callback.message.edit_text("🗑 <b>This receipt has been deleted from the system.</b>", parse_mode="HTML")
    else:
        await callback.answer("Could not find receipt or permission denied.", show_alert=True)


@dp.callback_query(F.data.startswith("edit_receipt:"))
async def edit_receipt_init_handler(callback: types.CallbackQuery):
    """Handler triggered when clicking '✏️ Edit' on a receipt card."""
    receipt_id = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=get_edit_fields_keyboard(receipt_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("cancel_edit:"))
async def cancel_edit_handler(callback: types.CallbackQuery, state: FSMContext):
    """Cancels the edit flow and restores original card buttons."""
    receipt_id = int(callback.data.split(":")[1])
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=get_receipt_inline_keyboard(receipt_id))
    await callback.answer("Editing cancelled.")


# --- Editing Main Receipt Fields (Store, Date, Total Amount) ---

@dp.callback_query(F.data.startswith("edit_field:"))
async def select_field_to_edit_handler(callback: types.CallbackQuery, state: FSMContext):
    """Handles main field selection for editing and prompts user for input."""
    _, field, receipt_id_str = callback.data.split(":")
    receipt_id = int(receipt_id_str)

    await state.update_data(
        receipt_id=receipt_id,
        field=field,
        message_id=callback.message.message_id
    )
    await state.set_state(EditReceiptState.waiting_for_value)

    prompt_messages = {
        "store_name": "Please send the new store name:",
        "date": "Please send the new date in <code>YYYY-MM-DD</code> format (e.g., 2026-03-29):",
        "total_amount": "Please send the new total amount (e.g., 12.50):"
    }

    await callback.message.answer(
        prompt_messages.get(field, "Please send the new value:"),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(EditReceiptState.waiting_for_value)
async def process_new_field_value_handler(message: types.Message, state: FSMContext):
    """Receives the new main field value, updates DB, and refreshes receipt message."""
    user_data = await state.get_data()
    receipt_id = user_data["receipt_id"]
    field = user_data["field"]
    target_msg_id = user_data["message_id"]

    raw_text = message.text.strip()
    parsed_value = raw_text

    if field == "total_amount":
        try:
            parsed_value = float(raw_text.replace(",", "."))
        except ValueError:
            await message.answer("❌ Invalid amount format. Please enter a valid number (e.g., 15.50):")
            return
    elif field == "date":
        try:
            parsed_value = datetime.strptime(raw_text, "%Y-%m-%d").date()
        except ValueError:
            await message.answer("❌ Invalid date format. Please use <code>YYYY-MM-DD</code> (e.g., 2026-03-29):", parse_mode="HTML")
            return

    async with AsyncSessionLocal() as session:
        updated_receipt = await update_receipt_field(
            session=session,
            receipt_id=receipt_id,
            user_id=message.from_user.id,
            field=field,
            new_value=parsed_value
        )

    if updated_receipt:
        formatted_text = format_receipt_text(updated_receipt)
        await bot.edit_message_text(
            text=formatted_text,
            chat_id=message.chat.id,
            message_id=target_msg_id,
            parse_mode="HTML",
            reply_markup=get_receipt_inline_keyboard(receipt_id)
        )
        await message.answer("✅ Receipt successfully updated!")
    else:
        await message.answer("❌ Failed to update receipt. Receipt not found or permission denied.")

    await state.clear()


# --- Editing Specific Receipt Items ---

@dp.callback_query(F.data.startswith("edit_items_menu:"))
async def edit_items_menu_handler(callback: types.CallbackQuery):
    """Displays the list of item numbers to choose for editing."""
    receipt_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        receipt = await get_receipt_by_id(session, receipt_id, callback.from_user.id)
    
    if receipt:
        await callback.message.edit_reply_markup(reply_markup=get_items_selection_keyboard(receipt))
    await callback.answer()


@dp.callback_query(F.data.startswith("select_item:"))
async def select_item_handler(callback: types.CallbackQuery):
    """Displays edit options for a specific item (Name, Price, Category)."""
    _, item_id_str, receipt_id_str = callback.data.split(":")
    item_id, receipt_id = int(item_id_str), int(receipt_id_str)
    
    await callback.message.edit_reply_markup(reply_markup=get_single_item_edit_keyboard(item_id, receipt_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_item_field:"))
async def select_item_field_to_edit(callback: types.CallbackQuery, state: FSMContext):
    """Prompts user for new value (Name or Price) of a specific item."""
    _, field, item_id_str, receipt_id_str = callback.data.split(":")
    item_id, receipt_id = int(item_id_str), int(receipt_id_str)

    await state.update_data(
        item_id=item_id,
        receipt_id=receipt_id,
        field=field,
        message_id=callback.message.message_id
    )
    await state.set_state(EditItemState.waiting_for_value)

    prompt_messages = {
        "name": "Please send the new item name:",
        "total_price": "Please send the new total price for this item (e.g., 25.50):"
    }

    await callback.message.answer(
        prompt_messages.get(field, "Please send the new value:"),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(EditItemState.waiting_for_value)
async def process_new_item_field_value(message: types.Message, state: FSMContext):
    """Receives new value for item field, updates DB, and updates message card."""
    user_data = await state.get_data()
    item_id = user_data["item_id"]
    receipt_id = user_data["receipt_id"]
    field = user_data["field"]
    target_msg_id = user_data["message_id"]

    raw_text = message.text.strip()
    parsed_value = raw_text

    if field == "total_price":
        try:
            parsed_value = float(raw_text.replace(",", "."))
        except ValueError:
            await message.answer("❌ Invalid price format. Please enter a valid number (e.g., 15.50):")
            return

    async with AsyncSessionLocal() as session:
        updated_receipt = await update_receipt_item_field(
            session=session,
            item_id=item_id,
            field=field,
            new_value=parsed_value
        )

    if updated_receipt:
        formatted_text = format_receipt_text(updated_receipt)
        await bot.edit_message_text(
            text=formatted_text,
            chat_id=message.chat.id,
            message_id=target_msg_id,
            parse_mode="HTML",
            reply_markup=get_single_item_edit_keyboard(item_id, receipt_id)
        )
        await message.answer("✅ Item successfully updated!")
    else:
        await message.answer("❌ Failed to update item.")

    await state.clear()


@dp.callback_query(F.data.startswith("select_item_category:"))
async def select_item_category_menu(callback: types.CallbackQuery):
    """Shows category selection keyboard for a specific item."""
    _, item_id_str, receipt_id_str = callback.data.split(":")
    item_id, receipt_id = int(item_id_str), int(receipt_id_str)

    await callback.message.edit_reply_markup(reply_markup=get_item_categories_keyboard(item_id, receipt_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("set_item_cat:"))
async def set_item_category_handler(callback: types.CallbackQuery):
    """Applies new category to a specific item."""
    _, item_id_str, receipt_id_str, new_category = callback.data.split(":")
    item_id, receipt_id = int(item_id_str), int(receipt_id_str)

    async with AsyncSessionLocal() as session:
        updated_receipt = await update_receipt_item_field(
            session=session,
            item_id=item_id,
            field="category",
            new_value=new_category
        )

    if updated_receipt:
        formatted_text = format_receipt_text(updated_receipt)
        await callback.message.edit_text(
            text=formatted_text,
            parse_mode="HTML",
            reply_markup=get_single_item_edit_keyboard(item_id, receipt_id)
        )
        await callback.answer(f"Category changed to {new_category}!")
    else:
        await callback.answer("Failed to update item category.", show_alert=True)


# --- Photo Upload and Processing Handler ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    await message.answer("📥 Checking photo and downloading from Telegram...")

    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)

    file_bytes = io.BytesIO()
    await bot.download_file(file_info.file_path, destination=file_bytes)
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

        blob_client = blob_service_client.get_blob_client(
            container=AZURE_CONTAINER_NAME, blob=blob_name
        )

        await asyncio.to_thread(blob_client.upload_blob, raw_bytes, overwrite=True)
        await asyncio.to_thread(process_receipt_task.delay, blob_name, message.chat.id)

        await message.answer(
            f"✅ Photo uploaded to Azure Blob Storage successfully!\n"
            f"• Processing with AI...",
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"Error handling photo upload: {e}")
        await message.answer("❌ Failed to process photo.")


async def main():
    logging.basicConfig(level=logging.INFO)

    ensure_container_exists()

    logging.info("Bot started!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())