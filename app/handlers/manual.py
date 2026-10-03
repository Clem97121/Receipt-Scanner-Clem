import html
import os
from decimal import Decimal

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from db.crud import save_manual_expense
from db.database import AsyncSessionLocal
from db.family import ensure_user
from handlers.cards import receipt_card
from handlers.edit import ALLOWED_CATEGORIES, get_edit_input_text, parse_money_amount
from keyboards import (
    BTN_ADD_EXPENSE,
    PRESET_CATEGORIES,
    get_manual_cancel_keyboard,
    get_manual_category_keyboard,
    get_manual_description_keyboard,
    get_receipt_inline_keyboard,
)
from schemas import MAX_STORE_NAME_LENGTH
from states import ManualExpenseState
from timeutils import local_today

router = Router(name="manual")

DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "CZK")
CATEGORY_LABELS = {cat_code: label for label, cat_code in PRESET_CATEGORIES}


@router.message(F.text == BTN_ADD_EXPENSE)
@router.message(Command("add"))
async def start_manual_expense(message: types.Message, state: FSMContext):
    """Starts the manual expense form: amount -> category -> optional description."""
    await state.clear()
    await state.set_state(ManualExpenseState.waiting_for_amount)
    await message.answer(
        "✍️ <b>New expense</b>\n\nSend the amount (e.g., 250 or 12.50):",
        parse_mode="HTML",
        reply_markup=get_manual_cancel_keyboard(),
    )


@router.message(ManualExpenseState.waiting_for_amount)
async def manual_amount_handler(message: types.Message, state: FSMContext):
    """Receives the amount and asks for a category."""
    raw_text = await get_edit_input_text(message)
    if raw_text is None:
        return

    amount = parse_money_amount(raw_text)
    if amount is None or amount == 0:
        await message.answer("❌ Invalid amount. Please enter a number greater than 0 and below 100000000 (e.g., 12.50):")
        return

    await state.update_data(amount=str(amount))
    await state.set_state(ManualExpenseState.waiting_for_category)
    await message.answer(
        f"💰 Amount: <code>{amount} {html.escape(DEFAULT_CURRENCY)}</code>\n\nChoose a category:",
        parse_mode="HTML",
        reply_markup=get_manual_category_keyboard(),
    )


@router.message(ManualExpenseState.waiting_for_category)
async def manual_category_text_handler(message: types.Message):
    """Reminds the user to use the buttons when they type instead of choosing a category."""
    if await get_edit_input_text(message) is None:
        return
    await message.answer("Please choose a category with the buttons above, or /cancel.")


@router.callback_query(ManualExpenseState.waiting_for_category, F.data.startswith("manual_cat:"))
async def manual_category_handler(callback: types.CallbackQuery, state: FSMContext):
    """Stores the chosen category and asks for an optional description."""
    category = callback.data.split(":", 1)[1]
    if category not in ALLOWED_CATEGORIES:
        await callback.answer("❌ Unknown category.", show_alert=True)
        return

    await state.update_data(category=category)
    await state.set_state(ManualExpenseState.waiting_for_description)
    await callback.message.edit_text(
        f"🏷 Category: <b>{html.escape(CATEGORY_LABELS[category])}</b>\n\n"
        "Send a short description (e.g., taxi, coffee) or press Skip:",
        parse_mode="HTML",
        reply_markup=get_manual_description_keyboard(),
    )
    await callback.answer()


@router.message(ManualExpenseState.waiting_for_description)
async def manual_description_handler(message: types.Message, state: FSMContext):
    """Receives the description and saves the expense."""
    raw_text = await get_edit_input_text(message)
    if raw_text is None:
        return
    if len(raw_text) > MAX_STORE_NAME_LENGTH:
        await message.answer(
            f"❌ Description is too long (max {MAX_STORE_NAME_LENGTH} characters). Please send a shorter one:"
        )
        return
    await save_and_show_expense(message, message.from_user, state, description=raw_text)


@router.callback_query(ManualExpenseState.waiting_for_description, F.data == "manual_skip_description")
async def manual_skip_description_handler(callback: types.CallbackQuery, state: FSMContext):
    """Saves the expense without a description."""
    await callback.answer()
    await save_and_show_expense(callback.message, callback.from_user, state, description=None)


@router.callback_query(StateFilter(*ManualExpenseState.__states__), F.data == "manual_cancel")
async def manual_cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    """Cancels the manual expense form."""
    await state.clear()
    await callback.message.edit_text("✖️ Cancelled.")
    await callback.answer()


@router.callback_query(F.data.startswith("manual_"))
async def manual_stale_button_handler(callback: types.CallbackQuery):
    """Answers buttons of a form that was already finished or cancelled."""
    await callback.answer("This form is no longer active. Press «➕ Add expense» to start again.", show_alert=True)


async def save_and_show_expense(
    target: types.Message, user: types.User, state: FSMContext, description: str | None
) -> None:
    """Saves the collected expense, clears the form and shows the new receipt card."""
    data = await state.get_data()
    await state.clear()

    async with AsyncSessionLocal() as session:
        await ensure_user(session, user.id, user.username, user.full_name)
        receipt = await save_manual_expense(
            session,
            user_id=user.id,
            amount=Decimal(data["amount"]),
            category=data["category"],
            description=description,
            currency=DEFAULT_CURRENCY,
            expense_date=local_today(),
        )

    await target.answer(
        "✅ <b>Expense saved!</b>\n\n" + await receipt_card(receipt, user.id),
        parse_mode="HTML",
        reply_markup=get_receipt_inline_keyboard(receipt.id),
    )
