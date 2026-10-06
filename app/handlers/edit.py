from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from db.crud import get_receipt_by_id, update_receipt_field, update_receipt_item_field
from db.database import AsyncSessionLocal
from handlers.cards import receipt_card
from keyboards import (
    MAIN_MENU_BUTTONS,
    PRESET_CATEGORIES,
    get_edit_fields_keyboard,
    get_item_categories_keyboard,
    get_items_selection_keyboard,
    get_receipt_inline_keyboard,
    get_single_item_edit_keyboard,
)
from states import EditItemState, EditReceiptState

router = Router(name="edit")

ALLOWED_CATEGORIES = {cat_code for _, cat_code in PRESET_CATEGORIES}

# Fields users may edit, mapped to their max text length (None = not a free-text field)
EDITABLE_RECEIPT_FIELDS = {"store_name": 128, "date": None, "total_amount": None}
EDITABLE_ITEM_FIELDS = {"name": 255, "total_price": None}

# Numeric(10, 2) columns hold values strictly below 10^8
MAX_MONEY_AMOUNT = Decimal("100000000")


def parse_money_amount(raw_text: str, allow_negative: bool = False) -> Decimal | None:
    """Parses a user-entered amount; returns None unless it is a finite number with abs value below MAX_MONEY_AMOUNT.

    Negative amounts are only accepted with allow_negative (item lines can be discounts).
    """
    try:
        value = Decimal(raw_text.replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return None
    if not value.is_finite() or abs(value) >= MAX_MONEY_AMOUNT:
        return None
    if value < 0 and not allow_negative:
        return None
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if abs(value) >= MAX_MONEY_AMOUNT:  # e.g. 99999999.999 rounds up to 10^8
        return None
    return value


async def get_edit_input_text(message: types.Message) -> str | None:
    """Returns the stripped text of an edit reply, or asks for text and returns None if there is none."""
    raw_text = message.text.strip() if message.text else ""
    if raw_text in MAIN_MENU_BUTTONS or raw_text.startswith("/"):
        # Already cancelled by interrupt_edit_handler (handlers/common.py); never store it as a value.
        return None
    if not raw_text:
        await message.answer("❌ Please send the new value as a text message, or /cancel to stop editing.")
        return None
    return raw_text


# --- Entering and Leaving Edit Mode ---

@router.callback_query(F.data.startswith("edit_receipt:"))
async def edit_receipt_init_handler(callback: types.CallbackQuery):
    """Handler triggered when clicking '✏️ Edit' on a receipt card."""
    receipt_id = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=get_edit_fields_keyboard(receipt_id))
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_edit:"))
async def cancel_edit_handler(callback: types.CallbackQuery, state: FSMContext):
    """Cancels the edit flow and restores original card buttons."""
    receipt_id = int(callback.data.split(":")[1])
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=get_receipt_inline_keyboard(receipt_id))
    await callback.answer("Editing cancelled.")


# --- Editing Main Receipt Fields (Store, Date, Total Amount) ---

@router.callback_query(F.data.startswith("edit_field:"))
async def select_field_to_edit_handler(callback: types.CallbackQuery, state: FSMContext):
    """Handles main field selection for editing and prompts user for input."""
    _, field, receipt_id_str = callback.data.split(":")
    receipt_id = int(receipt_id_str)

    if field not in EDITABLE_RECEIPT_FIELDS:
        await callback.answer("❌ This field cannot be edited.", show_alert=True)
        return

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


@router.message(EditReceiptState.waiting_for_value)
async def process_new_field_value_handler(message: types.Message, state: FSMContext):
    """Receives the new main field value, updates DB, and refreshes receipt message."""
    raw_text = await get_edit_input_text(message)
    if raw_text is None:
        return

    user_data = await state.get_data()
    receipt_id = user_data["receipt_id"]
    field = user_data["field"]
    target_msg_id = user_data["message_id"]

    if field not in EDITABLE_RECEIPT_FIELDS:
        await state.clear()
        await message.answer("❌ This field cannot be edited.")
        return

    parsed_value = raw_text

    if field == "total_amount":
        parsed_value = parse_money_amount(raw_text)
        if parsed_value is None:
            await message.answer(
                "❌ Invalid amount. Please enter a number from 0 to 99999999.99 (e.g., 15.50):"
            )
            return
    elif field == "store_name" and len(raw_text) > EDITABLE_RECEIPT_FIELDS["store_name"]:
        await message.answer(
            f"❌ Store name is too long (max {EDITABLE_RECEIPT_FIELDS['store_name']} characters). Please send a shorter one:"
        )
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
        formatted_text = await receipt_card(updated_receipt, message.from_user.id)
        await message.bot.edit_message_text(
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

@router.callback_query(F.data.startswith("edit_items_menu:"))
async def edit_items_menu_handler(callback: types.CallbackQuery):
    """Displays the list of item numbers to choose for editing."""
    receipt_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        receipt = await get_receipt_by_id(session, receipt_id, callback.from_user.id)

    if receipt:
        await callback.message.edit_reply_markup(reply_markup=get_items_selection_keyboard(receipt))
    await callback.answer()


@router.callback_query(F.data.startswith("select_item:"))
async def select_item_handler(callback: types.CallbackQuery):
    """Displays edit options for a specific item (Name, Price, Category)."""
    _, item_id_str, receipt_id_str = callback.data.split(":")
    item_id, receipt_id = int(item_id_str), int(receipt_id_str)

    await callback.message.edit_reply_markup(reply_markup=get_single_item_edit_keyboard(item_id, receipt_id))
    await callback.answer()


@router.callback_query(F.data.startswith("edit_item_field:"))
async def select_item_field_to_edit(callback: types.CallbackQuery, state: FSMContext):
    """Prompts user for new value (Name or Price) of a specific item."""
    _, field, item_id_str, receipt_id_str = callback.data.split(":")
    item_id, receipt_id = int(item_id_str), int(receipt_id_str)

    if field not in EDITABLE_ITEM_FIELDS:
        await callback.answer("❌ This field cannot be edited.", show_alert=True)
        return

    await state.update_data(
        item_id=item_id,
        receipt_id=receipt_id,
        field=field,
        message_id=callback.message.message_id
    )
    await state.set_state(EditItemState.waiting_for_value)

    prompt_messages = {
        "name": "Please send the new item name:",
        "total_price": "Please send the new total price for this item (e.g., 25.50, or -3.00 for a discount):"
    }

    await callback.message.answer(
        prompt_messages.get(field, "Please send the new value:"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditItemState.waiting_for_value)
async def process_new_item_field_value(message: types.Message, state: FSMContext):
    """Receives new value for item field, updates DB, and updates message card."""
    raw_text = await get_edit_input_text(message)
    if raw_text is None:
        return

    user_data = await state.get_data()
    item_id = user_data["item_id"]
    receipt_id = user_data["receipt_id"]
    field = user_data["field"]
    target_msg_id = user_data["message_id"]

    if field not in EDITABLE_ITEM_FIELDS:
        await state.clear()
        await message.answer("❌ This field cannot be edited.")
        return

    parsed_value = raw_text

    if field == "total_price":
        parsed_value = parse_money_amount(raw_text, allow_negative=True)
        if parsed_value is None:
            await message.answer(
                "❌ Invalid price. Please enter a number from -99999999.99 to 99999999.99 "
                "(e.g., 15.50, or -3.00 for a discount):"
            )
            return
    elif field == "name" and len(raw_text) > EDITABLE_ITEM_FIELDS["name"]:
        await message.answer(
            f"❌ Item name is too long (max {EDITABLE_ITEM_FIELDS['name']} characters). Please send a shorter one:"
        )
        return

    async with AsyncSessionLocal() as session:
        updated_receipt = await update_receipt_item_field(
            session=session,
            item_id=item_id,
            user_id=message.from_user.id,
            field=field,
            new_value=parsed_value
        )

    if updated_receipt:
        formatted_text = await receipt_card(updated_receipt, message.from_user.id)
        await message.bot.edit_message_text(
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


@router.callback_query(F.data.startswith("select_item_category:"))
async def select_item_category_menu(callback: types.CallbackQuery):
    """Shows category selection keyboard for a specific item."""
    _, item_id_str, receipt_id_str = callback.data.split(":")
    item_id, receipt_id = int(item_id_str), int(receipt_id_str)

    await callback.message.edit_reply_markup(reply_markup=get_item_categories_keyboard(item_id, receipt_id))
    await callback.answer()


@router.callback_query(F.data.startswith("set_item_cat:"))
async def set_item_category_handler(callback: types.CallbackQuery):
    """Applies new category to a specific item."""
    _, item_id_str, receipt_id_str, new_category = callback.data.split(":")
    item_id, receipt_id = int(item_id_str), int(receipt_id_str)

    if new_category not in ALLOWED_CATEGORIES:
        await callback.answer("❌ Unknown category.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        updated_receipt = await update_receipt_item_field(
            session=session,
            item_id=item_id,
            user_id=callback.from_user.id,
            field="category",
            new_value=new_category
        )

    if updated_receipt:
        formatted_text = await receipt_card(updated_receipt, callback.from_user.id)
        await callback.message.edit_text(
            text=formatted_text,
            parse_mode="HTML",
            reply_markup=get_single_item_edit_keyboard(item_id, receipt_id)
        )
        await callback.answer(f"Category changed to {new_category}!")
    else:
        await callback.answer("Failed to update item category.", show_alert=True)
